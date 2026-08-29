import pytest

from graph import GraphState, create_initial_state, evaluate_customer, route_action


def test_graph_state_declares_required_lab_fields():
    required = {
        "customer_id",
        "proposed_action",
        "confidence_score",
        "reasoning",
        "human_decision",
    }

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


@pytest.mark.parametrize(
    ("customer_id", "income", "churn_probability"),
    [
        ("", 1_000_000, 0.2),
        ("CUST", -1, 0.2),
        ("CUST", 1_000_000, -0.01),
        ("CUST", 1_000_000, 1.01),
    ],
)
def test_initial_state_rejects_invalid_customer_data(
    customer_id, income, churn_probability
):
    with pytest.raises(ValueError):
        create_initial_state(customer_id, income, churn_probability)


def routing_state(action, confidence):
    state = create_initial_state("CUST", 1_000_000, 0.2)
    state.update(
        proposed_action=action,
        confidence_score=confidence,
        reasoning="Test routing",
    )
    return state


def test_hard_policy_overrides_high_confidence():
    assert (
        route_action(routing_state("increase_credit_limit", 0.99))
        == "execute_high_risk_action"
    )


def test_low_risk_high_confidence_auto_executes():
    assert (
        route_action(routing_state("send_email", 0.90))
        == "execute_low_risk_action"
    )


def test_low_confidence_escalates_even_for_email():
    assert (
        route_action(routing_state("send_email", 0.82))
        == "execute_high_risk_action"
    )
