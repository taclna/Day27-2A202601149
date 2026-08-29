"""Pydantic schemas used by the HITL churn-risk workflow."""

from pydantic import BaseModel, ConfigDict, Field


class AuditEntry(BaseModel):
    """One immutable-in-practice record in the local audit trail."""

    model_config = ConfigDict(str_strip_whitespace=True)

    timestamp: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reviewer_id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
