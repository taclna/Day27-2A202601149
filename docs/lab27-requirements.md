# Yêu cầu Lab 27: Agent Human-in-the-Loop đánh giá churn risk

## 1. Mục tiêu

Xây dựng một LangGraph workflow đánh giá rủi ro khách hàng rời bỏ (`churn risk`), đề xuất hành động giữ chân khách hàng và quyết định tự động thực thi hay chuyển cho con người xem xét.

Hệ thống phải bảo đảm hành động có rủi ro cao không được thực hiện trước khi có quyết định của reviewer, đồng thời lưu lại dấu vết kiểm toán cho mọi quyết định quan trọng.

## 2. Luồng nghiệp vụ bắt buộc

```text
Customer Data
      |
      v
Agent Reasoning
      |
      | proposed_action
      | confidence_score
      | reasoning
      v
Confidence Routing + Hard Rules
      |
      +-----------------------------+
      |                             |
      | Low-risk                    | High-risk / cần review
      v                             v
Auto Execute                  Interrupt Graph
                                    |
                                    v
                             Streamlit Review
                              /      |      \
                         Approve   Reject    Edit
                            |        |        |
                            +--------+--------+
                                     |
                                     v
                                Resume Graph
                                     |
                                     v
                                 Audit Log
```

## 3. Công nghệ và điều kiện tối thiểu

- Python 3.10 trở lên.
- Các thư viện chính: `langgraph`, `langchain`, `streamlit`, `pydantic`.
- Ứng dụng chạy cục bộ; Streamlit là giao diện review.
- LangGraph sử dụng `MemorySaver` để giữ checkpoint trong thời gian tiến trình đang chạy.

## 4. Cấu trúc đầu ra

Cấu trúc tối thiểu theo đề bài:

```text
day27-hitl/
├── app.py
├── graph.py
├── models.py
├── audit_log.json
└── requirements.txt
```

Project có thể bổ sung module audit, test và tài liệu nếu vẫn giữ đúng các file bắt buộc trên.

## 5. State và schema kiểm toán

### 5.1. `GraphState`

`GraphState` phải là một `TypedDict` và có tối thiểu các trường:

- `customer_id: str`
- `proposed_action: str`
- `confidence_score: float`
- `reasoning: str`
- `human_decision: str | None`

State phải:

- Tồn tại xuyên suốt workflow.
- Không bị mất khi graph bị interrupt.
- Cho phép Streamlit cập nhật `human_decision` trước khi resume graph.

### 5.2. `AuditEntry`

`AuditEntry` phải là một Pydantic `BaseModel` và có các trường:

- `timestamp`
- `agent_id`
- `action`
- `confidence`
- `reviewer_id`
- `decision`

Mỗi entry phải trả lời được: agent nào đề xuất, action nào được đề xuất hoặc thực thi, confidence bao nhiêu, ai review, reviewer quyết định gì và quyết định xảy ra lúc nào.

## 6. Agent reasoning

Phải có node:

```python
evaluate_customer(state)
```

Node đánh giá dữ liệu khách hàng, bao gồm Total Operating Income (TOI) và churn probability, rồi trả về:

- `proposed_action`
- `confidence_score`
- `reasoning`

Các action cốt lõi:

- `send_email`: hành động rủi ro thấp.
- `increase_credit_limit`: hành động rủi ro cao.

`confidence_score` phải nằm trong khoảng từ `0.0` đến `1.0`. Confidence cao không được phép vượt qua hard policy.

## 7. Routing và hard policy

Phải có conditional edge function:

```python
route_action(state)
```

Routing phải kiểm tra theo đúng thứ tự:

1. **Policy Override:** `increase_credit_limit` luôn route đến `execute_high_risk_action`, bất kể confidence.
2. **Auto-Execute:** action rủi ro thấp với `confidence_score >= 0.85` route đến `execute_low_risk_action`.
3. **Escalate/Suggest:** `confidence_score < 0.85` route đến `execute_high_risk_action` để chờ human review.

Các trường hợp nghiệm thu bắt buộc:

| Action | Confidence | Kết quả |
|---|---:|---|
| `increase_credit_limit` | `0.99` | Human Review |
| `send_email` | `0.90` | `execute_low_risk_action` |
| `send_email` | `0.82` | Human Review |

## 8. LangGraph checkpoint và interrupt

Graph phải được compile tương đương với:

```python
memory = MemorySaver()
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["execute_high_risk_action"],
)
```

Khi route đến high-risk node:

- `execute_high_risk_action` chưa được chạy.
- Graph ở trạng thái pending.
- State vẫn chứa dữ liệu khách hàng và đề xuất của agent.
- Lần resume phải dùng cùng `thread_id` với lần invoke ban đầu.

## 9. Streamlit approval interface

Giao diện phải hiển thị:

- Customer ID.
- Proposed action.
- Confidence score.
- Reasoning.
- Ba lựa chọn: Approve, Reject và Edit.

Sau khi reviewer quyết định, giao diện phải:

1. Gọi `graph.update_state(config, {...})` để cập nhật state.
2. Gọi `graph.invoke(None, config)` để resume đúng graph đang pending.

Ý nghĩa quyết định:

- **Approve:** thực hiện action do agent đề xuất.
- **Reject:** hủy action, không thực hiện.
- **Edit:** cập nhật action theo nội dung reviewer sửa rồi thực hiện action đã sửa.

Compiled graph cần được giữ trong `st.session_state` để không bị tạo lại ngoài ý muốn sau mỗi lần Streamlit rerun.

## 10. Audit trail

Sau mỗi human decision, `audit_log.json` phải có một entry mới. Cả Approve, Reject và Edit đều phải được log.

Quy trình ghi file phải:

1. Đọc danh sách entry hiện có.
2. Append `AuditEntry` mới.
3. Ghi lại toàn bộ danh sách hợp lệ.
4. Không ghi đè làm mất lịch sử cũ.

Trong production nên thay file JSON bằng append-only database, chẳng hạn PostgreSQL.

## 11. Tiêu chí tự kiểm tra

- `GraphState` có đủ năm trường bắt buộc.
- State còn nguyên trước và sau interrupt.
- `evaluate_customer` trả về đủ ba trường và confidence hợp lệ.
- Hard rule được xét trước confidence.
- Auto-execute đúng với `send_email` confidence `0.90`.
- Escalation đúng với `send_email` confidence `0.82`.
- High-risk node chưa chạy trước review.
- Approve thực thi action.
- Reject hủy action.
- Edit thực thi action đã chỉnh sửa.
- Mọi human decision được append vào audit log.
- Các lần invoke, get state, update state và resume dùng cùng `thread_id`.

## 12. Reflection Questions cần trả lời

Tài liệu bàn giao cuối cùng cần giải thích:

1. Khi cần con người rewrite email sau lúc email được generate nhưng trước routing, nên dùng `interrupt_after` ở node generate hay `interrupt_before` ở node kế tiếp, và lý do lựa chọn.
2. Cách giảm alert fatigue khi có khoảng 500 action `send_email` mỗi ngày với confidence quanh `0.82`, ngay dưới threshold `0.85`.
3. Vì sao không nên tin hoàn toàn confidence tự báo của LLM và cách calibrate confidence trước routing.

## 13. Yêu cầu nộp bài

Bài làm là artefact cá nhân và được nộp bằng link repository GitHub cá nhân chứa toàn bộ Lab 27.

Repository phải thể hiện tối thiểu:

- `GraphState`
- `AuditEntry`
- `evaluate_customer`
- `route_action`
- `execute_low_risk_action`
- `execute_high_risk_action`
- `MemorySaver`
- `interrupt_before`
- Streamlit approval interface
- Audit log

README phải mô tả:

- Cách cài dependency bằng `pip install -r requirements.txt`.
- Cách chạy LangGraph workflow.
- Cách chạy Streamlit UI bằng `streamlit run app.py`.
- Confidence threshold đang sử dụng.
- Hard policy rule.
- Cách thực hiện Approve, Reject và Edit.
- Vị trí lưu audit log.

Repository không được chứa:

- API key.
- Access token.
- Password.
- Private key.
- File `.env` có credential thật.

Link nộp có dạng:

```text
https://github.com/<YOUR_USERNAME>/Day27-HITL
```

Việc push repository và dán link lên hệ thống nộp bài là thao tác riêng sau khi mã nguồn đã được kiểm tra và người dùng cho phép.
