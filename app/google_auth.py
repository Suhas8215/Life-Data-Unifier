"""Google OAuth flow and token management."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings, get_settings

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

router = APIRouter(tags=["auth"])


def _token_path(settings: Settings) -> Path:
    return Path(settings.google_token_path).expanduser()


def has_stored_credentials() -> bool:
    """Return whether Google OAuth credentials are already stored locally."""
    settings = get_settings()
    return _token_path(settings).exists()


def save_credentials(credentials: Credentials, settings: Settings) -> None:
    """Persist OAuth credentials to local disk for future API calls."""
    token_path = _token_path(settings)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def _build_flow(settings: Settings, state: str | None = None) -> Flow:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Fill GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GOOGLE_SCOPES, state=state)
    flow.redirect_uri = settings.google_redirect_uri
    return flow


@router.get("/auth/login")
def auth_login(request: Request) -> RedirectResponse:
    """Start Google OAuth flow and redirect user to consent screen."""
    settings = get_settings()
    flow = _build_flow(settings)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    request.session["google_oauth_state"] = state
    return RedirectResponse(url=authorization_url, status_code=302)


@router.get("/auth/callback")
def auth_callback(request: Request) -> RedirectResponse:
    """Handle Google OAuth callback and persist access credentials locally."""
    settings = get_settings()
    state = request.session.get("google_oauth_state")
    query_state = request.query_params.get("state")
    if not state or state != query_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    flow = _build_flow(settings, state=state)
    flow.fetch_token(authorization_response=str(request.url))
    save_credentials(flow.credentials, settings)
    request.session.pop("google_oauth_state", None)
    return RedirectResponse(url="/", status_code=302)
