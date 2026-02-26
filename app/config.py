"""Configuration loading and settings."""

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOKEN_PATH = PROJECT_ROOT / "data" / "token.json"
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "ldu.db"


@dataclass(frozen=True)
class Settings:
    """App settings loaded from environment variables."""

    app_name: str
    app_host: str
    app_port: int
    session_secret_key: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_token_path: str
    sqlite_path: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings for app runtime."""
    load_dotenv()
    return Settings(
        app_name=os.getenv("APP_NAME", "Life Data Unifier"),
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        session_secret_key=os.getenv("SESSION_SECRET_KEY", "dev-local-secret-change-me"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.getenv(
            "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback"
        ).strip(),
        google_token_path=os.getenv("GOOGLE_TOKEN_PATH", str(DEFAULT_TOKEN_PATH)).strip(),
        sqlite_path=os.getenv("SQLITE_PATH", str(DEFAULT_SQLITE_PATH)).strip(),
    )
