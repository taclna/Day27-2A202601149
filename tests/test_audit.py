from datetime import datetime

import pytest

from audit import append_audit_entry, read_audit_log, utc_timestamp
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
        "send_email",
        "increase_credit_limit",
    ]


def test_invalid_json_is_not_overwritten(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid audit log JSON"):
        append_audit_entry(make_entry(), path)

    assert path.read_text(encoding="utf-8") == "not-json"


def test_utc_timestamp_is_timezone_aware_iso_8601():
    parsed = datetime.fromisoformat(utc_timestamp())

    assert parsed.utcoffset() is not None
