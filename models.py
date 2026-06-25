"""Pydantic models for the ticket-sorter API."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (match the spec's allowed values exactly)
# ---------------------------------------------------------------------------

class CaseType(str, Enum):
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    PHISHING = "phishing_or_social_engineering"
    OTHER = "other"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Department(str, Enum):
    CUSTOMER_SUPPORT = "customer_support"
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENTS_OPS = "payments_ops"
    FRAUD_RISK = "fraud_risk"


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SortTicketRequest(BaseModel):
    """Payload accepted by POST /sort-ticket."""

    ticket_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique ticket identifier (e.g. 'T-001').",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Raw customer message text.",
    )

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank or whitespace only")
        return v


class SortTicketResponse(BaseModel):
    """Payload returned by POST /sort-ticket."""

    ticket_id: str
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str = Field(
        ...,
        description=(
            "1-2 sentence summary for a human support agent. "
            "Must never contain the words PIN, OTP, password, or 'card number'."
        ),
    )
    human_review_required: bool
    confidence: float = Field(..., ge=0.0, le=1.0)


class HealthResponse(BaseModel):
    """Payload returned by GET /health."""

    status: Literal["ok"] = "ok"
    service: Literal["ticket-sorter"] = "ticket-sorter"
    version: Literal["0.1.0"] = "0.1.0"
