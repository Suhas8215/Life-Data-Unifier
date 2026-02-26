"""Google Calendar data access utilities."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.db import upsert_gcal_events
from app.google_auth import GOOGLE_SCOPES

router = APIRouter(prefix="/debug/gcal", tags=["gcal-debug"])


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


def _to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        # Google may return values ending with "Z".
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return value


def fetch_recent_events(
    lookback_days: int = 1,
    lookahead_days: int = 7,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch normalized events from yesterday through the coming week."""
    credentials = _load_credentials()
    now_utc = datetime.now(timezone.utc)
    time_min = (now_utc - timedelta(days=lookback_days)).isoformat()
    time_max = (now_utc + timedelta(days=lookahead_days)).isoformat()

    try:
        service = build("calendar", "v3", credentials=credentials)
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = response.get("items", [])
        results: list[dict[str, Any]] = []
        for event in events:
            attendees = [a.get("email", "") for a in event.get("attendees", []) if a.get("email")]
            start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            end_raw = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
            results.append(
                {
                    "id": event.get("id"),
                    "status": event.get("status"),
                    "summary": event.get("summary", ""),
                    "description": event.get("description", ""),
                    "start": _to_iso(start_raw),
                    "end": _to_iso(end_raw),
                    "attendees": attendees,
                    "html_link": event.get("htmlLink"),
                    "is_recurring": bool(event.get("recurringEventId") or event.get("recurrence")),
                }
            )
        return results
    except HttpError as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar API error: {exc}") from exc


@router.get("/events")
def debug_events(
    lookback_days: int = Query(default=1, ge=0, le=30),
    lookahead_days: int = Query(default=7, ge=1, le=60),
    limit: int = Query(default=25, ge=1, le=100),
    persist: bool = Query(default=True),
) -> dict[str, Any]:
    """Temporary debug endpoint to inspect fetched calendar events."""
    items = fetch_recent_events(
        lookback_days=lookback_days,
        lookahead_days=lookahead_days,
        limit=limit,
    )
    upserted = upsert_gcal_events(items) if persist else 0
    return {
        "lookback_days": lookback_days,
        "lookahead_days": lookahead_days,
        "count": len(items),
        "persisted": persist,
        "upserted": upserted,
        "items": items,
    }
