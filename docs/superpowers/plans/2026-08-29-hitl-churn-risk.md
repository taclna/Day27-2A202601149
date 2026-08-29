# HITL Churn Risk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây dựng và kiểm thử một LangGraph workflow đánh giá churn risk, tự động thực thi action ít rủi ro, interrupt action cần review, nhận Approve/Reject/Edit từ Streamlit và append audit trail.

**Architecture:** Logic nghiệp vụ xác định nằm trong `graph.py`, schema trong `models.py`, persistence JSON trong `audit.py`, còn `app.py` chỉ điều phối UI và session. Graph factory inject đường dẫn audit và checkpointer để test dùng tài nguyên cô lập; mọi high-risk execution chỉ xảy ra sau static interrupt và resume bằng cùng `thread_id`.

**Tech Stack:** Python 3.10+, LangGraph 1.x, LangChain 1.x, Streamlit 1.x, Pydantic 2.x, pytest 8.x.

**Spec:** `docs/superpowers/specs/2026-08-29-hitl-churn-risk-design.md`

## Global Constraints

- Giữ nguyên năm field bắt buộc: `customer_id`, `proposed_action`, `confidence_score`, `reasoning`, `human_decision`.
- Confidence phải thuộc `[0.0, 1.0]`; auto-execute threshold là `0.85`.
- `increase_credit_limit` luôn route tới human review trước khi xét confidence.
- Compile bằng `MemorySaver()` và `interrupt_before=["execute_high_risk_action"]`.
- Approve thực thi action gốc; Reject hủy; Edit thực thi action đã sửa.
- Audit mới phải append, không làm mất entry cũ và không overwrite JSON hỏng.
- Không gọi API thật, không cần credential và không commit `.env`, token, password hay private key.
- README phải bao phủ toàn bộ checklist nộp bài trong `docs/lab27-requirements.md`.

---

### Task 1: Dependency manifest, AuditEntry và append-only JSON audit

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `models.py`
- Create: `audit.py`
- Create: `audit_log.json`
- Create: `tests/test_models.py`
- Create: `tests/test_audit.py`

**Interfaces:**
- Consumes: Không có interface production trước đó.
- Produces: `AuditEntry`; `read_audit_log(path: str | Path) -> list[dict[str, object]]`; `append_audit_entry(entry: AuditEntry, path: str | Path) -> None`; `utc_timestamp() -> str`.

- [ ] **Step 1: Khai báo dependencies**

```text
# requirements.txt
langgraph>=1.0,<2.0
langchain>=1.0,<2.0
streamlit>=1.40,<2.0
pydantic>=2.7,<3.0

# requirements-dev.txt
-r requirements.txt
pytest>=8.0,<9.0
```

Khởi tạo `audit_log.json` bằng một JSON array rỗng: `[]`.

- [ ] **Step 2: Viết test RED cho schema**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from models import AuditEntry


def test_audit_entry_accepts_complete_valid_data():
    entry = AuditEntry(
        timestamp="2026-08-29T09:00:00+00:00",
        agent_id="churn-risk-agent",
        action="send_email",
        confidence=0.9,
        reviewer_id="system",
        decision="auto_execute",
    )
    assert entry.confidence == 0.9


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_audit_entry_rejects_confidence_outside_probability_range(confidence):
    with pytest.raises(ValidationError):
        AuditEntry(
            timestamp="2026-08-29T09:00:00+00:00",
            agent_id="churn-risk-agent",
            action="send_email",
            confidence=confidence,
            reviewer_id="system",
            decision="auto_execute",
        )
```

- [ ] **Step 3: Chạy test schema để xác nhận RED**

Run: `python -m pytest tests/test_models.py -v`

Expected: FAIL khi import `models.AuditEntry` vì module chưa tồn tại.

- [ ] **Step 4: Implement schema tối thiểu**

```python
# models.py
from pydantic import BaseModel, ConfigDict, Field


class AuditEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    timestamp: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reviewer_id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
```

- [ ] **Step 5: Chạy test schema để xác nhận GREEN**

Run: `python -m pytest tests/test_models.py -v`

Expected: 3 tests PASS.

- [ ] **Step 6: Viết test RED cho audit persistence**

```python
# tests/test_audit.py
import json
from pathlib import Path
import pytest
from audit import append_audit_entry, read_audit_log
from models import AuditEntry


def make_entry(action="send_email"):
    return AuditEntry(
        timestamp="2026-08-29T09:00:00+00:00",
        agent_id="churn-risk-agent",
        action=action,
        confidence=0.9,
        reviewer_id="operator_01",
        decision="approve",
    )


def test_append_preserves_existing_audit_history(tmp_path):
    path = tmp_path / "audit.json"
    append_audit_entry(make_entry("send_email"), path)
    append_audit_entry(make_entry("increase_credit_limit"), path)
    assert [item["action"] for item in read_audit_log(path)] == [
        "send_email", "increase_credit_limit"
    ]


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid audit log JSON"):
        append_audit_entry(make_entry(), path)
    assert path.read_text(encoding="utf-8") == "not-json"
```

- [ ] **Step 7: Chạy audit tests để xác nhận RED**

Run: `python -m pytest tests/test_audit.py -v`

Expected: FAIL vì `audit.py` chưa tồn tại.

- [ ] **Step 8: Implement audit functions**

`read_audit_log` trả `[]` khi file chưa tồn tại hoặc rỗng, parse JSON list và raise `ValueError("Invalid audit log JSON: ...")` khi decode lỗi. `append_audit_entry` gọi `entry.model_dump(mode="json")`, append, ghi UTF-8 indent 2 vào file tạm cùng thư mục rồi `replace` file đích. `utc_timestamp` dùng `datetime.now(timezone.utc).isoformat()`.

- [ ] **Step 9: Chạy Task 1 tests để xác nhận GREEN**

Run: `python -m pytest tests/test_models.py tests/test_audit.py -v`

Expected: toàn bộ tests PASS.

- [ ] **Step 10: Commit Task 1**

```bash
git add requirements.txt requirements-dev.txt models.py audit.py audit_log.json tests/test_models.py tests/test_audit.py
git commit -m "feat: add validated audit trail"
```

---

### Task 2: GraphState, agent reasoning và policy routing

**Files:**
- Create: `graph.py`
- Create: `tests/test_graph_logic.py`

**Interfaces:**
- Consumes: `AuditEntry`, `append_audit_entry`, `utc_timestamp` từ Task 1.
- Produces: `GraphState`; constants `AUTO_EXECUTE_THRESHOLD`, `HIGH_RISK_ACTION`; `create_initial_state(...) -> GraphState`; `evaluate_customer(state: GraphState) -> dict[str, object]`; `route_action(state: GraphState) -> str`.

- [ ] **Step 1: Viết test RED cho required state fields và reasoning**

```python
# tests/test_graph_logic.py
from graph import GraphState, create_initial_state, evaluate_customer


def test_graph_state_declares_required_lab_fields():
    required = {"customer_id", "proposed_action", "confidence_score", "reasoning", "human_decision"}
    assert required <= GraphState.__required_keys__


def test_high_value_high_churn_customer_gets_credit_limit_proposal():
    state = create_initial_state("CUST001", 30_000_000, 0.80)
    result = evaluate_customer(state)
    assert result["proposed_action"] == "increase_credit_limit"
    assert 0.0 <= result["confidence_score"] <= 1.0
    assert result["reasoning"]


def test_medium_churn_customer_gets_low_confidence_email():
    result = evaluate_customer(create_initial_state("CUST002", 10_000_000, 0.60))
    assert result["proposed_action"] == "send_email"
    assert result["confidence_score"] == 0.82


def test_low_churn_customer_gets_high_confidence_email():
    result = evaluate_customer(create_initial_state("CUST003", 10_000_000, 0.20))
    assert result["proposed_action"] == "send_email"
    assert result["confidence_score"] == 0.90
```

- [ ] **Step 2: Chạy reasoning tests để xác nhận RED**

Run: `python -m pytest tests/test_graph_logic.py -v`

Expected: FAIL vì `graph.py` chưa tồn tại.

- [ ] **Step 3: Implement GraphState và deterministic reasoning**

`GraphState` khai báo năm field bắt buộc cùng `total_operating_income`, `churn_probability`, `reviewer_id`, `execution_status`. `create_initial_state` strip customer ID, validate TOI không âm và probability trong `[0, 1]`, rồi khởi tạo đầy đủ state. `evaluate_customer` dùng đúng bảng ba nhánh trong design và trả partial state ba field.

- [ ] **Step 4: Chạy reasoning tests để xác nhận GREEN**

Run: `python -m pytest tests/test_graph_logic.py -v`

Expected: 4 tests PASS.

- [ ] **Step 5: Viết test RED cho routing precedence**

```python
from graph import route_action


def routing_state(action, confidence):
    state = create_initial_state("CUST", 1_000_000, 0.2)
    state.update(proposed_action=action, confidence_score=confidence, reasoning="test")
    return state


def test_hard_policy_overrides_high_confidence():
    assert route_action(routing_state("increase_credit_limit", 0.99)) == "execute_high_risk_action"


def test_low_risk_high_confidence_auto_executes():
    assert route_action(routing_state("send_email", 0.90)) == "execute_low_risk_action"


def test_low_confidence_escalates_even_for_email():
    assert route_action(routing_state("send_email", 0.82)) == "execute_high_risk_action"
```

- [ ] **Step 6: Chạy routing tests để xác nhận RED**

Run: `python -m pytest tests/test_graph_logic.py -k "policy or auto or escalates" -v`

Expected: FAIL vì `route_action` chưa được định nghĩa.

- [ ] **Step 7: Implement routing tối thiểu**

```python
AUTO_EXECUTE_THRESHOLD = 0.85
HIGH_RISK_ACTION = "increase_credit_limit"


def route_action(state: GraphState) -> str:
    if state["proposed_action"] == HIGH_RISK_ACTION:
        return "execute_high_risk_action"
    if state["confidence_score"] >= AUTO_EXECUTE_THRESHOLD:
        return "execute_low_risk_action"
    return "execute_high_risk_action"
```

- [ ] **Step 8: Chạy toàn bộ Task 2 tests để xác nhận GREEN**

Run: `python -m pytest tests/test_graph_logic.py -v`

Expected: toàn bộ tests PASS.

- [ ] **Step 9: Commit Task 2**

```bash
git add graph.py tests/test_graph_logic.py
git commit -m "feat: add churn reasoning and policy routing"
```

---

### Task 3: Execution nodes, MemorySaver, interrupt và resume

**Files:**
- Modify: `graph.py`
- Create: `tests/test_hitl_workflow.py`

**Interfaces:**
- Consumes: mọi interface Task 1 và Task 2.
- Produces: `execute_low_risk_action(state, audit_path) -> dict[str, str]`; `execute_high_risk_action(state, audit_path) -> dict[str, str]`; `build_graph(audit_path=Path("audit_log.json"), checkpointer=None)`.

- [ ] **Step 1: Viết test RED cho auto-execute và interrupt state**

```python
# tests/test_hitl_workflow.py
from audit import read_audit_log
from graph import build_graph, create_initial_state


def config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def test_low_risk_action_auto_executes_and_is_audited(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    cfg = config("auto")
    result = workflow.invoke(create_initial_state("CUST-A", 1_000_000, 0.20), cfg)
    assert result["execution_status"] == "executed:send_email"
    assert workflow.get_state(cfg).next == ()
    assert read_audit_log(audit_path)[0]["decision"] == "auto_execute"


def test_high_risk_interrupts_before_execution_and_keeps_state(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    cfg = config("pending")
    workflow.invoke(create_initial_state("CUST-H", 30_000_000, 0.80), cfg)
    snapshot = workflow.get_state(cfg)
    assert snapshot.next == ("execute_high_risk_action",)
    assert snapshot.values["customer_id"] == "CUST-H"
    assert snapshot.values["proposed_action"] == "increase_credit_limit"
    assert read_audit_log(audit_path) == []
```

- [ ] **Step 2: Chạy workflow tests để xác nhận RED**

Run: `python -m pytest tests/test_hitl_workflow.py -v`

Expected: FAIL vì execution nodes và `build_graph` chưa tồn tại.

- [ ] **Step 3: Implement execution nodes và compiled graph**

Node low-risk tạo `AuditEntry` với reviewer `system`, decision `auto_execute`, append audit và trả `{"execution_status": f"executed:{action}"}`. Node high-risk chỉ chấp nhận `approve`, `reject`, `edit`; reject trả `rejected:{action}`, hai decision còn lại trả `executed:{action}`; cả ba append đúng reviewer/decision/action.

`build_graph` tạo `StateGraph(GraphState)`, entry point `evaluate_customer`, conditional edges tới hai execution node, edge từ mỗi execution node tới `END`, rồi compile bằng:

```python
memory = checkpointer if checkpointer is not None else MemorySaver()
return builder.compile(
    checkpointer=memory,
    interrupt_before=["execute_high_risk_action"],
)
```

Execution node được wrap bằng closure để nhận `audit_path` mà không đưa path vào customer state.

- [ ] **Step 4: Chạy workflow tests để xác nhận GREEN**

Run: `python -m pytest tests/test_hitl_workflow.py -v`

Expected: 2 tests PASS.

- [ ] **Step 5: Viết test RED cho Approve, Reject và Edit**

```python
import pytest


@pytest.mark.parametrize(
    ("decision", "expected_prefix"),
    [("approve", "executed:"), ("reject", "rejected:")],
)
def test_resume_applies_human_decision_and_audits(tmp_path, decision, expected_prefix):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    cfg = config(decision)
    workflow.invoke(create_initial_state("CUST-H", 30_000_000, 0.80), cfg)
    workflow.update_state(cfg, {"human_decision": decision, "reviewer_id": "operator_01"})
    result = workflow.invoke(None, cfg)
    assert result["execution_status"].startswith(expected_prefix)
    assert read_audit_log(audit_path)[0]["decision"] == decision


def test_edit_executes_and_audits_reviewer_action(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    cfg = config("edit")
    workflow.invoke(create_initial_state("CUST-H", 30_000_000, 0.80), cfg)
    workflow.update_state(cfg, {
        "human_decision": "edit",
        "reviewer_id": "operator_01",
        "proposed_action": "send_retention_offer",
    })
    result = workflow.invoke(None, cfg)
    assert result["execution_status"] == "executed:send_retention_offer"
    assert read_audit_log(audit_path)[0]["action"] == "send_retention_offer"
```

- [ ] **Step 6: Chạy resume tests để xác nhận RED**

Run: `python -m pytest tests/test_hitl_workflow.py -k "resume or edit" -v`

Expected: FAIL cho đến khi high-risk node đọc và áp dụng state đã update.

- [ ] **Step 7: Hoàn thiện high-risk resume behavior**

Validate `reviewer_id` không rỗng, normalize decision về lowercase, không thay action trong node, và tạo đúng một audit entry sau quyết định. Decision khác ba giá trị cho phép raise `ValueError("Human decision must be approve, reject, or edit")`.

- [ ] **Step 8: Chạy toàn bộ workflow suite để xác nhận GREEN**

Run: `python -m pytest tests/test_hitl_workflow.py -v`

Expected: toàn bộ tests PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add graph.py tests/test_hitl_workflow.py
git commit -m "feat: add interruptible HITL workflow"
```

---

### Task 4: Streamlit approval interface và CLI demo

**Files:**
- Create: `app.py`
- Create: `demo.py`
- Create: `tests/test_app.py`
- Create: `tests/test_demo.py`

**Interfaces:**
- Consumes: `build_graph`, `create_initial_state`, `read_audit_log`.
- Produces: Streamlit app với session keys `workflow`, `thread_config`, `last_state`; `demo.run_demo() -> dict[str, object]`.

- [ ] **Step 1: Viết test RED cho CLI demo**

```python
# tests/test_demo.py
from demo import run_demo


def test_cli_demo_completes_low_risk_workflow(tmp_path):
    result = run_demo(audit_path=tmp_path / "audit.json")
    assert result["customer_id"] == "DEMO-CUST-001"
    assert result["execution_status"] == "executed:send_email"
```

- [ ] **Step 2: Chạy demo test để xác nhận RED**

Run: `python -m pytest tests/test_demo.py -v`

Expected: FAIL vì `demo.py` chưa tồn tại.

- [ ] **Step 3: Implement CLI demo**

`run_demo` tạo graph, config với UUID, invoke customer mẫu churn `0.20`, trả final state. `main` in customer ID, action, confidence, reasoning và execution status dưới dạng text; khối `if __name__ == "__main__": main()` cho phép `python demo.py`.

- [ ] **Step 4: Chạy demo test để xác nhận GREEN**

Run: `python -m pytest tests/test_demo.py -v`

Expected: PASS.

- [ ] **Step 5: Viết Streamlit smoke test RED**

```python
# tests/test_app.py
from streamlit.testing.v1 import AppTest


def test_app_renders_customer_form():
    app = AppTest.from_file("app.py").run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "Churn Risk Human-in-the-Loop"
    assert app.text_input(key="customer_id")
    assert app.text_input(key="reviewer_id")
    assert app.button(key="evaluate_customer")
```

- [ ] **Step 6: Chạy UI smoke test để xác nhận RED**

Run: `python -m pytest tests/test_app.py -v`

Expected: FAIL vì `app.py` chưa tồn tại.

- [ ] **Step 7: Implement Streamlit UI**

`app.py` đặt page config và title; khởi tạo graph đúng một lần trong `st.session_state`; render input có key ổn định; Evaluate tạo UUID/config mới và invoke initial state. Khi snapshot pending, hiển thị action card, ba button/key `approve`, `reject`, `edit`, cùng text input `edited_action`. Mỗi decision update state với cùng config, gọi `invoke(None, config)`, lưu final state và rerun. Cuối trang đọc `audit_log.json` và render dataframe; audit lỗi hiển thị bằng `st.error` mà không ghi đè file.

- [ ] **Step 8: Chạy UI test để xác nhận GREEN**

Run: `python -m pytest tests/test_app.py -v`

Expected: PASS và `app.exception` rỗng.

- [ ] **Step 9: Chạy toàn bộ test suite**

Run: `python -m pytest -v`

Expected: toàn bộ tests PASS.

- [ ] **Step 10: Commit Task 4**

```bash
git add app.py demo.py tests/test_app.py tests/test_demo.py
git commit -m "feat: add Streamlit review interface"
```

---

### Task 5: README, repository hygiene và final verification

**Files:**
- Modify: `README.md`
- Create: `.gitignore`
- Modify: `docs/lab27-requirements.md`
- Modify: `docs/superpowers/specs/2026-08-29-hitl-churn-risk-design.md`

**Interfaces:**
- Consumes: Các lệnh và hành vi đã được chứng minh trong Task 1–4.
- Produces: Repository sẵn sàng nộp với hướng dẫn tái lập và không chứa credential.

- [ ] **Step 1: Viết README theo checklist nộp bài**

README phải có các section và lệnh cụ thể:

```markdown
## Cài đặt
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

## Chạy workflow
python demo.py

## Chạy Streamlit
streamlit run app.py

## Chạy kiểm thử
pip install -r requirements-dev.txt
python -m pytest -v
```

README giải thích threshold `0.85`, policy `increase_credit_limit` luôn review, luồng Approve/Reject/Edit, checkpoint theo `thread_id`, và audit tại `audit_log.json`. Ba Reflection Questions dùng nội dung đã chốt trong design spec.

- [ ] **Step 2: Thêm repository hygiene**

`.gitignore` phải chứa:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.streamlit/
.venv/
venv/
.env
.env.*
*.pem
*.key
coverage.xml
.coverage
htmlcov/
```

Không tạo `.env` vì ứng dụng không cần secret.

- [ ] **Step 3: Chạy verification đầy đủ**

Run lần lượt:

```powershell
python --version
python -m pytest -v
python demo.py
python -m compileall app.py audit.py demo.py graph.py models.py tests
git diff --check
git status --short
```

Expected: Python >= 3.10; tất cả tests PASS; demo kết thúc với `executed:send_email`; compileall exit 0; diff check không có lỗi whitespace; status chỉ có các file dự kiến.

- [ ] **Step 4: Quét credential trước khi commit**

Run:

```powershell
rg -n -i "(api[_-]?key|access[_-]?token|password|private[_-]?key)\s*[:=]\s*['\"][^'\"]+" -g "!docs/**" -g "!.git/**" .
git ls-files | rg "(^|/)(\.env($|\.)|.*\.(pem|key)$)"
```

Expected: không có credential value và không track file secret/private key.

- [ ] **Step 5: Commit Task 5**

```bash
git add README.md .gitignore docs/lab27-requirements.md docs/superpowers/specs/2026-08-29-hitl-churn-risk-design.md
git commit -m "docs: add Lab 27 runbook and submission guide"
```

- [ ] **Step 6: Final evidence check**

Run: `git status --short --branch; git log --oneline --decorate -6`

Expected: working tree sạch; local `main` ahead of `origin/main` với các commit Lab 27. Không push nếu chưa có lệnh riêng của người dùng.
