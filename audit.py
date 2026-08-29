"""Local JSON audit-trail persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from models import AuditEntry


def utc_timestamp() -> str:
    """Return a timezone-aware UTC timestamp in ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat()


def read_audit_log(path: str | Path) -> list[dict[str, object]]:
    """Read an audit JSON array without silently repairing corrupt data."""

    audit_path = Path(path)
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        return []

    try:
        data = json.loads(audit_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid audit log JSON: {audit_path}") from exc

    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(f"Invalid audit log JSON: {audit_path} must contain an array of objects")

    return data


def append_audit_entry(entry: AuditEntry, path: str | Path) -> None:
    """Atomically append an entry while preserving the existing JSON history."""

    audit_path = Path(path)
    entries = read_audit_log(audit_path)
    entries.append(entry.model_dump(mode="json"))

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = audit_path.with_suffix(f"{audit_path.suffix}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(audit_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
