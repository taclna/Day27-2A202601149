from pathlib import Path

from streamlit.testing.v1 import AppTest

from audit import read_audit_log


def test_app_renders_customer_form():
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(app_path).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Churn Risk Human-in-the-Loop"
    assert app.text_input(key="customer_id")
    assert app.text_input(key="reviewer_id")
    assert app.button(key="evaluate_customer")


def test_app_approves_pending_action_and_writes_isolated_audit(
    tmp_path, monkeypatch
):
    audit_path = tmp_path / "ui-audit.json"
    monkeypatch.setenv("HITL_AUDIT_PATH", str(audit_path))
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(app_path).run(timeout=10)

    app.text_input(key="customer_id").set_value("CUST-UI")
    app.number_input(key="total_operating_income").set_value(30_000_000.0)
    app.number_input(key="churn_probability").set_value(0.80)
    app.text_input(key="reviewer_id").set_value("operator_ui")
    app.button(key="evaluate_customer").click().run(timeout=10)

    assert app.button(key="approve")
    assert app.button(key="reject")
    assert app.button(key="edit")

    app.button(key="approve").click().run(timeout=10)

    assert any("executed:increase_credit_limit" in item.value for item in app.success)
    assert read_audit_log(audit_path)[0]["decision"] == "approve"
