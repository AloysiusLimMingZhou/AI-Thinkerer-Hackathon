import asyncio
import base64
import json
from contextlib import asynccontextmanager

import pytest

from meeting_agent.budget import BudgetExceeded, BudgetService
from meeting_agent.config import Settings
from meeting_agent.provider_calls import IntegrationUnavailable
from meeting_agent.repository import SQLiteRepository
from meeting_agent.voice import ElevenLabsVoice


class Socket:
    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.closed = False
    async def send(self, text):
        self.sent.append(json.loads(text))
    async def recv(self):
        if not self.frames:
            raise EOFError("unfinished secret")
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return json.dumps(frame)


class Connector:
    def __init__(self, frames):
        self.socket = Socket(frames)
        self.calls = []
    @asynccontextmanager
    async def __call__(self, uri, **kwargs):
        self.calls.append((uri, kwargs))
        try:
            yield self.socket
        finally:
            self.socket.closed = True


def voice_harness(tmp_path, frames, **kwargs):
    settings = Settings(database_path=tmp_path/"voice.db", elevenlabs_api_key="secret-test", **kwargs)
    budget = BudgetService(SQLiteRepository(settings.database_path), settings)
    connect = Connector(frames)
    return ElevenLabsVoice(settings, budget, connect=connect), budget, connect


@pytest.mark.asyncio
async def test_v4_dialogue_finalizes_once(tmp_path):
    voice, budget, connect = voice_harness(tmp_path, [
        {"audio":base64.b64encode(b"first-").decode()},
        {"audio":base64.b64encode(b"second").decode(), "is_final":True},
    ])
    assert await voice.generate("Hello.") == b"first-second"
    uri, options = connect.calls[0]
    assert "model_id=eleven_v4_turbo" in uri
    assert "output_format=mp3_44100_128" in uri
    assert options["additional_headers"]["xi-api-key"] == "secret-test"
    assert connect.socket.sent[0]["voices"] == [voice.settings.elevenlabs_voice_id]
    assert connect.socket.sent[1]["inputs"][0]["text"] == "Hello."
    assert connect.socket.sent[-1] == {"close_socket":True}
    assert connect.socket.closed
    assert budget.status().settled_micro_usd == len("Hello.") * 40


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [
    [{"audio":"@@@", "is_final":True}],
    [{"error":"secret-test"}],
    [{"audio":base64.b64encode(b"unfinished").decode()}],
    [TimeoutError("secret-test")],
    [{"is_final":True}],
], ids=["base64", "provider-error", "unfinished", "timeout", "empty"])
async def test_failed_synthesis_is_not_retried_or_refunded(tmp_path, frames):
    voice, budget, connect = voice_harness(tmp_path, frames)
    with pytest.raises(IntegrationUnavailable) as result:
        await voice.generate("Hello.")
    assert "secret-test" not in str(result.value)
    assert len(connect.calls) == 1
    assert budget.status().uncertain_count == 1
    assert budget.status().held_micro_usd > 0
    assert connect.socket.closed


@pytest.mark.asyncio
async def test_oversized_audio_is_bounded(tmp_path):
    voice, budget, connect = voice_harness(tmp_path, [{"audio":base64.b64encode(b"x" * (9*1024*1024)).decode(), "is_final":True}])
    with pytest.raises(IntegrationUnavailable):
        await voice.generate("Hello.")
    assert budget.status().uncertain_count == 1


@pytest.mark.asyncio
async def test_cap_and_missing_key_connect_nothing(tmp_path):
    voice, budget, connect = voice_harness(tmp_path, [], ai_monthly_soft_limit_usd="0", ai_monthly_hard_limit_usd="0.000001")
    with pytest.raises(BudgetExceeded):
        await voice.generate("Hello.")
    assert connect.calls == []
    missing = Settings(database_path=tmp_path/"none.db")
    with pytest.raises(IntegrationUnavailable):
        await ElevenLabsVoice(missing, budget, connect=connect).generate("Hello.")
    assert connect.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", " ", "x"*5001], ids=["empty", "blank", "too-long"])
async def test_invalid_text_never_connects(tmp_path, text):
    voice, budget, connect = voice_harness(tmp_path, [])
    with pytest.raises(ValueError):
        await voice.generate(text)
    assert connect.calls == []
    assert budget.status().held_micro_usd == 0


@pytest.mark.asyncio
async def test_cancelled_synthesis_retains_hold(tmp_path):
    voice, budget, connect = voice_harness(tmp_path, [asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await voice.generate("Hello.")
    assert connect.socket.closed
    assert budget.status().uncertain_count == 1


def test_manual_speech_route_obeys_provider_guard(tmp_path):
    from fastapi.testclient import TestClient
    from meeting_agent.api import create_app
    from test_api import FakeBrain
    settings = Settings(database_path=tmp_path/"route.db", backend_api_token="test",
        elevenlabs_api_key="fake", ai_monthly_soft_limit_usd="0", ai_monthly_hard_limit_usd="0.000001")
    budget = BudgetService(SQLiteRepository(settings.database_path), settings)
    connect = Connector([])
    app = create_app(settings=settings, brain=FakeBrain(), voice=ElevenLabsVoice(settings,budget,connect=connect))
    client = TestClient(app, headers={"Authorization":"Bearer test"})
    sid = client.post("/sessions",json={"title":"Test","owner_name":"Aloy"}).json()["id"]
    assert client.post(f"/sessions/{sid}/speak",json={"text":"Hello."}).status_code == 429
    assert connect.calls == []
