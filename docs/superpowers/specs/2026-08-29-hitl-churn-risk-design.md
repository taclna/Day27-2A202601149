# Thiết kế hệ thống Agent HITL đánh giá churn risk

## 1. Phạm vi

Thiết kế này triển khai các yêu cầu trong `docs/lab27-requirements.md` thành một ứng dụng demo chạy cục bộ, không cần API key và không phụ thuộc vào dịch vụ LLM bên ngoài. Mục tiêu là minh họa chính xác state persistence, policy routing, interrupt/resume, human approval và audit trail.

Ứng dụng không thực hiện gửi email thật hoặc thay đổi hạn mức tín dụng thật. Các node execute chỉ tạo kết quả mô phỏng và ghi audit log.

## 2. Các phương án đã cân nhắc

### Phương án A — Agent rule-based xác định (chọn)

`evaluate_customer` dùng TOI và churn probability để sinh output có thể lặp lại. Phương án này dễ chạy, dễ test, không có chi phí API và bám sát mục tiêu học LangGraph HITL.

### Phương án B — Gọi LLM thật

Output tự nhiên hơn nhưng cần API key, prompt/schema parsing, xử lý lỗi mạng và kiểm soát tính không xác định. Phần phức tạp này không giúp chứng minh cơ chế interrupt/resume tốt hơn.

### Phương án C — Provider abstraction hỗ trợ cả mock và LLM

Linh hoạt hơn nhưng tạo thêm interface và cấu hình chưa cần thiết cho một lab nhỏ. Có thể bổ sung sau nếu project phát triển thành ứng dụng thật.

## 3. Kiến trúc module

```text
app.py
  |
  | build_graph(), invoke(), get_state(), update_state()
  v
graph.py -----------------------> audit.py
  |                                  |
  | GraphState                       | append_audit_entry()
  | evaluate_customer()              v
  | route_action()               audit_log.json
  | execution nodes
  v
models.py
  |
  | AuditEntry
  v
Pydantic validation
```

Trách nhiệm từng file:

- `models.py`: chỉ chứa schema Pydantic và validation liên quan.
- `audit.py`: chỉ quản lý việc đọc và append audit trail.
- `graph.py`: định nghĩa state, reasoning, routing, execution nodes và graph factory.
- `app.py`: quản lý Streamlit session, input form, action card và quyết định reviewer.
- `tests/`: kiểm tra logic miền nghiệp vụ và hành vi graph, không phụ thuộc trình duyệt.

## 4. Mô hình state

`GraphState` là `TypedDict` có năm trường bắt buộc của lab:

```python
customer_id: str
proposed_action: str
confidence_score: float
reasoning: str
human_decision: str | None
```

State bổ sung các trường cần cho demo hoàn chỉnh:

- `total_operating_income: float`: TOI đầu vào, không âm.
- `churn_probability: float`: xác suất churn trong `[0.0, 1.0]`.
- `reviewer_id: str`: người đưa ra human decision.
- `execution_status: str`: kết quả mô phỏng (`executed`, `rejected` hoặc trạng thái mô tả tương đương).

Năm trường của lab luôn tồn tại trong initial state. Các trường bổ sung giúp node không phụ thuộc vào biến toàn cục hoặc dữ liệu UI nằm ngoài checkpoint.

## 5. Agent reasoning xác định

`evaluate_customer(state)` dùng ba nhánh rõ ràng:

| Điều kiện | Action | Confidence | Ý nghĩa |
|---|---|---:|---|
| `churn_probability >= 0.75` và `TOI >= 20_000_000` | `increase_credit_limit` | `0.96` | Khách hàng giá trị cao, nguy cơ churn cao; đề xuất tài chính bắt buộc review |
| `0.50 <= churn_probability < 0.75`, hoặc churn cao nhưng không đạt điều kiện TOI | `send_email` | `0.82` | Có tín hiệu churn nhưng bằng chứng chưa đủ mạnh; cần review |
| `churn_probability < 0.50` | `send_email` | `0.90` | Chỉ cần liên hệ ít rủi ro và đủ confidence để tự động thực thi |

Các mức cố định chủ ý làm cho cả ba nhánh của lab dễ tái hiện. Node trả về partial state gồm `proposed_action`, `confidence_score` và `reasoning`.

Input không hợp lệ được chặn ở Streamlit và được kiểm tra lại trong node để API Python không thể bỏ qua validation.

## 6. Routing và policy precedence

`route_action(state)` thực hiện đúng thứ tự:

```text
action == increase_credit_limit
    -> execute_high_risk_action
else confidence >= 0.85
    -> execute_low_risk_action
else
    -> execute_high_risk_action
```

Việc xét action trước confidence bảo đảm hard policy không bao giờ bị confidence override. Tên node được trả về trực tiếp để conditional edges ánh xạ rõ ràng.

## 7. Interrupt và resume

`build_graph()` tạo `StateGraph`, thêm ba node, conditional edges và compile bằng một `MemorySaver`. Graph được cấu hình:

```python
interrupt_before=["execute_high_risk_action"]
```

Mỗi case dùng một `thread_id` UUID. Khi route high-risk, checkpoint chứa toàn bộ customer state và `snapshot.next` trỏ đến high-risk node nhưng node chưa chạy.

Streamlit lưu compiled graph, config và thread ID trong `st.session_state`. Khi reviewer quyết định, UI gọi `update_state` với decision, reviewer và action đã sửa (nếu có), sau đó gọi `invoke(None, config)` để tiếp tục từ checkpoint.

## 8. Hành vi execution node

### Low risk

`execute_low_risk_action` mô phỏng thực thi, đặt `execution_status = "executed"` và ghi audit entry với:

- `reviewer_id = "system"`
- `decision = "auto_execute"`

Việc ghi cả quyết định tự động tạo audit trail đầy đủ hơn yêu cầu tối thiểu.

### High risk

`execute_high_risk_action` chỉ chạy sau resume:

- `approve`: giữ nguyên action, đặt trạng thái đã thực thi.
- `reject`: không thực thi, đặt trạng thái bị từ chối.
- `edit`: dùng `proposed_action` đã được UI cập nhật, rồi đặt trạng thái đã thực thi.

Decision thiếu hoặc không hợp lệ gây lỗi rõ ràng thay vì âm thầm thực thi. Mỗi nhánh hợp lệ tạo đúng một audit entry.

## 9. Audit trail

`AuditEntry` dùng Pydantic để bảo đảm confidence thuộc `[0.0, 1.0]` và các chuỗi bắt buộc không rỗng. Timestamp dùng UTC ISO 8601.

`append_audit_entry(entry, path)`:

1. Đọc JSON hiện có; file rỗng hoặc chưa tồn tại được xem là danh sách rỗng.
2. Xác nhận root JSON là một list; JSON hỏng tạo lỗi rõ ràng để tránh mất dấu vết.
3. Append entry mới trong bộ nhớ.
4. Ghi qua file tạm cùng thư mục rồi thay thế file đích để giảm nguy cơ file dở dang.

Đường dẫn audit được inject vào graph factory, nhờ đó test dùng file tạm và không làm bẩn audit thật.

## 10. Thiết kế Streamlit

Giao diện gồm:

1. Form nhập `customer_id`, TOI, churn probability và reviewer ID.
2. Nút đánh giá tạo thread mới và invoke graph.
3. Action card hiển thị customer, proposed action, confidence và reasoning.
4. Nếu graph pending, hiển thị Approve, Reject và khu vực Edit.
5. Sau quyết định, resume graph rồi hiển thị execution status.
6. Bảng audit trail được tải lại từ JSON sau mỗi action.

Nút Edit đi kèm ô nhập action thay thế. UI không cho submit action sửa thành chuỗi rỗng.

## 11. Xử lý lỗi

- Customer ID và reviewer ID không được rỗng.
- TOI không âm; churn probability phải trong `[0.0, 1.0]`.
- Confidence ngoài `[0.0, 1.0]` bị từ chối.
- Resume luôn dùng config/thread ID đã lưu; không tự tạo ID mới.
- Audit JSON hỏng được báo lỗi và giữ nguyên file thay vì ghi đè.
- High-risk node từ chối chạy nếu chưa có human decision hợp lệ.
- Lỗi được Streamlit hiển thị bằng thông báo thân thiện; chi tiết exception vẫn hữu ích khi chạy test/terminal.

## 12. Chiến lược kiểm thử

Kiểm thử tự động dùng `pytest` và file tạm:

- Schema: `AuditEntry` hợp lệ; confidence ngoài miền bị từ chối.
- Reasoning: mỗi vùng churn/TOI trả đúng action, confidence và reasoning không rỗng.
- Routing: ba case bắt buộc `0.99`, `0.90`, `0.82`; hard rule luôn ưu tiên.
- Interrupt: high-risk node chưa tạo audit trước review; snapshot vẫn giữ customer data.
- Approve: resume, thực thi action và append audit.
- Reject: resume, không thực thi và append audit.
- Edit: state nhận action mới, resume thực thi action mới và audit action mới.
- Auto-execute: low-risk hoàn tất không interrupt và ghi audit tự động.
- Audit persistence: entry mới được append, entry cũ còn nguyên; JSON hỏng không bị overwrite.
- Static/import smoke test: các module import được trên Python 3.10+.

Streamlit UI được xác minh thêm bằng lệnh khởi động headless để bắt lỗi import/runtime ban đầu; logic quyết định nằm trong các hàm testable thay vì gắn hoàn toàn vào button callback.

## 13. Reflection Questions — định hướng trả lời

### 13.1. Interrupt để rewrite email

Nếu email vừa được generate và cần dừng ngay sau đó để con người rewrite trước routing, dùng `interrupt_after` tại node generate là cách diễn đạt trực tiếp nhất. Một thiết kế tương đương là `interrupt_before` tại node routing kế tiếp. Chọn `interrupt_after` giúp checkpoint thể hiện rõ output generate đã hoàn tất còn routing chưa bắt đầu; nếu node generate có side effect thì phải bảo đảm resume không chạy lại side effect.

### 13.2. Giảm alert fatigue quanh ngưỡng 0.85

Không nên chỉ hạ threshold. Nên gom các email tương tự thành batch review, xếp hàng theo churn impact/giá trị khách hàng, cung cấp bulk approve với sampling, và thêm một vùng xám có sampling động. Về kiến trúc, dùng calibration trên dữ liệu lịch sử và theo dõi tỷ lệ reviewer override để điều chỉnh threshold theo action/segment thay vì một ngưỡng toàn cục.

### 13.3. Calibrate confidence

Confidence tự báo của LLM không phải xác suất đã được hiệu chỉnh; mô hình có thể tự tin dù dữ liệu đầu vào sai hoặc thiếu. Trước routing, đối chiếu dữ liệu với nguồn có thẩm quyền, tính feature/data-quality checks, rồi calibrate score trên tập validation có nhãn bằng Platt scaling hoặc isotonic regression. Theo dõi reliability diagram, Brier score và hiệu năng theo từng phân khúc; hard policy vẫn áp dụng độc lập với calibrated score.

## 14. Ngoài phạm vi

- Gửi email hoặc cập nhật hạn mức thật.
- Đăng nhập, phân quyền và quản lý nhiều reviewer đồng thời.
- Database production, distributed lock hoặc audit ledger bất biến.
- LLM provider, prompt management và API key.
- Deploy lên cloud.

Các phần này chỉ nên bổ sung sau khi demo HITL cốt lõi đã được nghiệm thu.

## 15. Artefact bàn giao và an toàn repository

README của repository sẽ là hướng dẫn bàn giao chính, gồm lệnh cài dependency, lệnh chạy workflow CLI, lệnh chạy Streamlit, confidence threshold `0.85`, hard rule cho `increase_credit_limit`, quy trình Approve/Reject/Edit và vị trí `audit_log.json`.

Project bổ sung một CLI demo nhỏ trong `graph.py` hoặc entry point tương đương để người chấm có thể chạy LangGraph workflow mà không cần mở Streamlit. CLI chỉ mô phỏng hành động và không gọi dịch vụ thật.

`.gitignore` loại trừ `.env`, các biến thể environment cục bộ, private key, cache Python, virtual environment và artefact test. File `.env.example` không cần thiết vì ứng dụng không sử dụng credential. Trước khi bàn giao sẽ quét tên file và nội dung được track để phát hiện chuỗi credential phổ biến.

Repository sau cùng phải chứa trực tiếp các artefact bắt buộc: `GraphState`, `AuditEntry`, hai function reasoning/routing, hai execution node, `MemorySaver`, cấu hình `interrupt_before`, giao diện Streamlit và audit log. Việc commit mã nguồn nằm trong phạm vi triển khai; push lên GitHub hoặc nộp link chỉ được thực hiện khi người dùng yêu cầu riêng.
