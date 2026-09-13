import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from meeting_agent.config import Settings
from meeting_agent.models import (
    ContextNoteView,
    SessionStatus,
    SessionView,
    TranscriptEntry,
)
from meeting_agent.services import (
    OpenAIBrain,
    conversation_gate,
    enforce_action_boundary,
    retrieve_context,
)


def meeting():
    return SessionView(
        id="demo",
        title="Launch",
        owner_name="Aloy",
        agent_name="Alloy",
        status=SessionStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "speaker,gap,text,expected",
    [
        ("Jamie", 10, "What about the budget?", True),
        ("Jamie", 10, "He's a guy, by the way", True),
        ("Jamie", 10, "Hey Sam, what do you think?", False),
        ("Sam", 10, "What about the budget?", False),
        ("Jamie", 40, "What about the budget?", False),
        ("Unknown participant", 10, "What about the budget?", False),
    ],
)
def test_conversation_floor(speaker, gap, text, expected):
    now = datetime.now(UTC)
    question = "Alloy, when is launch?"
    transcript = [
        TranscriptEntry(
            id="1", speaker="Jamie", text=question, is_final=True, spoken_at=now
        ),
        TranscriptEntry(
            id="2",
            speaker=speaker,
            text=text,
            is_final=True,
            spoken_at=now + timedelta(seconds=gap),
        ),
    ]
    qa = [
        {
            "question": question,
            "answer": "Friday.",
            "created_at": (now + timedelta(seconds=2)).isoformat(),
        }
    ]
    assert (
        conversation_gate(
            text, speaker=speaker, session=meeting(), transcript=transcript, qa_log=qa
        )[0]
        is expected
    )


def test_unanswered_previous_question_does_not_open_floor():
    now = datetime.now(UTC)
    transcript = [
        TranscriptEntry(
            id=str(i), speaker="Jamie", text=text, is_final=True, spoken_at=now
        )
        for i, text in enumerate(["What's next?", "What about budget?"])
    ]
    assert not conversation_gate(
        "What about budget?",
        speaker="Jamie",
        session=meeting(),
        transcript=transcript,
        qa_log=[],
    )[0]


def test_profile_is_selected_without_keyword_overlap():
    profile = ContextNoteView(
        id="p",
        source="owner-profile",
        title="Style",
        content="Aloy prefers concise, casual English.",
        created_at=datetime.now(UTC),
    )
    assert retrieve_context("When do we ship?", [profile]) == [profile]


def test_answer_model_prompt_and_dialogue_contract():
    brain = OpenAIBrain(Settings())
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return "We haven't settled the budget yet."

    brain._complete = complete
    history = [
        TranscriptEntry(
            id="assistant-qa-0",
            speaker="Alloy",
            text="Friday.",
            is_final=True,
            spoken_at=datetime.now(UTC),
        )
    ]
    asyncio.run(brain.answer(meeting(), "What about the budget?", history, []))
    assert captured["model"] == "gpt-4.1-mini"
    assert "reasoning" not in captured
    assert captured["max_output_tokens"] == 300
    assert captured["store"] is False
    assert "NO action tools" in captured["instructions"]
    assert "distinct identities" in captured["instructions"]
    assert "flag it for the owner" not in captured["instructions"]
    assert json.loads(captured["input"])["recent_transcript"][0]["role"] == "assistant"


def test_minutes_keep_original_model():
    brain = OpenAIBrain(Settings())
    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return "# Summary"

    brain._complete = complete
    asyncio.run(brain.generate_minutes(meeting(), [], [], []))
    assert captured["model"] == "gpt-5-mini"
    assert captured["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize(
    "answer",
    [
        "I'll flag this for her.",
        "I can remind Aloy about it.",
        "I've sent him a message.",
        "I will let Aloy know.",
        "I can approve the budget.",
        "I'm going to notify him.",
        "If there's something constructive you want me to share, let me know.",
    ],
)
def test_false_action_promises_are_blocked(answer):
    result = enforce_action_boundary(answer, "Aloy")
    assert "can't take that action" in result


@pytest.mark.parametrize(
    "answer",
    [
        "We haven't settled the budget yet.",
        "I can't send messages from here.",
        "I can help draft a message.",
        "Got it — he.",
    ],
)
def test_normal_speech_is_not_rewritten(answer):
    assert enforce_action_boundary(answer, "Aloy") == answer
