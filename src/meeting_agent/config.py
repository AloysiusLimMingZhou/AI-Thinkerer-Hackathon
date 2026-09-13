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
        )
