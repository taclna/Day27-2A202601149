# Lab 27 — Agent Human-in-the-Loop với LangGraph

Ứng dụng đánh giá nguy cơ khách hàng rời bỏ (`churn risk`), đề xuất hành động giữ chân và dùng Human-in-the-Loop (HITL) để chặn các hành động rủi ro cao trước khi thực thi.

Repository nộp bài: <https://github.com/taclna/Day27-2A202601449>

## Chức năng

- `GraphState` giữ dữ liệu khách hàng, đề xuất, confidence, reasoning và human decision.
- Agent rule-based đánh giá Total Operating Income (TOI) và churn probability.
- Hard policy luôn chuyển `increase_credit_limit` sang human review.
- `send_email` chỉ auto-execute khi confidence từ `0.85` trở lên.
- `MemorySaver` giữ checkpoint khi graph bị tạm dừng.
- `interrupt_before=["execute_high_risk_action"]` bảo đảm high-risk node chưa chạy trước review.
- Streamlit hiển thị đề xuất và hỗ trợ Approve, Reject, Edit.
- Audit trail JSON ghi cả quyết định tự động và quyết định của reviewer.

## Kiến trúc

```text
Customer Data
      |
      v
evaluate_customer
      |
      v
route_action (hard policy trước confidence)
      |
      +------------------------------+
      |                              |
      v                              v
execute_low_risk_action      interrupt trước high-risk
      |                              |
      |                              v
      |                       Streamlit Review
      |                      Approve/Reject/Edit
      |                              |
      |                              v
      |                    execute_high_risk_action
      |                              |
      +---------------+--------------+
                      v
                audit_log.json
```

## Cấu trúc project

```text
.
├── app.py                  # Streamlit approval interface
├── audit.py                # Đọc và append audit JSON
├── audit_log.json          # Audit trail cục bộ
├── demo.py                 # CLI demo LangGraph workflow
├── graph.py                # State, nodes, routing và graph compilation
├── models.py               # Pydantic AuditEntry
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Runtime + pytest
├── tests/                  # Automated tests
└── docs/                   # Yêu cầu, design và implementation plan
```

## Cài đặt

Yêu cầu Python 3.10 trở lên.

### PowerShell trên Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Ứng dụng không cần API key hoặc file `.env`.

## Chạy LangGraph workflow

Chạy customer mẫu theo nhánh low-risk auto-execute:

```powershell
python demo.py
```

Kết quả gồm Customer ID, proposed action, confidence, reasoning và execution status. Lần chạy này append một entry `auto_execute` vào `audit_log.json`.

## Chạy Streamlit UI

```powershell
streamlit run app.py
```

Sau khi trình duyệt mở:

1. Nhập Customer ID, TOI, churn probability và Reviewer ID.
2. Chọn **Đánh giá khách hàng**.
3. Nếu action được auto-execute, UI hiển thị kết quả ngay.
4. Nếu graph đang pending, kiểm tra action, confidence và reasoning rồi chọn:
   - **Approve:** thực thi action gốc.
   - **Reject:** hủy action.
   - **Edit:** nhập action thay thế rồi thực thi action đã sửa.
5. Xem entry mới trong bảng **Audit trail** cuối trang.

Streamlit giữ compiled graph và `thread_id` trong `st.session_state`. Khi review, ứng dụng gọi `graph.update_state(...)`, sau đó `graph.invoke(None, config)` với cùng config để resume checkpoint.

## Confidence routing và hard policy

Threshold đang dùng:

```text
AUTO_EXECUTE_THRESHOLD = 0.85
```

Routing kiểm tra theo thứ tự:

1. Nếu action là `increase_credit_limit`, luôn chuyển tới `execute_high_risk_action` và dừng trước node để human review.
2. Nếu action khác có confidence `>= 0.85`, chuyển tới `execute_low_risk_action`.
3. Nếu confidence `< 0.85`, chuyển tới high-risk path để review.

| Action | Confidence | Kết quả |
|---|---:|---|
| `increase_credit_limit` | `0.99` | Human review |
| `send_email` | `0.90` | Auto-execute |
| `send_email` | `0.82` | Human review |

## Logic agent mẫu

Agent trong lab là rule-based để chạy ổn định mà không cần LLM/API key:

| Dữ liệu khách hàng | Proposed action | Confidence |
|---|---|---:|
| Churn `>= 0.75` và TOI `>= 20.000.000` | `increase_credit_limit` | `0.96` |
| Churn `>= 0.50`, không thuộc dòng trên | `send_email` | `0.82` |
| Churn `< 0.50` | `send_email` | `0.90` |

Confidence cao không được bypass hard policy.

## GraphState

State có đầy đủ năm field bắt buộc:

```python
customer_id: str
proposed_action: str
confidence_score: float
reasoning: str
human_decision: str | None
```

Các field bổ sung lưu TOI, churn probability, reviewer, action sửa và execution status. Với Edit, UI ghi action thay thế vào `edited_action` để không làm conditional edge chạy lại và bypass high-risk node. Sau resume, high-risk node cập nhật `proposed_action` bằng action đã sửa.

## Audit log

Audit trail được lưu tại:

```text
audit_log.json
```

Mỗi `AuditEntry` có:

```json
{
  "timestamp": "2026-08-29T09:00:00+00:00",
  "agent_id": "churn-risk-agent",
  "action": "increase_credit_limit",
  "confidence": 0.96,
  "reviewer_id": "operator_01",
  "decision": "approve"
}
```

Audit writer đọc lịch sử, append entry mới và thay file bằng một bản JSON hoàn chỉnh. Nếu JSON hiện tại hỏng, ứng dụng báo lỗi và không overwrite dữ liệu cũ. Đây là demo cục bộ; production nên dùng append-only database và cơ chế đồng bộ nhiều writer.

## Chạy kiểm thử

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

Test suite bao phủ schema, audit persistence, reasoning, routing, hard policy, interrupt state, auto-execute, Approve, Reject, Edit, invalid decision, CLI và Streamlit interaction.

## Reflection Questions

### 1. Rewrite email trước routing nên dùng interrupt nào?

Nếu email vừa được generate và cần con người rewrite trước routing, dùng `interrupt_after` tại node generate là cách biểu đạt trực tiếp: node generate đã hoàn thành và routing chưa bắt đầu. `interrupt_before` tại routing node kế tiếp có thể cho hành vi tương đương. Dùng `interrupt_after` làm ranh giới nghiệp vụ dễ đọc hơn; node generate vẫn cần idempotent nếu có side effect.

### 2. Làm sao giảm alert fatigue với 500 email confidence 0.82 mỗi ngày?

Không nên chỉ hạ threshold. Có thể batch các email tương tự, xếp hàng theo churn impact và giá trị khách hàng, hỗ trợ bulk approve có lấy mẫu, và dùng một vùng xám với sampling động. Nên calibrate trên lịch sử reviewer override và đặt threshold theo action hoặc customer segment thay vì một ngưỡng chung cho mọi trường hợp.

### 3. Vì sao confidence tự báo của LLM nguy hiểm và calibrate thế nào?

Confidence tự báo không phải xác suất đã hiệu chỉnh; LLM có thể rất tự tin dù dữ liệu thu nhập sai hoặc thiếu. Trước routing cần kiểm tra dữ liệu với nguồn có thẩm quyền, thêm data-quality signals và calibrate score trên validation set có nhãn bằng Platt scaling hoặc isotonic regression. Theo dõi reliability diagram, Brier score và hiệu năng theo phân khúc. Hard policy vẫn phải độc lập với calibrated confidence.

## An toàn repository

- Không lưu API key, access token, password hoặc private key.
- `.env`, `*.pem`, `*.key`, virtual environment và cache được loại trừ bằng `.gitignore`.
- Workflow chỉ mô phỏng action; không gửi email hoặc thay đổi hạn mức thật.
- Không push repository hoặc nộp link tự động nếu chưa có xác nhận của chủ repository.

## Tài liệu thiết kế

- [Yêu cầu Lab 27](docs/lab27-requirements.md)
- [Design spec](docs/superpowers/specs/2026-08-29-hitl-churn-risk-design.md)
- [Implementation plan](docs/superpowers/plans/2026-08-29-hitl-churn-risk.md)
