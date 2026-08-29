"""Core state, reasoning, and routing for the churn-risk workflow."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from audit import append_audit_entry, utc_timestamp
from models import AuditEntry


AUTO_EXECUTE_THRESHOLD = 0.85
HIGH_RISK_ACTION = "increase_credit_limit"
LOW_RISK_ACTION = "send_email"
AGENT_ID = "churn-risk-agent"
DEFAULT_AUDIT_PATH = Path("audit_log.json")


class GraphState(TypedDict):
    """Persistent state shared by every node in the workflow."""

    customer_id: str
    proposed_action: str
    confidence_score: float
    reasoning: str
    human_decision: str | None
    total_operating_income: float
    churn_probability: float
    reviewer_id: str
    edited_action: str
    execution_status: str


def _validate_customer_data(
    customer_id: str,
    total_operating_income: float,
    churn_probability: float,
) -> None:
    if not customer_id.strip():
        raise ValueError("Customer ID must not be empty")
    if total_operating_income < 0:
        raise ValueError("Total operating income must not be negative")
    if not 0.0 <= churn_probability <= 1.0:
        raise ValueError("Churn probability must be between 0.0 and 1.0")


def create_initial_state(
    customer_id: str,
    total_operating_income: float,
    churn_probability: float,
) -> GraphState:
    """Validate customer input and create a complete initial graph state."""

    _validate_customer_data(customer_id, total_operating_income, churn_probability)
    return GraphState(
        customer_id=customer_id.strip(),
        proposed_action="",
        confidence_score=0.0,
        reasoning="",
        human_decision=None,
        total_operating_income=float(total_operating_income),
        churn_probability=float(churn_probability),
        reviewer_id="",
        edited_action="",
        execution_status="pending_evaluation",
    )


def evaluate_customer(state: GraphState) -> dict[str, object]:
    """Return a deterministic retention proposal for a customer."""

    customer_id = state["customer_id"]
    income = state["total_operating_income"]
    churn_probability = state["churn_probability"]
    _validate_customer_data(customer_id, income, churn_probability)

    if churn_probability >= 0.75 and income >= 20_000_000:
        return {
            "proposed_action": HIGH_RISK_ACTION,
            "confidence_score": 0.96,
            "reasoning": (
                "Customer has high churn probability and strong operating income. "
                "A credit-limit increase may improve retention, but financial policy "
                "requires human review."
            ),
        }

    if churn_probability >= 0.50:
        return {
            "proposed_action": LOW_RISK_ACTION,
            "confidence_score": 0.82,
            "reasoning": (
                "Customer shows meaningful churn risk, but evidence is below the "
                "auto-execution threshold, so a reviewer should confirm the email."
            ),
        }

    return {
        "proposed_action": LOW_RISK_ACTION,
        "confidence_score": 0.90,
        "reasoning": (
            "Customer has low churn probability and only a low-risk retention email "
            "is recommended."
        ),
    }


def route_action(state: GraphState) -> str:
    """Apply hard policy before confidence-based routing."""

    if state["proposed_action"] == HIGH_RISK_ACTION:
        return "execute_high_risk_action"
    if state["confidence_score"] >= AUTO_EXECUTE_THRESHOLD:
        return "execute_low_risk_action"
    return "execute_high_risk_action"


def _write_audit(
    state: GraphState,
    reviewer_id: str,
    decision: str,
    audit_path: str | Path,
    action: str | None = None,
) -> None:
    entry = AuditEntry(
        timestamp=utc_timestamp(),
        agent_id=AGENT_ID,
        action=action or state["proposed_action"],
        confidence=state["confidence_score"],
        reviewer_id=reviewer_id,
        decision=decision,
    )
    append_audit_entry(entry, audit_path)


def execute_low_risk_action(
    state: GraphState,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
) -> dict[str, str]:
    """Simulate a safe action and record the automatic decision."""

    _write_audit(state, "system", "auto_execute", audit_path)
    return {"execution_status": f"executed:{state['proposed_action']}"}


def execute_high_risk_action(
    state: GraphState,
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
) -> dict[str, str]:
    """Apply a reviewed decision after the graph resumes from its interrupt."""

    decision = (state["human_decision"] or "").strip().lower()
    if decision not in {"approve", "reject", "edit"}:
        raise ValueError("Human decision must be approve, reject, or edit")

    reviewer_id = state["reviewer_id"].strip()
    if not reviewer_id:
        raise ValueError("Reviewer ID must not be empty")

    action = state["proposed_action"]
    updates: dict[str, str] = {}
    if decision == "edit":
        action = state["edited_action"].strip()
        if not action:
            raise ValueError("Edited action must not be empty")
        updates["proposed_action"] = action

    _write_audit(state, reviewer_id, decision, audit_path, action=action)
    status_prefix = "rejected" if decision == "reject" else "executed"
    updates["execution_status"] = f"{status_prefix}:{action}"
    return updates


def build_graph(
    audit_path: str | Path = DEFAULT_AUDIT_PATH,
    checkpointer=None,
):
    """Build the persistent LangGraph workflow with a high-risk breakpoint."""

    builder = StateGraph(GraphState)
    builder.add_node("evaluate_customer", evaluate_customer)

    def low_risk_node(state: GraphState) -> dict[str, str]:
        return execute_low_risk_action(state, audit_path)

    def high_risk_node(state: GraphState) -> dict[str, str]:
        return execute_high_risk_action(state, audit_path)

    builder.add_node("execute_low_risk_action", low_risk_node)
    builder.add_node("execute_high_risk_action", high_risk_node)
    builder.set_entry_point("evaluate_customer")
    builder.add_conditional_edges(
        "evaluate_customer",
        route_action,
        {
            "execute_low_risk_action": "execute_low_risk_action",
            "execute_high_risk_action": "execute_high_risk_action",
        },
    )
    builder.add_edge("execute_low_risk_action", END)
    builder.add_edge("execute_high_risk_action", END)

    memory = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(
        checkpointer=memory,
        interrupt_before=["execute_high_risk_action"],
    )
