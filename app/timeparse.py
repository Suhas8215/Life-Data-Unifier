"""Time phrase normalization helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(prefix="/debug/timeparse", tags=["timeparse-debug"])

_TODAY_RE = re.compile(r"\btoday\b", flags=re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\btomorrow\b", flags=re.IGNORECASE)
_THIS_WEEK_RE = re.compile(r"\bthis week\b", flags=re.IGNORECASE)
_NEXT_WEEK_RE = re.compile(r"\bnext week\b", flags=re.IGNORECASE)
_BY_FRIDAY_RE = re.compile(r"\bby friday\b", flags=re.IGNORECASE)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def _week_bounds(containing_day: datetime) -> tuple[datetime, datetime]:
    start = _start_of_day(containing_day - timedelta(days=containing_day.weekday()))
    end = _end_of_day(start + timedelta(days=6))
    return start, end


def _upcoming_weekday(day: datetime, weekday_index: int) -> datetime:
    delta = (weekday_index - day.weekday()) % 7
    return day + timedelta(days=delta)


def parse_time_window(text: str, now: datetime | None = None) -> dict[str, str] | None:
    """Parse approved MVP time phrases into an ISO datetime window."""
    if not text:
        return None

    local_now = now.astimezone() if now else _local_now()
    today = _start_of_day(local_now)

    if _TODAY_RE.search(text):
        start, end = _start_of_day(today), _end_of_day(today)
        return {"matched_phrase": "today", "start": start.isoformat(), "end": end.isoformat()}

    if _TOMORROW_RE.search(text):
        target = today + timedelta(days=1)
        start, end = _start_of_day(target), _end_of_day(target)
        return {"matched_phrase": "tomorrow", "start": start.isoformat(), "end": end.isoformat()}

    if _THIS_WEEK_RE.search(text):
        start, end = _week_bounds(local_now)
        return {"matched_phrase": "this week", "start": start.isoformat(), "end": end.isoformat()}

    if _NEXT_WEEK_RE.search(text):
        next_week_anchor = local_now + timedelta(days=7)
        start, end = _week_bounds(next_week_anchor)
        return {"matched_phrase": "next week", "start": start.isoformat(), "end": end.isoformat()}

    if _BY_FRIDAY_RE.search(text):
        friday = _upcoming_weekday(local_now, weekday_index=4)
        start, end = _start_of_day(today), _end_of_day(friday)
        return {"matched_phrase": "by friday", "start": start.isoformat(), "end": end.isoformat()}

    return None


@router.get("/parse")
def debug_parse(text: str = Query(..., min_length=1, max_length=500)) -> dict[str, Any]:
    """Debug endpoint for manual phrase normalization checks."""
    parsed = parse_time_window(text)
    return {"text": text, "parsed": parsed}
