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
    openai_answer_model: str = "gpt-4.1-mini"
    elevenlabs_voice_id: str = "IKne3meq5aSn9XLyUdCD"
    elevenlabs_model_id: str = "eleven_flash_v2_5"
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
    backend_api_token: str | None = None
    recall_api_key: str | None = None
    recall_region: str = "ap-northeast-1"
    recall_webhook_verification_secret: str | None = None
    public_api_base_url: str | None = None
    recall_media_base_url: str | None = None
    recall_calendar_callback_uri: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        )
        return cls(
            recall_media_base_url=(os.getenv("RECALL_MEDIA_BASE_URL") or "").rstrip("/")
            or None,
            backend_api_token=os.getenv("BACKEND_API_TOKEN") or None,
            recall_api_key=os.getenv("RECALL_API_KEY") or None,
            recall_region=os.getenv("RECALL_REGION", "ap-northeast-1"),
            recall_webhook_verification_secret=os.getenv(
                "RECALL_WEBHOOK_VERIFICATION_SECRET"
            )
            or None,
            public_api_base_url=(os.getenv("PUBLIC_API_BASE_URL") or "").rstrip("/")
            or None,
            recall_calendar_callback_uri=os.getenv("RECALL_CALENDAR_CALLBACK_URI")
            or None,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            openai_answer_model=os.getenv("OPENAI_ANSWER_MODEL", "gpt-4.1-mini"),
            elevenlabs_voice_id=os.getenv(
                "ELEVENLABS_VOICE_ID", "IKne3meq5aSn9XLyUdCD"
            ),
            elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
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
