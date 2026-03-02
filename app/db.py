"""SQLite connection helpers and setup."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any

from app.config import get_settings


def _db_path() -> Path:
    settings = get_settings()
    return Path(settings.sqlite_path).expanduser()


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection configured for dict-like row access."""
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def init_db() -> None:
    """Create required tables and indexes if they do not exist."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS gmail_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                date TEXT,
                subject TEXT,
                snippet TEXT,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gmail_inbox_messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                date TEXT,
                from_email TEXT,
                to_emails TEXT,
                cc_emails TEXT,
                subject TEXT,
                snippet TEXT,
                label_ids_json TEXT NOT NULL,
                headers_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gcal_events (
                id TEXT PRIMARY KEY,
                status TEXT,
                summary TEXT,
                description TEXT,
                start_time TEXT,
                end_time TEXT,
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS obligations (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL CHECK (source IN ('gmail', 'gcal')),
                source_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                text_evidence TEXT NOT NULL,
                action TEXT NOT NULL,
                counterparty TEXT,
                time_window_start TEXT,
                time_window_end TEXT,
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'dismissed', 'snoozed'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_obligations_source_source_id
            ON obligations(source, source_id);

            CREATE TABLE IF NOT EXISTS response_candidates (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                evidence_snippet TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL,
                score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
                status TEXT NOT NULL CHECK (status IN ('pending_response', 'done', 'dismissed', 'snoozed'))
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_response_candidates_message_id
            ON response_candidates(message_id);
            """
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_gmail_messages(items: list[dict[str, Any]]) -> int:
    """Upsert normalized Gmail messages into local SQLite."""
    if not items:
        return 0

    fetched_at = _utc_now_iso()
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO gmail_messages (id, thread_id, date, subject, snippet, payload_json, fetched_at)
            VALUES (:id, :thread_id, :date, :subject, :snippet, :payload_json, :fetched_at)
            ON CONFLICT(id) DO UPDATE SET
                thread_id=excluded.thread_id,
                date=excluded.date,
                subject=excluded.subject,
                snippet=excluded.snippet,
                payload_json=excluded.payload_json,
                fetched_at=excluded.fetched_at;
            """,
            [
                {
                    "id": item.get("id"),
                    "thread_id": item.get("thread_id"),
                    "date": item.get("date"),
                    "subject": item.get("subject", ""),
                    "snippet": item.get("snippet", ""),
                    "payload_json": json.dumps(item, ensure_ascii=True),
                    "fetched_at": fetched_at,
                }
                for item in items
                if item.get("id")
            ],
        )
        return conn.total_changes


def upsert_gmail_inbox_messages(items: list[dict[str, Any]]) -> int:
    """Upsert normalized inbox-side Gmail messages into local SQLite."""
    if not items:
        return 0

    fetched_at = _utc_now_iso()
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO gmail_inbox_messages (
                id, thread_id, date, from_email, to_emails, cc_emails, subject, snippet,
                label_ids_json, headers_json, payload_json, fetched_at
            )
            VALUES (
                :id, :thread_id, :date, :from_email, :to_emails, :cc_emails, :subject, :snippet,
                :label_ids_json, :headers_json, :payload_json, :fetched_at
            )
            ON CONFLICT(id) DO UPDATE SET
                thread_id=excluded.thread_id,
                date=excluded.date,
                from_email=excluded.from_email,
                to_emails=excluded.to_emails,
                cc_emails=excluded.cc_emails,
                subject=excluded.subject,
                snippet=excluded.snippet,
                label_ids_json=excluded.label_ids_json,
                headers_json=excluded.headers_json,
                payload_json=excluded.payload_json,
                fetched_at=excluded.fetched_at;
            """,
            [
                {
                    "id": item.get("id"),
                    "thread_id": item.get("thread_id"),
                    "date": item.get("date"),
                    "from_email": item.get("from", ""),
                    "to_emails": item.get("to", ""),
                    "cc_emails": item.get("cc", ""),
                    "subject": item.get("subject", ""),
                    "snippet": item.get("snippet", ""),
                    "label_ids_json": json.dumps(item.get("label_ids", []), ensure_ascii=True),
                    "headers_json": json.dumps(item.get("headers", {}), ensure_ascii=True),
                    "payload_json": json.dumps(item, ensure_ascii=True),
                    "fetched_at": fetched_at,
                }
                for item in items
                if item.get("id")
            ],
        )
        return conn.total_changes


def upsert_gcal_events(items: list[dict[str, Any]]) -> int:
    """Upsert normalized Google Calendar events into local SQLite."""
    if not items:
        return 0

    fetched_at = _utc_now_iso()
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO gcal_events (id, status, summary, description, start_time, end_time, payload_json, fetched_at)
            VALUES (:id, :status, :summary, :description, :start_time, :end_time, :payload_json, :fetched_at)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                summary=excluded.summary,
                description=excluded.description,
                start_time=excluded.start_time,
                end_time=excluded.end_time,
                payload_json=excluded.payload_json,
                fetched_at=excluded.fetched_at;
            """,
            [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "summary": item.get("summary", ""),
                    "description": item.get("description", ""),
                    "start_time": item.get("start"),
                    "end_time": item.get("end"),
                    "payload_json": json.dumps(item, ensure_ascii=True),
                    "fetched_at": fetched_at,
                }
                for item in items
                if item.get("id")
            ],
        )
        return conn.total_changes


def upsert_obligations(items: list[dict[str, Any]]) -> int:
    """Upsert obligations records into local SQLite."""
    if not items:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO obligations (
                id, source, source_id, created_at, text_evidence, action, counterparty,
                time_window_start, time_window_end, confidence, status
            )
            VALUES (
                :id, :source, :source_id, :created_at, :text_evidence, :action, :counterparty,
                :time_window_start, :time_window_end, :confidence, :status
            )
            ON CONFLICT(id) DO UPDATE SET
                source=excluded.source,
                source_id=excluded.source_id,
                created_at=excluded.created_at,
                text_evidence=excluded.text_evidence,
                action=excluded.action,
                counterparty=excluded.counterparty,
                time_window_start=excluded.time_window_start,
                time_window_end=excluded.time_window_end,
                confidence=excluded.confidence,
                status=excluded.status;
            """,
            [
                {
                    "id": item.get("id"),
                    "source": item.get("source"),
                    "source_id": item.get("source_id"),
                    "created_at": item.get("created_at"),
                    "text_evidence": item.get("text_evidence", ""),
                    "action": item.get("action", ""),
                    "counterparty": item.get("counterparty"),
                    "time_window_start": item.get("time_window_start"),
                    "time_window_end": item.get("time_window_end"),
                    "confidence": float(item.get("confidence", 0)),
                    "status": item.get("status", "pending"),
                }
                for item in items
                if item.get("id")
            ],
        )
        return conn.total_changes


def get_recent_gmail_messages(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent Gmail message rows for extraction/debug purposes."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, thread_id, date, subject, snippet, fetched_at
            FROM gmail_messages
            ORDER BY COALESCE(date, fetched_at) DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_recent_gmail_inbox_messages(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent inbox-side Gmail rows for response-candidate analysis."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, thread_id, date, from_email, to_emails, cc_emails, subject, snippet,
                   label_ids_json, headers_json, fetched_at
            FROM gmail_inbox_messages
            ORDER BY COALESCE(date, fetched_at) DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        entry["label_ids"] = json.loads(entry.pop("label_ids_json"))
        entry["headers"] = json.loads(entry.pop("headers_json"))
        results.append(entry)
    return results


def get_latest_sent_by_thread(thread_ids: list[str]) -> dict[str, str]:
    """Return latest sent-message date by thread id."""
    if not thread_ids:
        return {}

    unique_ids = list(dict.fromkeys([t for t in thread_ids if t]))
    if not unique_ids:
        return {}

    placeholders = ",".join(["?"] * len(unique_ids))
    query = f"""
        SELECT thread_id, MAX(COALESCE(date, fetched_at)) AS latest_sent_at
        FROM gmail_messages
        WHERE thread_id IN ({placeholders})
        GROUP BY thread_id;
    """
    with get_connection() as conn:
        cursor = conn.execute(query, tuple(unique_ids))
        rows = cursor.fetchall()

    return {
        str(row["thread_id"]): str(row["latest_sent_at"])
        for row in rows
        if row["thread_id"] and row["latest_sent_at"]
    }


def list_upcoming_gcal_events(
    lookback_days: int = 1,
    lookahead_days: int = 7,
    limit: int = 300,
    include_routine: bool = False,
) -> list[dict[str, Any]]:
    """Return upcoming calendar events, optionally filtering routine events."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=lookback_days)
    window_end = now + timedelta(days=lookahead_days)

    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, status, summary, description, start_time, end_time, payload_json
            FROM gcal_events
            ORDER BY start_time ASC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    staged: list[dict[str, Any]] = []
    summary_frequency: dict[str, int] = {}
    for row in rows:
        entry = dict(row)
        if entry.get("status") == "cancelled":
            continue
        start = _parse_datetime(entry.get("start_time"))
        if not start:
            continue
        if start < window_start or start > window_end:
            continue

        payload = _safe_json_loads(entry.get("payload_json"))
        summary_key = str(entry.get("summary", "")).strip().lower()
        if summary_key:
            summary_frequency[summary_key] = summary_frequency.get(summary_key, 0) + 1

        entry["html_link"] = payload.get("html_link")
        entry["is_recurring"] = bool(payload.get("is_recurring"))
        staged.append(entry)

    result: list[dict[str, Any]] = []
    for entry in staged:
        summary_key = str(entry.get("summary", "")).strip().lower()
        repeated_in_window = summary_frequency.get(summary_key, 0) >= 3 if summary_key else False
        is_routine = bool(entry.get("is_recurring")) or repeated_in_window
        entry["is_routine"] = is_routine
        if not include_routine and is_routine:
            continue
        result.append(entry)

    return result


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def list_obligations(limit: int = 500) -> list[dict[str, Any]]:
    """Return obligations ordered by newest created time first."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, source, source_id, created_at, text_evidence, action, counterparty,
                   time_window_start, time_window_end, confidence, status
            FROM obligations
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_obligation_by_id(obligation_id: str) -> dict[str, Any] | None:
    """Return one obligation row or None if not found."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, source, source_id, created_at, text_evidence, action, counterparty,
                   time_window_start, time_window_end, confidence, status
            FROM obligations
            WHERE id = ?
            LIMIT 1;
            """,
            (obligation_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def update_obligation_status(obligation_id: str, status: str) -> bool:
    """Update obligation status. Returns True when one row was updated."""
    if status not in {"pending", "done", "dismissed", "snoozed"}:
        return False

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE obligations
            SET status = ?
            WHERE id = ?;
            """,
            (status, obligation_id),
        )
        return cursor.rowcount == 1


def upsert_response_candidates(items: list[dict[str, Any]]) -> int:
    """Upsert response candidate rows into local SQLite."""
    if not items:
        return 0

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO response_candidates (
                id, message_id, thread_id, created_at, evidence_snippet,
                reason_codes_json, score, status
            )
            VALUES (
                :id, :message_id, :thread_id, :created_at, :evidence_snippet,
                :reason_codes_json, :score, :status
            )
            ON CONFLICT(id) DO UPDATE SET
                message_id=excluded.message_id,
                thread_id=excluded.thread_id,
                created_at=excluded.created_at,
                evidence_snippet=excluded.evidence_snippet,
                reason_codes_json=excluded.reason_codes_json,
                score=excluded.score,
                status=excluded.status;
            """,
            [
                {
                    "id": item.get("id"),
                    "message_id": item.get("message_id"),
                    "thread_id": item.get("thread_id"),
                    "created_at": item.get("created_at"),
                    "evidence_snippet": item.get("evidence_snippet", ""),
                    "reason_codes_json": json.dumps(item.get("reason_codes", []), ensure_ascii=True),
                    "score": float(item.get("score", 0)),
                    "status": item.get("status", "pending_response"),
                }
                for item in items
                if item.get("id")
            ],
        )
        return conn.total_changes


def list_response_candidates(limit: int = 500) -> list[dict[str, Any]]:
    """Return response candidates ordered by score then newest."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, message_id, thread_id, created_at, evidence_snippet,
                   reason_codes_json, score, status
            FROM response_candidates
            ORDER BY score DESC, created_at DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        entry["reason_codes"] = json.loads(entry.pop("reason_codes_json"))
        results.append(entry)
    return results


def get_response_candidate_by_id(candidate_id: str) -> dict[str, Any] | None:
    """Return one response candidate row or None if not found."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, message_id, thread_id, created_at, evidence_snippet,
                   reason_codes_json, score, status
            FROM response_candidates
            WHERE id = ?
            LIMIT 1;
            """,
            (candidate_id,),
        )
        row = cursor.fetchone()

    if not row:
        return None

    result = dict(row)
    result["reason_codes"] = json.loads(result.pop("reason_codes_json"))
    return result


def update_response_candidate_status(candidate_id: str, status: str) -> bool:
    """Update response candidate status. Returns True when one row was updated."""
    if status not in {"pending_response", "done", "dismissed", "snoozed"}:
        return False

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE response_candidates
            SET status = ?
            WHERE id = ?;
            """,
            (status, candidate_id),
        )
        return cursor.rowcount == 1
