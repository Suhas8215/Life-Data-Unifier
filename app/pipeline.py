"""Orchestrated scan pipeline for MVP demo flow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.db import upsert_gcal_events, upsert_gmail_messages, upsert_obligations
from app.extractor import extract_gmail_obligations
from app.gcal import fetch_recent_events
from app.gmail import fetch_recent_sent

router = APIRouter(prefix="/debug/pipeline", tags=["pipeline-debug"])


def run_scan_pipeline(
    gmail_days: int = 7,
    gcal_lookback_days: int = 1,
    gcal_lookahead_days: int = 7,
    gmail_limit: int = 100,
    gcal_limit: int = 100,
    message_limit_for_extraction: int = 200,
) -> dict[str, Any]:
    """Fetch source data, persist it, then run and persist extraction."""
    gmail_items = fetch_recent_sent(days=gmail_days, limit=gmail_limit)
    gmail_upserted = upsert_gmail_messages(gmail_items)

    gcal_items = fetch_recent_events(
        lookback_days=gcal_lookback_days,
        lookahead_days=gcal_lookahead_days,
        limit=gcal_limit,
    )
    gcal_upserted = upsert_gcal_events(gcal_items)

    obligations = extract_gmail_obligations(message_limit=message_limit_for_extraction)
    obligations_upserted = upsert_obligations(obligations)

    return {
        "gmail_days": gmail_days,
        "gcal_lookback_days": gcal_lookback_days,
        "gcal_lookahead_days": gcal_lookahead_days,
        "gmail_fetched": len(gmail_items),
        "gmail_upserted": gmail_upserted,
        "gcal_fetched": len(gcal_items),
        "gcal_upserted": gcal_upserted,
        "obligations_found": len(obligations),
        "obligations_upserted": obligations_upserted,
    }


@router.get("/scan")
def debug_scan(
    gmail_days: int = Query(default=7, ge=1, le=30),
    gcal_lookback_days: int = Query(default=1, ge=0, le=30),
    gcal_lookahead_days: int = Query(default=7, ge=1, le=60),
    gmail_limit: int = Query(default=100, ge=1, le=500),
    gcal_limit: int = Query(default=100, ge=1, le=500),
    message_limit_for_extraction: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """Run complete scan pipeline and return summary counts."""
    summary = run_scan_pipeline(
        gmail_days=gmail_days,
        gcal_lookback_days=gcal_lookback_days,
        gcal_lookahead_days=gcal_lookahead_days,
        gmail_limit=gmail_limit,
        gcal_limit=gcal_limit,
        message_limit_for_extraction=message_limit_for_extraction,
    )
    return {"ok": True, "summary": summary}
