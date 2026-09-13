from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    openai_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    database_path: Path = Path("data/meeting_agent.db")
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    app_base_url: str = "http://localhost:8000"
    oauth_encryption_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    microsoft_client_id: str | None = None
    microsoft_client_secret: str | None = None
    zoom_client_id: str | None = None
    zoom_client_secret: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        )
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            elevenlabs_voice_id=os.getenv(
                "ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"
            ),
            elevenlabs_model_id=os.getenv(
                "ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"
            ),
            database_path=Path(os.getenv("MEETING_AGENT_DB", "data/meeting_agent.db")),
            cors_origins=origins,
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
            oauth_encryption_key=os.getenv("OAUTH_ENCRYPTION_KEY") or None,
            google_client_id=os.getenv("GOOGLE_CLIENT_ID") or None,
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or None,
            slack_client_id=os.getenv("SLACK_CLIENT_ID") or None,
            slack_client_secret=os.getenv("SLACK_CLIENT_SECRET") or None,
            microsoft_client_id=os.getenv("MICROSOFT_CLIENT_ID") or None,
            microsoft_client_secret=os.getenv("MICROSOFT_CLIENT_SECRET") or None,
            zoom_client_id=os.getenv("ZOOM_CLIENT_ID") or None,
            zoom_client_secret=os.getenv("ZOOM_CLIENT_SECRET") or None,
        )
