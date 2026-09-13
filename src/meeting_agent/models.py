from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    ENDED = "ended"


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=100)
    agent_name: str = Field(default="Thinkerer", min_length=1, max_length=100)
    meeting_url: str | None = Field(default=None, max_length=2_000)


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
    speaker: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=10_000)
    is_final: bool = True
    force_answer: bool = False
    spoken_at: datetime = Field(default_factory=utc_now)


class TranscriptEntry(BaseModel):
    id: str
    speaker: str
    text: str
    is_final: bool
    spoken_at: datetime


class Citation(BaseModel):
    id: str
    source: str
    title: str


class AgentDecision(BaseModel):
    action: Literal["stay_silent", "answer"]
    reason: str
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)


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
