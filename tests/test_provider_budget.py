import asyncio
import io
import json
import wave
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from meeting_agent.budget import BudgetExceeded, BudgetService, PaidCallContext, paid_call_context
from meeting_agent.config import Settings
from meeting_agent.models import SessionView, TranscriptEntry
from meeting_agent.repository import SQLiteRepository
from meeting_agent.services import IntegrationUnavailable, OpenAIBrain
from meeting_agent.transcription import OpenAITranscriber


def wav(seconds=1, channels=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"\0" * int(seconds * rate * channels * 2))
    return output.getvalue()


def setup(tmp_path, **kwargs):
    settings = Settings(database_path=tmp_path/"paid.db", openai_api_key="fake", **kwargs)
    budget = BudgetService(SQLiteRepository(settings.database_path), settings)
    create = AsyncMock(return_value=SimpleNamespace(status="completed",
        output_text='{"kind":"social","text":"Hi.","evidence":[]}',
        usage=SimpleNamespace(input_tokens=100, output_tokens=20), _request_id="req1"))
    client = SimpleNamespace(responses=SimpleNamespace(create=create),
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(text="Hello.")))))
    return settings, budget, client


def session():
    return SessionView(id="s", title="Meeting", owner_name="Aloy", agent_name="Alloy", status="active", created_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_luna_uses_recent_context_and_settles_usage(tmp_path):
    settings, budget, client = setup(tmp_path)
    brain = OpenAIBrain(settings, budget, client=client)
    history = [TranscriptEntry(id=str(i), speaker="Guest", text="EARLY_PRIVATE_SENTINEL" if i==0 else "x"*3000,
        is_final=True, spoken_at=datetime.now(UTC)) for i in range(14)]
    result = await brain.answer(session(), "Alloy, hello?", history, [])
    request = client.responses.create.call_args.kwargs
    assert request["model"] == "gpt-6-luna"
    assert request["reasoning"] == {"effort": "none"}
    assert request["max_output_tokens"] == 1000
    assert "EARLY_PRIVATE_SENTINEL" not in request["input"]
    assert len(json.loads(request["input"])["recent_transcript"]) == 12
    assert len(json.loads(request["input"])["recent_transcript"][0]["text"]) == 2000
    assert result.text == "Hi."
    assert budget.status().settled_micro_usd == 20
    assert budget.status().held_micro_usd == 0


@pytest.mark.asyncio
async def test_luna_denial_and_missing_key_dispatch_nothing(tmp_path):
    settings, budget, client = setup(tmp_path, ai_monthly_soft_limit_usd="0", ai_monthly_hard_limit_usd="0.000001")
    with pytest.raises(BudgetExceeded):
        await OpenAIBrain(settings, budget, client=client).answer(session(), "Hi", [], [])
    assert client.responses.create.await_count == 0
    missing = Settings(database_path=tmp_path/"missing.db")
    with pytest.raises(IntegrationUnavailable):
        await OpenAIBrain(missing, budget, client=client).answer(session(), "Hi", [], [])
    assert client.responses.create.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("secret"), asyncio.CancelledError()])
async def test_openai_timeout_or_cancellation_holds_reservation(tmp_path, error):
    settings, budget, client = setup(tmp_path)
    client.responses.create.side_effect = error
    with pytest.raises((IntegrationUnavailable, asyncio.CancelledError)):
        await OpenAIBrain(settings, budget, client=client).answer(session(), "Hi", [], [])
    assert client.responses.create.await_count == 1
    assert budget.status().uncertain_count == 1
    assert budget.status().held_micro_usd > 0


@pytest.mark.asyncio
async def test_missing_usage_stays_held_and_incomplete_output_not_spoken(tmp_path):
    settings, budget, client = setup(tmp_path)
    client.responses.create.return_value.usage = None
    await OpenAIBrain(settings, budget, client=client).answer(session(), "Hi", [], [])
    assert budget.status().uncertain_count == 1
    client.responses.create.return_value.status = "incomplete"
    with pytest.raises(IntegrationUnavailable):
        await OpenAIBrain(settings, budget, client=client).answer(session(), "Hi", [], [])


@pytest.mark.asyncio
async def test_transcription_exact_model_duration_and_replay(tmp_path):
    settings, budget, client = setup(tmp_path)
    transcriber = OpenAITranscriber(settings, budget, client=client)
    assert await transcriber.transcribe(wav(), session_id="s", event_id="u1") == "Hello."
    request = client.audio.transcriptions.create.call_args.kwargs
    assert request["model"] == "gpt-transcribe"
    assert request["file"][0] == "utterance.wav"
    assert budget.status().settled_micro_usd == 75
    from meeting_agent.budget import DuplicateOperation
    with pytest.raises(DuplicateOperation):
        await transcriber.transcribe(wav(), session_id="s", event_id="u1")
    assert client.audio.transcriptions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("audio", [b"not-wav", wav(16), wav(channels=2), wav(rate=48000)], ids=["invalid", "too-long", "stereo", "wrong-rate"])
async def test_bad_audio_never_spends(tmp_path, audio):
    settings, budget, client = setup(tmp_path)
    with pytest.raises(ValueError):
        await OpenAITranscriber(settings, budget, client=client).transcribe(audio, session_id="s", event_id="bad")
    assert client.audio.transcriptions.create.await_count == 0
    assert budget.status().held_micro_usd == 0


@pytest.mark.asyncio
async def test_transcription_timeout_blank_and_oversized_text(tmp_path):
    settings, budget, client = setup(tmp_path)
    transcriber = OpenAITranscriber(settings, budget, client=client)
    call = client.audio.transcriptions.create
    call.side_effect = TimeoutError("secret")
    with pytest.raises(IntegrationUnavailable, match="transcription"):
        await transcriber.transcribe(wav(), session_id="s", event_id="timeout")
    assert budget.status().uncertain_count == 1
    call.side_effect = None
    for index, text in enumerate([" ", "x"*10001]):
        call.return_value.text = text
        with pytest.raises(IntegrationUnavailable):
            await transcriber.transcribe(wav(), session_id="s", event_id=f"invalid-{index}")


@pytest.mark.asyncio
async def test_minutes_explicit_reasoning_and_context_provenance(tmp_path):
    settings, budget, client = setup(tmp_path)
    brain = OpenAIBrain(settings, budget, client=client)
    with paid_call_context(PaidCallContext("s", "final-stage", "minutes")):
        await brain.summarize_minutes(session(), "EARLY_DECISION", synthesis=False)
    request = client.responses.create.call_args.kwargs
    assert request["reasoning"] == {"effort": "low"}
    assert request["max_output_tokens"] == 2000
    with budget.repository._connect() as db:
        row = db.execute("SELECT * FROM ai_cost_ledger").fetchone()
        assert row["session_id"] == "s"
        assert row["purpose"] == "minutes-segment"
