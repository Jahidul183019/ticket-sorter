"""Rule-based ticket classifier (no LLM, no API key)."""
from __future__ import annotations

import logging
import re
from typing import Iterable, List, Tuple

from models import (
    CaseType,
    Department,
    Severity,
    SortTicketRequest,
    SortTicketResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

# Words that must NEVER appear in the agent-facing summary.
FORBIDDEN_SUMMARY_TERMS = (
    "pin",
    "otp",
    "password",
    "card number",
    "card-number",
    "card_number",
    "cvv",
    "cvc",
)
_SUMMARY_REDACTED_PLACEHOLDER = "[REDACTED]"


def _sanitize_summary(summary: str) -> str:
    """Replace forbidden security tokens with a placeholder."""
    if not summary:
        return summary

    sanitized = summary
    for term in FORBIDDEN_SUMMARY_TERMS:
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        sanitized = pattern.sub(_SUMMARY_REDACTED_PLACEHOLDER, sanitized)

    if sanitized != summary:
        logger.warning(
            "agent_summary contained a forbidden security term; redacted before returning."
        )
    return sanitized


# ---------------------------------------------------------------------------
# Keyword rules — checked in priority order
# ---------------------------------------------------------------------------

# Each entry: (case_type, [keyword/phrases...])
# Phrases are matched as substrings against the lowercased message.
_PHISHING_KEYWORDS: Tuple[str, ...] = (
    "otp",
    "one time password",
    "one-time password",
    "pin",
    "share my pin",
    "give me your pin",
    "share your otp",
    "share the otp",
    "give your otp",
    "verify your account",
    "verify your bkash",
    "verify your nagad",
    "click the link",
    "click this link",
    "phishing",
    "fake website",
    "scam link",
    "scammer",
    "asked for my password",
    "asked for my pin",
    "asked for my otp",
    "asked for otp",
    "asked for pin",
    "asked me to send otp",
    "asked me to send pin",
    "send otp to",
    "send pin to",
    "share password",
    "share credentials",
    "share cvv",
    "share card number",
    "fraud call",
    "fraud sms",
    "someone is asking",
)

_WRONG_TRANSFER_KEYWORDS: Tuple[str, ...] = (
    "wrong number",
    "wrong account",
    "sent to wrong",
    "wrong recipient",
    "sent money to wrong",
    "transferred to wrong",
    "transferred wrong",
    "by mistake",
    "sent by mistake",
    "transferred by mistake",
    "wrongly transferred",
    "wrongly sent",
    "sent to the wrong person",
    "sent to the wrong number",
    "wrong transfer",
    "accidentally sent",
    "accidentally transferred",
    "mistakenly sent",
    "mistakenly transferred",
    "want my money back",
    "recover my money",
    "recover the money",
    "get my money back",
)

_PAYMENT_FAILED_KEYWORDS: Tuple[str, ...] = (
    "payment failed",
    "transaction failed",
    "transaction declined",
    "declined",
    "payment unsuccessful",
    "unsuccessful",
    "money deducted",
    "amount deducted",
    "deducted but not received",
    "deducted but",
    "did not receive",
    "didn't receive",
    "didnt receive",
    "not received",
    "money not received",
    "payment pending",
    "pending for a long",
    "stuck",
    "stuck transaction",
    "failed transaction",
    "payment not going through",
    "send money failed",
    "send money not working",
    "cash out failed",
    "cash-out failed",
    "add money failed",
    "top up failed",
    "top-up failed",
    "send money unsuccessful",
)

_REFUND_KEYWORDS: Tuple[str, ...] = (
    "refund",
    "refunded",
    "money back",
    "want my money back",
    "want a refund",
    "asking for refund",
    "request a refund",
    "request refund",
    "please refund",
    "please return",
    "return my money",
    "merchant did not",
    "merchant didn't",
    "merchant didnt",
    "service not provided",
    "service was not provided",
    "didn't get the service",
    "didnt get the service",
    "overcharged",
    "double charged",
    "charged twice",
    "wrong charge",
    "unauthorized charge",
    "unauthorised charge",
    "cancel transaction",
    "cancel the transaction",
    "reverse the transaction",
    "reverse transaction",
)


def _matches_any(text: str, keywords: Iterable[str]) -> bool:
    """True if any keyword appears as a substring of the lowercased text."""
    for kw in keywords:
        if kw in text:
            return True
    return False


def _detect_case_type(message_lc: str) -> Tuple[CaseType, float]:
    """Return (case_type, confidence) using priority-ordered keyword rules."""
    # Phishing first — it's the highest-stakes misroute if missed.
    if _matches_any(message_lc, _PHISHING_KEYWORDS):
        return CaseType.PHISHING, 0.9

    if _matches_any(message_lc, _WRONG_TRANSFER_KEYWORDS):
        return CaseType.WRONG_TRANSFER, 0.85

    if _matches_any(message_lc, _PAYMENT_FAILED_KEYWORDS):
        return CaseType.PAYMENT_FAILED, 0.85

    if _matches_any(message_lc, _REFUND_KEYWORDS):
        return CaseType.REFUND_REQUEST, 0.8

    return CaseType.OTHER, 0.5


# ---------------------------------------------------------------------------
# Spec-defined fixed mappings
# ---------------------------------------------------------------------------

def _severity_for(case_type: CaseType) -> Severity:
    """Per spec: severity is determined solely by case_type."""
    if case_type == CaseType.WRONG_TRANSFER:
        return Severity.HIGH
    if case_type == CaseType.PAYMENT_FAILED:
        return Severity.HIGH
    if case_type == CaseType.PHISHING:
        return Severity.CRITICAL
    if case_type == CaseType.REFUND_REQUEST:
        return Severity.LOW
    return Severity.LOW  # OTHER


def _department_for(case_type: CaseType) -> Department:
    """Per spec: department is determined solely by case_type."""
    if case_type == CaseType.WRONG_TRANSFER:
        return Department.DISPUTE_RESOLUTION
    if case_type == CaseType.PAYMENT_FAILED:
        return Department.PAYMENTS_OPS
    if case_type == CaseType.PHISHING:
        return Department.FRAUD_RISK
    if case_type == CaseType.REFUND_REQUEST:
        return Department.CUSTOMER_SUPPORT
    return Department.CUSTOMER_SUPPORT  # OTHER


def _human_review_required(case_type: CaseType, severity: Severity) -> bool:
    """Per spec: true iff severity is critical OR case_type is phishing."""
    return severity == Severity.CRITICAL or case_type == CaseType.PHISHING


# ---------------------------------------------------------------------------
# Summary templates (per case_type)
# ---------------------------------------------------------------------------

# Short, agent-facing sentences. Each template uses `{hint}` when we want to
# echo a tiny piece of the customer's wording (kept brief and never including
# any potentially sensitive tokens).
_SUMMARY_TEMPLATES = {
    CaseType.WRONG_TRANSFER: (
        "Customer reports sending money to the wrong number/account and "
        "is requesting recovery of the transferred amount."
    ),
    CaseType.PAYMENT_FAILED: (
        "Customer reports a failed payment or transaction; amount may have "
        "been deducted but the transfer did not complete."
    ),
    CaseType.PHISHING: (
        "Customer may have been targeted by a social-engineering or phishing "
        "attempt and shared sensitive account information. Treat as a fraud-risk "
        "case and follow account-safety procedures."
    ),
    CaseType.REFUND_REQUEST: (
        "Customer is requesting a refund for a charge, transaction, or service."
    ),
    CaseType.OTHER: (
        "Customer message did not match a known case pattern. Manual triage "
        "is required to determine the appropriate routing."
    ),
}


def _summary_for(case_type: CaseType, original_message: str) -> str:
    base = _SUMMARY_TEMPLATES[case_type]
    return base


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def classify_ticket(req: SortTicketRequest) -> SortTicketResponse:
    """Classify a ticket using pure keyword rules. Never raises on input."""
    message = req.message or ""
    message_lc = message.lower()

    case_type, confidence = _detect_case_type(message_lc)
    severity = _severity_for(case_type)
    department = _department_for(case_type)

    summary = _sanitize_summary(_summary_for(case_type, message))
    human_review = _human_review_required(case_type, severity)

    return SortTicketResponse(
        ticket_id=req.ticket_id,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=summary,
        human_review_required=human_review,
        confidence=confidence,
    )
