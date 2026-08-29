import pytest

from audit import read_audit_log
from graph import build_graph, create_initial_state


def config(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def test_low_risk_action_auto_executes_and_is_audited(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    thread_config = config("auto")

    result = workflow.invoke(
        create_initial_state("CUST-A", 1_000_000, 0.20),
        thread_config,
    )

    assert result["execution_status"] == "executed:send_email"
    assert workflow.get_state(thread_config).next == ()
    assert read_audit_log(audit_path)[0]["decision"] == "auto_execute"


def test_high_risk_interrupts_before_execution_and_keeps_state(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    thread_config = config("pending")

    workflow.invoke(
        create_initial_state("CUST-H", 30_000_000, 0.80),
        thread_config,
    )
    snapshot = workflow.get_state(thread_config)

    assert snapshot.next == ("execute_high_risk_action",)
    assert snapshot.values["customer_id"] == "CUST-H"
    assert snapshot.values["proposed_action"] == "increase_credit_limit"
    assert read_audit_log(audit_path) == []


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ("approve", "executed:increase_credit_limit"),
        ("reject", "rejected:increase_credit_limit"),
    ],
)
def test_resume_applies_human_decision_and_audits(
    tmp_path, decision, expected_status
):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    thread_config = config(decision)
    workflow.invoke(
        create_initial_state("CUST-H", 30_000_000, 0.80),
        thread_config,
    )

    workflow.update_state(
        thread_config,
        {"human_decision": decision, "reviewer_id": "operator_01"},
    )
    result = workflow.invoke(None, thread_config)

    assert result["execution_status"] == expected_status
    assert read_audit_log(audit_path)[0]["decision"] == decision


def test_edit_executes_and_audits_reviewer_action(tmp_path):
    audit_path = tmp_path / "audit.json"
    workflow = build_graph(audit_path=audit_path)
    thread_config = config("edit")
    workflow.invoke(
        create_initial_state("CUST-H", 30_000_000, 0.80),
        thread_config,
    )

    workflow.update_state(
        thread_config,
        {
            "human_decision": "edit",
            "reviewer_id": "operator_01",
            "edited_action": "send_retention_offer",
        },
    )
    result = workflow.invoke(None, thread_config)

    assert result["execution_status"] == "executed:send_retention_offer"
    assert result["proposed_action"] == "send_retention_offer"
    assert read_audit_log(audit_path)[0]["action"] == "send_retention_offer"
    assert read_audit_log(audit_path)[0]["decision"] == "edit"


def test_high_risk_node_rejects_missing_human_decision(tmp_path):
    workflow = build_graph(audit_path=tmp_path / "audit.json")
    thread_config = config("invalid")
    workflow.invoke(
        create_initial_state("CUST-H", 30_000_000, 0.80),
        thread_config,
    )
    workflow.update_state(
        thread_config,
        {"human_decision": "invalid", "reviewer_id": "operator_01"},
    )

    with pytest.raises(
        ValueError,
        match="Human decision must be approve, reject, or edit",
    ):
        workflow.invoke(None, thread_config)


def test_edit_rejects_an_empty_reviewer_action(tmp_path):
    workflow = build_graph(audit_path=tmp_path / "audit.json")
    thread_config = config("empty-edit")
    workflow.invoke(
        create_initial_state("CUST-H", 30_000_000, 0.80),
        thread_config,
    )
    workflow.update_state(
        thread_config,
        {
            "human_decision": "edit",
            "reviewer_id": "operator_01",
            "edited_action": "   ",
        },
    )

    with pytest.raises(ValueError, match="Edited action must not be empty"):
        workflow.invoke(None, thread_config)
