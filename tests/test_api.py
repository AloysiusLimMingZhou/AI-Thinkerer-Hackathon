from pathlib import Path

from fastapi.testclient import TestClient

from meeting_agent.api import create_app
from meeting_agent.config import Settings
from meeting_agent.models import ContextNoteView, SessionView, TranscriptEntry


class FakeBrain:
    def __init__(self) -> None:
        self.context_seen: list[ContextNoteView] = []

    async def answer(
        self,
        session: SessionView,
        question: str,
        transcript: list[TranscriptEntry],
        context: list[ContextNoteView],
    ) -> str:
        self.context_seen = list(context)
        return "The refunds migration is scheduled for Tuesday."

    async def generate_minutes(
        self,
        session: SessionView,
        transcript: list[TranscriptEntry],
        context: list[ContextNoteView],
        qa_log: list[dict[str, object]],
    ) -> str:
        return "# Summary\n\nThe team reviewed the refunds migration."


class FakeVoice:
    async def generate(self, text: str) -> bytes:
        return b"fake-mp3"


def make_client(tmp_path: Path) -> tuple[TestClient, FakeBrain]:
    brain = FakeBrain()
    settings = Settings(database_path=tmp_path / "test.db")
    app = create_app(settings=settings, brain=brain, voice=FakeVoice())
    return TestClient(app), brain


def test_end_to_end_session_flow(tmp_path: Path) -> None:
    client, brain = make_client(tmp_path)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "openai_configured": False,
        "elevenlabs_configured": False,
    }

    created = client.post(
        "/sessions",
        json={
            "title": "Payments standup",
            "owner_name": "Aloy",
            "agent_name": "Aloy-bot",
        },
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    context = client.post(
        f"/sessions/{session_id}/context",
        json={
            "notes": [
                {
                    "source": "past-meeting",
                    "title": "Refund migration plan",
                    "content": "The refunds migration is scheduled for Tuesday.",
                },
                {
                    "source": "slack",
                    "title": "Unrelated hiring update",
                    "content": "Two interviews are booked this week.",
                },
            ]
        },
    )
    assert context.status_code == 201

    silent = client.post(
        f"/sessions/{session_id}/utterances",
        json={"speaker": "Jamie", "text": "The dashboard looks good."},
    )
    assert silent.status_code == 200
    assert silent.json()["action"] == "stay_silent"
    assert silent.json()["reason"] == "wake name not detected"

    answered = client.post(
        f"/sessions/{session_id}/utterances",
        json={
            "speaker": "Jamie",
            "text": "Aloy-bot, when is the refunds migration?",
        },
    )
    assert answered.status_code == 200
    assert answered.json()["action"] == "answer"
    assert answered.json()["answer"].startswith("The refunds migration")
    assert [item.title for item in brain.context_seen] == ["Refund migration plan"]
    assert answered.json()["citations"][0]["source"] == "past-meeting"

    audio = client.post(
        f"/sessions/{session_id}/speak", json={"text": answered.json()["answer"]}
    )
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == b"fake-mp3"

    minutes = client.post(f"/sessions/{session_id}/minutes")
    assert minutes.status_code == 200
    assert "# Summary" in minutes.json()["content"]
    assert client.get(f"/sessions/{session_id}/minutes").json() == minutes.json()

    events = client.get(f"/sessions/{session_id}/events").json()
    assert {event["type"] for event in events} >= {
        "session.created",
        "context.added",
        "transcript.utterance",
        "agent.decision",
        "voice.generated",
        "minutes.generated",
    }


def test_partial_caption_waits_and_manual_override_answers(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session = client.post(
        "/sessions",
        json={"title": "Demo", "owner_name": "Muste", "agent_name": "Thinkerer"},
    ).json()

    partial = client.post(
        f"/sessions/{session['id']}/utterances",
        json={"speaker": "Sam", "text": "Thinkerer, what", "is_final": False},
    )
    assert partial.json()["reason"] == "waiting for final caption"

    forced = client.post(
        f"/sessions/{session['id']}/utterances",
        json={"speaker": "Muste", "text": "Give the update", "force_answer": True},
    )
    assert forced.status_code == 200
    assert forced.json()["action"] == "answer"
    assert forced.json()["reason"] == "manual override"


def test_unknown_session_is_404(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/sessions/missing").status_code == 404
