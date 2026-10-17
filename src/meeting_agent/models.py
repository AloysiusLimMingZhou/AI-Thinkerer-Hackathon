from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    ENDED = "ended"


class Provider(StrEnum):
    GOOGLE = "google"


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=100)
    agent_name: str = Field(default="Alloy", min_length=1, max_length=100)
    meeting_url: str | None = Field(default=None, max_length=2_000)
    platform: Literal["google_meet", "discord"] = "google_meet"
    purpose: Literal["meeting", "briefing"] = "meeting"
    source_briefing_id: str | None = Field(default=None, max_length=200)
    briefing_ready: bool = False

    @model_validator(mode="after")
    def validate_platform_purpose(self):
        if self.platform == "discord" and self.meeting_url:
            raise ValueError("Discord sessions do not use a meeting URL")
        if self.purpose == "briefing" and self.platform != "discord":
            raise ValueError("Prepared briefings are for Discord")
        if self.purpose == "meeting" and self.briefing_ready:
            raise ValueError("Only briefings can be marked ready")
        return self


class SessionView(SessionCreate):
    id: str
    status: SessionStatus
    created_at: datetime


class ContextNoteCreate(BaseModel):
    source: str = Field(default="notes", min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100_000)


class ContextNoteView(ContextNoteCreate):
    id: str
    created_at: datetime


class ContextBatch(BaseModel):
    notes: list[ContextNoteCreate] = Field(min_length=1, max_length=100)


class UtteranceCreate(BaseModel):
    event_id: str | None = Field(default=None,max_length=200)
    participant_id: str | None = Field(default=None,max_length=200)
    is_self: bool = False
    speaker: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=10_000)
    is_final: bool = True
    force_answer: bool = False
    spoken_at: AwareDatetime = Field(default_factory=utc_now)


class TranscriptEntry(BaseModel):
    participant_id: str | None = None
    id: str
    speaker: str
    text: str
    is_final: bool
    spoken_at: datetime


class Citation(BaseModel):
    filename: str | None = None
    locator: str | None = None
    quote: str | None = None
    id: str
    source: str
    title: str


class AgentDecision(BaseModel):
    action: Literal["stay_silent", "answer", "defer"]
    reason: str
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class CoachRequest(BaseModel):
    latest_message: str = Field(min_length=1, max_length=10_000)
    objective: str | None = Field(default=None, max_length=2_000)


class CoachSuggestion(BaseModel):
    suggestion: str
    citations: list[Citation] = Field(default_factory=list)


class OAuthStartView(BaseModel):
    provider: Provider
    authorization_url: str
    expires_in_seconds: int = 600


class IntegrationView(BaseModel):
    provider: Provider
    connected: bool
    configured: bool
    account_id: str | None = None
    account_label: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None


class ProviderCapabilityView(BaseModel):
    provider: Provider
    role: Literal["meeting", "context"]
    oauth_supported: bool
    context_imports: list[str]
    live_audio_input: str
    live_voice_output: str
    requirement: str


class ContextImportRequest(BaseModel):
    provider: Provider
    resource_type: str = Field(min_length=1, max_length=50)
    resource_id: str = Field(min_length=1, max_length=2_000)
    container_id: str | None = Field(default=None, max_length=2_000)
    limit: int = Field(default=15, ge=1, le=50)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5_000)


class MinutesView(BaseModel):
    session_id: str
    content: str
    updated_at: datetime


class HealthView(BaseModel):
    status: Literal["ok"] = "ok"
    openai_configured: bool
    elevenlabs_configured: bool
