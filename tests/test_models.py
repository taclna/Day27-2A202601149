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
