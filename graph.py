"""Core state, reasoning, and routing for the churn-risk workflow."""

from __future__ import annotations

from typing import TypedDict


AUTO_EXECUTE_THRESHOLD = 0.85
HIGH_RISK_ACTION = "increase_credit_limit"
LOW_RISK_ACTION = "send_email"


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
