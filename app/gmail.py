"""Gmail data access utilities."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.db import upsert_gmail_inbox_messages, upsert_gmail_messages
from app.google_auth import GOOGLE_SCOPES

router = APIRouter(prefix="/debug/gmail", tags=["gmail-debug"])


def _load_credentials() -> Credentials:
    settings = get_settings()
    token_path = Path(settings.google_token_path).expanduser()
    if not token_path.exists():
        raise HTTPException(
            status_code=401,
            detail="No stored Google token found. Connect Google first at /auth/login.",
        )

    credentials = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleAuthRequest())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise HTTPException(
            status_code=401,
            detail="Stored Google token is invalid. Reconnect via /auth/login.",
        )
    return credentials


def _parse_internal_date(headers: list[dict[str, str]], fallback_ms: str | None) -> str | None:
    header_date = next((h["value"] for h in headers if h.get("name", "").lower() == "date"), None)
    if header_date:
        try:
            parsed = parsedate_to_datetime(header_date)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass

    if fallback_ms:
        try:
            timestamp = int(fallback_ms) / 1000.0
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except ValueError:
            return None
    return None


def fetch_recent_sent(days: int = 7, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch normalized messages from Gmail SENT label for a recent time window."""
    credentials = _load_credentials()
    query_since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"label:sent after:{query_since}"

    try:
        service = build("gmail", "v1", credentials=credentials)
        list_response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
        )
        messages = list_response.get("messages", [])
        results: list[dict[str, Any]] = []
        for item in messages:
            message_id = item.get("id")
            if not message_id:
                continue

            detail = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="metadata")
                .execute()
            )
            payload = detail.get("payload", {})
            headers = payload.get("headers", [])

            subject = next(
                (h["value"] for h in headers if h.get("name", "").lower() == "subject"),
                "",
            )
            results.append(
                {
                    "id": detail.get("id"),
                    "thread_id": detail.get("threadId"),
                    "date": _parse_internal_date(headers, detail.get("internalDate")),
                    "subject": subject,
                    "snippet": detail.get("snippet", ""),
                }
            )
        return results
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Gmail API error: {exc}") from exc


def _header_lookup(headers: list[dict[str, str]]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in headers}


def fetch_recent_inbox(days: int = 7, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch normalized messages from inbox-side mail for response analysis."""
    credentials = _load_credentials()
    query_since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"in:inbox -label:sent after:{query_since}"
    metadata_headers = [
        "Date",
        "From",
        "To",
        "Cc",
        "Subject",
        "In-Reply-To",
        "References",
        "List-Unsubscribe",
        "Auto-Submitted",
        "Precedence",
        "Reply-To",
    ]

    try:
        service = build("gmail", "v1", credentials=credentials)
        list_response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=limit)
            .execute()
        )
        messages = list_response.get("messages", [])
        results: list[dict[str, Any]] = []
        for item in messages:
            message_id = item.get("id")
            if not message_id:
                continue

            detail = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=metadata_headers,
                )
                .execute()
            )
            payload = detail.get("payload", {})
            headers = payload.get("headers", [])
            headers_map = _header_lookup(headers)
            key_headers = {
                "in-reply-to": headers_map.get("in-reply-to", ""),
                "references": headers_map.get("references", ""),
                "list-unsubscribe": headers_map.get("list-unsubscribe", ""),
                "auto-submitted": headers_map.get("auto-submitted", ""),
                "precedence": headers_map.get("precedence", ""),
                "reply-to": headers_map.get("reply-to", ""),
            }
            results.append(
                {
                    "id": detail.get("id"),
                    "thread_id": detail.get("threadId"),
                    "date": _parse_internal_date(headers, detail.get("internalDate")),
                    "from": headers_map.get("from", ""),
                    "to": headers_map.get("to", ""),
                    "cc": headers_map.get("cc", ""),
                    "subject": headers_map.get("subject", ""),
                    "snippet": detail.get("snippet", ""),
                    "label_ids": detail.get("labelIds", []),
                    "headers": key_headers,
                }
            )
        return results
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Gmail API error: {exc}") from exc


@router.get("/sent")
def debug_sent(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=25, ge=1, le=100),
    persist: bool = Query(default=True),
) -> dict[str, Any]:
    """Temporary debug endpoint to inspect fetched SENT messages."""
    items = fetch_recent_sent(days=days, limit=limit)
    upserted = upsert_gmail_messages(items) if persist else 0
    return {
        "query_days": days,
        "count": len(items),
        "persisted": persist,
        "upserted": upserted,
        "items": items,
    }


@router.get("/inbox")
def debug_inbox(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=25, ge=1, le=200),
    persist: bool = Query(default=True),
) -> dict[str, Any]:
    """Temporary debug endpoint to inspect fetched inbox-side messages."""
    items = fetch_recent_inbox(days=days, limit=limit)
    upserted = upsert_gmail_inbox_messages(items) if persist else 0
    return {
        "query_days": days,
        "count": len(items),
        "persisted": persist,
        "upserted": upserted,
        "items": items,
    }
