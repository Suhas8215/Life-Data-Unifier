"""Commitment extraction logic."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from fastapi import APIRouter, Query

from app.db import get_recent_gmail_messages, upsert_obligations
from app.timeparse import parse_time_window

router = APIRouter(prefix="/debug/extractor", tags=["extractor-debug"])

_COMMITMENT_PATTERN = re.compile(
    r"\b(i(?:'ll| will| can)|let me)\s+([^.!?\n]{3,220})",
    flags=re.IGNORECASE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_action(fragment: str) -> str:
    action = fragment.strip(" \t\r\n,;:-")
    action = re.sub(r"\s+", " ", action)
    return action[:180]


def _extract_from_message(message: dict[str, Any], max_per_message: int = 3) -> list[dict[str, Any]]:
    text = f"{message.get('subject', '')}. {message.get('snippet', '')}".strip()
    if not text:
        return []

    obligations: list[dict[str, Any]] = []
    for match in _COMMITMENT_PATTERN.finditer(text):
        evidence = match.group(0).strip()
        action = _normalize_action(match.group(2))
        if not action:
            continue
        parsed_time = parse_time_window(f"{evidence}. {action}")

        source_id = str(message.get("id", ""))
        digest_input = f"gmail|{source_id}|{evidence.lower()}".encode("utf-8")
        obligation_id = hashlib.sha1(digest_input).hexdigest()[:24]
        obligations.append(
            {
                "id": obligation_id,
                "source": "gmail",
                "source_id": source_id,
                "created_at": message.get("date") or _now_iso(),
                "text_evidence": evidence,
                "action": action,
                "counterparty": None,
                "time_window_start": parsed_time["start"] if parsed_time else None,
                "time_window_end": parsed_time["end"] if parsed_time else None,
                "confidence": 0.7,
                "status": "pending",
            }
        )
        if len(obligations) >= max_per_message:
            break
    return obligations


def extract_gmail_obligations(message_limit: int = 100) -> list[dict[str, Any]]:
    """Extract v0 obligations from recently stored Gmail SENT messages."""
    messages = get_recent_gmail_messages(limit=message_limit)
    obligations: list[dict[str, Any]] = []
    for msg in messages:
        obligations.extend(_extract_from_message(msg))
    return obligations


@router.get("/gmail")
def debug_extract_gmail(
    message_limit: int = Query(default=100, ge=1, le=500),
    persist: bool = Query(default=True),
) -> dict[str, Any]:
    """Run rule-based extraction against locally stored Gmail records."""
    messages = get_recent_gmail_messages(limit=message_limit)
    obligations: list[dict[str, Any]] = []
    for msg in messages:
        obligations.extend(_extract_from_message(msg))

    upserted = upsert_obligations(obligations) if persist else 0
    return {
        "messages_scanned": len(messages),
        "obligations_found": len(obligations),
        "persisted": persist,
        "upserted": upserted,
        "items": obligations,
    }
