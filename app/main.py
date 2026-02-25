"""FastAPI app entrypoint."""

from pathlib import Path

from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import (
    get_obligation_by_id,
    get_response_candidate_by_id,
    init_db,
    list_obligations,
    list_upcoming_gcal_events,
    list_response_candidates,
    update_obligation_status,
    update_response_candidate_status,
)
from app.extractor import router as extractor_router
from app.gcal import router as gcal_router
from app.google_auth import has_stored_credentials, router as google_auth_router
from app.gmail import router as gmail_router
from app.pipeline import router as pipeline_router
from app.pipeline import run_scan_pipeline
from app.response_candidates import router as response_candidates_router
from app.timeparse import router as timeparse_router

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.include_router(google_auth_router)
app.include_router(gmail_router)
app.include_router(gcal_router)
app.include_router(extractor_router)
app.include_router(timeparse_router)
app.include_router(pipeline_router)
app.include_router(response_candidates_router)


@app.on_event("startup")
def startup() -> None:
    """Ensure local SQLite schema exists before serving requests."""
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    """Basic health check endpoint for local runtime validation."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the local home page."""
    scan_summary = request.query_params.get("scan_summary")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "google_connected": has_stored_credentials(),
            "scan_summary": scan_summary,
        },
    )


@app.post("/scan")
def run_scan_and_redirect(
    gmail_days: int = Query(default=7, ge=1, le=30),
    gcal_lookback_days: int = Query(default=1, ge=0, le=30),
    gcal_lookahead_days: int = Query(default=7, ge=1, le=60),
    gmail_limit: int = Query(default=100, ge=1, le=500),
    gcal_limit: int = Query(default=100, ge=1, le=500),
    message_limit_for_extraction: int = Query(default=200, ge=1, le=1000),
) -> RedirectResponse:
    """Run full scan pipeline and redirect to obligations dashboard."""
    summary = run_scan_pipeline(
        gmail_days=gmail_days,
        gcal_lookback_days=gcal_lookback_days,
        gcal_lookahead_days=gcal_lookahead_days,
        gmail_limit=gmail_limit,
        gcal_limit=gcal_limit,
        message_limit_for_extraction=message_limit_for_extraction,
    )
    summary_label = (
        f"Gmail({summary['gmail_days']}d) {summary['gmail_fetched']}, "
        f"GCal(-{summary['gcal_lookback_days']}+{summary['gcal_lookahead_days']}d) {summary['gcal_fetched']}, "
        f"Obligations {summary['obligations_found']}"
    )
    return RedirectResponse(url=f"/obligations?scan_summary={summary_label}", status_code=303)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@app.get("/obligations", response_class=HTMLResponse)
def obligations_dashboard(request: Request) -> HTMLResponse:
    """Render grouped obligations for quick triage."""
    all_items = list_obligations(limit=1000)
    include_routine = request.query_params.get("include_routine", "").lower() in {
        "1",
        "true",
        "yes",
    }
    upcoming_events = list_upcoming_gcal_events(
        lookback_days=1,
        lookahead_days=7,
        include_routine=include_routine,
    )
    now = datetime.now().astimezone()

    pending: list[dict] = []
    overdue: list[dict] = []
    suggested_followups: list[dict] = []

    for item in all_items:
        created_at = _parse_iso(item.get("created_at"))
        due_end = _parse_iso(item.get("time_window_end"))
        item["is_overdue"] = bool(
            item.get("status") == "pending" and due_end and due_end < now
        )
        item["source_url"] = (
            f"https://mail.google.com/mail/u/0/#all/{item['source_id']}"
            if item.get("source") == "gmail"
            else None
        )
        if item.get("status") == "pending":
            pending.append(item)
            if item["is_overdue"]:
                overdue.append(item)
            if not due_end and created_at and (now - created_at) > timedelta(days=3):
                suggested_followups.append(item)

    return templates.TemplateResponse(
        "obligations.html",
        {
            "request": request,
            "pending": pending,
            "overdue": overdue,
            "suggested_followups": suggested_followups,
            "all_count": len(all_items),
            "scan_summary": request.query_params.get("scan_summary"),
            "upcoming_events": upcoming_events,
            "include_routine": include_routine,
        },
    )


@app.get("/obligations/{obligation_id}", response_class=HTMLResponse)
def obligation_detail(request: Request, obligation_id: str) -> HTMLResponse:
    """Render detail view with evidence and status controls."""
    obligation = get_obligation_by_id(obligation_id)
    if not obligation:
        raise HTTPException(status_code=404, detail="Obligation not found.")
    obligation["source_url"] = (
        f"https://mail.google.com/mail/u/0/#all/{obligation['source_id']}"
        if obligation.get("source") == "gmail"
        else None
    )
    return templates.TemplateResponse(
        "obligation.html",
        {"request": request, "obligation": obligation},
    )


@app.post("/obligations/{obligation_id}/status")
def set_obligation_status(
    obligation_id: str,
    status: str = Query(...),
    next_path: str = Query(default="/obligations"),
) -> RedirectResponse:
    """Update triage status and redirect back to caller-selected page."""
    updated = update_obligation_status(obligation_id, status)
    if not updated:
        raise HTTPException(status_code=400, detail="Unable to update obligation status.")
    if not next_path.startswith("/"):
        next_path = "/obligations"
    return RedirectResponse(url=next_path, status_code=303)


@app.get("/responses", response_class=HTMLResponse)
def response_candidates_dashboard(request: Request) -> HTMLResponse:
    """Render response candidates for inbox triage."""
    all_items = list_response_candidates(limit=1000)
    now = datetime.now().astimezone()

    pending: list[dict] = []
    stale: list[dict] = []
    for item in all_items:
        created_at = _parse_iso(item.get("created_at"))
        item["source_url"] = f"https://mail.google.com/mail/u/0/#all/{item['message_id']}"
        if item.get("status") == "pending_response":
            pending.append(item)
            if created_at and (now - created_at) > timedelta(days=3):
                stale.append(item)

    return templates.TemplateResponse(
        "response_candidates.html",
        {
            "request": request,
            "pending": pending,
            "stale": stale,
            "all_count": len(all_items),
        },
    )


@app.get("/responses/{candidate_id}", response_class=HTMLResponse)
def response_candidate_detail(request: Request, candidate_id: str) -> HTMLResponse:
    """Render detail view with reason codes and status controls."""
    candidate = get_response_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Response candidate not found.")
    candidate["source_url"] = f"https://mail.google.com/mail/u/0/#all/{candidate['message_id']}"
    return templates.TemplateResponse(
        "response_candidate.html",
        {"request": request, "candidate": candidate},
    )


@app.post("/responses/{candidate_id}/status")
def set_response_candidate_status(
    candidate_id: str,
    status: str = Query(...),
    next_path: str = Query(default="/responses"),
) -> RedirectResponse:
    """Update response candidate status and redirect."""
    updated = update_response_candidate_status(candidate_id, status)
    if not updated:
        raise HTTPException(status_code=400, detail="Unable to update response candidate status.")
    if not next_path.startswith("/"):
        next_path = "/responses"
    return RedirectResponse(url=next_path, status_code=303)
