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
    openai_model: str = "gpt-6-luna"
    openai_transcription_model: str = "gpt-transcribe"
    openai_answer_model: str = "gpt-6-luna"
    elevenlabs_voice_id: str = "IKne3meq5aSn9XLyUdCD"
    elevenlabs_model_id: str = "eleven_flash_v2_5"
    database_path: Path = Path("data/meeting_agent.db")
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    app_base_url: str = "http://localhost:8000"
    oauth_encryption_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    backend_api_token: str | None = None
    recall_api_key: str | None = None
    recall_region: str = "ap-northeast-1"
    recall_webhook_verification_secret: str | None = None
    public_api_base_url: str | None = None
    recall_media_base_url: str | None = None
    recall_calendar_callback_uri: str | None = None
    discord_bot_token: str | None = None
    discord_guild_id: str | None = None
    discord_escalation_channel_id: str | None = None
    discord_owner_user_id: str | None = None
    ai_monthly_soft_limit_usd: str = "5"
    ai_monthly_hard_limit_usd: str = "8"
    ai_budget_timezone: str = "Asia/Kuala_Lumpur"

    def __post_init__(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        from .cost_rates import dollars_to_micro
        try:
            soft = dollars_to_micro(self.ai_monthly_soft_limit_usd)
            hard = dollars_to_micro(self.ai_monthly_hard_limit_usd)
            ZoneInfo(self.ai_budget_timezone)
            if hard <= 0 or soft > hard:
                raise ValueError("Require 0 <= soft limit <= positive hard limit")
        except (ArithmeticError, ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError("Invalid monthly budget settings") from exc

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        )
        return cls(
            ai_monthly_soft_limit_usd=os.getenv('AI_MONTHLY_SOFT_LIMIT_USD','5'),
            ai_monthly_hard_limit_usd=os.getenv('AI_MONTHLY_HARD_LIMIT_USD','8'),
            ai_budget_timezone=os.getenv('AI_BUDGET_TIMEZONE','Asia/Kuala_Lumpur'),
            discord_bot_token=os.getenv('DISCORD_BOT_TOKEN') or None,
            discord_guild_id=os.getenv('DISCORD_GUILD_ID') or None,
            discord_escalation_channel_id=os.getenv('DISCORD_ESCALATION_CHANNEL_ID') or None,
            discord_owner_user_id=os.getenv('DISCORD_OWNER_USER_ID') or None,
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
            openai_model=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
            openai_transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-transcribe"),
            openai_answer_model=os.getenv("OPENAI_ANSWER_MODEL", "gpt-6-luna"),
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
        )
