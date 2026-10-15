from datetime import UTC, datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

UNKNOWN_ANSWER="I don't know based on the knowledge I have. Is this urgent?"


class AnswerEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chunk_id: str
    quote: str


class BrainAnswer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind: Literal['supported','unknown','social']
    text: str
    evidence: list[AnswerEvidence]


class MeetingUtterance(BaseModel):
    event_id: str
    platform: Literal['google_meet','discord','preview']
    participant_id: str | None = None
    speaker: str
    spoken_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    received_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    text: str
    is_final: bool = True
    is_self: bool = False
    force_answer: bool = False
