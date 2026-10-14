from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from meeting_agent.api import create_app
from meeting_agent.meeting_models import BrainAnswer, AnswerEvidence
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
        return BrainAnswer(kind="supported", text="The refunds migration is scheduled for Tuesday.",
            evidence=[AnswerEvidence(chunk_id=context[0].id,quote=context[0].text)] if context else [])

    async def summarize_minutes(self,session,material,*,synthesis):
        return "# Summary\n\nThe team reviewed the refunds migration."


class FakeVoice:
    async def generate(self, text: str) -> bytes:
        return b"fake-mp3"


class FakeProviderRequester:
    def __init__(self):
        self.last_headers = {}

    async def post(self, url, *, data=None, headers=None, auth=None):
        assert url == "https://oauth2.googleapis.com/token"
        assert data["client_id"] == "google-client"
        assert data["client_secret"] == "google-secret"
        return httpx.Response(200, json={"access_token":"google-private-token", "scope":"calendar.readonly"})

    async def get(self, url, *, headers=None, params=None):
        assert url == "https://www.googleapis.com/calendar/v3/calendars/primary/events/event-1"
        self.last_headers = headers
        return httpx.Response(200, json={"summary":"Launch", "description":"Ship on Tuesday"})


def make_client(tmp_path: Path) -> tuple[TestClient, FakeBrain]:
    brain = FakeBrain()
    settings = Settings(
        database_path=tmp_path / "test.db", backend_api_token="test-token"
    )
    app = create_app(settings=settings, brain=brain, voice=FakeVoice())
    return TestClient(app, headers={"Authorization": "Bearer test-token"}), brain


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
    client.post(f"/sessions/{session['id']}/context",json={'notes':[{'title':'Update','content':'The refunds migration is Tuesday.'}]})

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


def test_google_oauth_and_context_import(tmp_path):
    requester = FakeProviderRequester()
    settings = Settings(database_path=tmp_path / "oauth.db", backend_api_token="test-token",
        oauth_encryption_key="a-secure-development-key-that-is-long-enough",
        google_client_id="google-client", google_client_secret="google-secret")
    app = create_app(settings=settings, brain=FakeBrain(), voice=FakeVoice(), provider_requester=requester)
    client = TestClient(app, headers={"Authorization":"Bearer test-token"})
    assert client.get("/integrations").json()[0]["configured"]
    started = client.post("/integrations/google/authorize")
    query = parse_qs(urlparse(started.json()["authorization_url"]).query)
    assert query["client_id"] == ["google-client"]
    assert query["code_challenge_method"] == ["S256"]
    connected = client.get("/integrations/google/callback", params={"code":"temporary-code", "state":query["state"][0]})
    assert connected.status_code == 200
    assert "access_token" not in connected.text
    assert b"google-private-token" not in (tmp_path / "oauth.db").read_bytes()
    session_id = client.post("/sessions", json={"title":"Import", "owner_name":"Aloy"}).json()["id"]
    imported = client.post(f"/sessions/{session_id}/context/import", json={"provider":"google", "resource_type":"calendar_event", "resource_id":"event-1"})
    assert imported.status_code == 201
    assert "Ship on Tuesday" in imported.json()[0]["content"]
    assert requester.last_headers == {"Authorization":"Bearer google-private-token"}


def test_private_coach_suggests_what_owner_can_say(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post(
        "/sessions",
        json={"title": "Coach demo", "owner_name": "Muste"},
    ).json()["id"]
    client.post(f'/sessions/{session_id}/context',json={'notes':[{'title':'Refunds','content':'The refunds migration is Tuesday.'}]})
    response = client.post(
        f"/sessions/{session_id}/coach",
        json={
            "latest_message": "When can refunds ship?",
            "objective": "Be concise and avoid overpromising",
        },
    )
    assert response.status_code == 200
    assert response.json()["suggestion"].startswith("The refunds migration")
