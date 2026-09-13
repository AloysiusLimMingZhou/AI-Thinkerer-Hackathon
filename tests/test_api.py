from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
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


class FakeProviderRequester:
    def __init__(self) -> None:
        self.last_headers: dict[str, str] = {}

    async def post(
        self,
        url: str,
        *,
        data: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> httpx.Response:
        assert url == "https://slack.com/api/oauth.v2.access"
        assert auth == ("slack-client", "slack-secret")
        assert data and data["code"] == "temporary-code"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "scope": "",
                "team": {"id": "T123", "name": "Hackathon"},
                "authed_user": {
                    "id": "U123",
                    "scope": "channels:read,channels:history",
                    "access_token": "xoxp-private-user-token",
                },
            },
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        assert url == "https://slack.com/api/conversations.history"
        assert params == {"channel": "C123", "limit": 15}
        self.last_headers = headers or {}
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {"ts": "2", "user": "U2", "text": "Ship on Tuesday"},
                    {"ts": "1", "user": "U1", "text": "Refunds are ready"},
                ],
            },
        )


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


def test_slack_oauth_and_context_import(tmp_path: Path) -> None:
    requester = FakeProviderRequester()
    settings = Settings(
        backend_api_token="test-token",
        database_path=tmp_path / "oauth.db",
        oauth_encryption_key="a-secure-development-key-that-is-long-enough",
        slack_client_id="slack-client",
        slack_client_secret="slack-secret",
    )
    app = create_app(
        settings=settings,
        brain=FakeBrain(),
        voice=FakeVoice(),
        provider_requester=requester,
    )
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})

    capabilities = client.get("/platforms")
    assert capabilities.status_code == 200
    assert {item["provider"] for item in capabilities.json()} == {
        "google",
        "slack",
        "microsoft",
        "zoom",
    }

    before = client.get("/integrations").json()
    slack_before = next(item for item in before if item["provider"] == "slack")
    assert slack_before["configured"] is True
    assert slack_before["connected"] is False

    started = client.post("/integrations/slack/authorize")
    assert started.status_code == 200
    authorization_url = started.json()["authorization_url"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["client_id"] == ["slack-client"]
    assert "channels:history" in query["user_scope"][0]

    connected = client.get(
        "/integrations/slack/callback",
        params={"code": "temporary-code", "state": query["state"][0]},
    )
    assert connected.status_code == 200
    assert connected.json()["account_label"] == "Hackathon"
    assert "access_token" not in connected.text
    assert "xoxp-private-user-token" not in (tmp_path / "oauth.db").read_bytes().decode(
        errors="ignore"
    )

    session_id = client.post(
        "/sessions",
        json={"title": "Import demo", "owner_name": "Muste"},
    ).json()["id"]
    imported = client.post(
        f"/sessions/{session_id}/context/import",
        json={
            "provider": "slack",
            "resource_type": "channel",
            "resource_id": "C123",
        },
    )
    assert imported.status_code == 201
    assert "Refunds are ready\n[2] U2: Ship on Tuesday" in imported.json()[0]["content"]
    assert requester.last_headers == {"Authorization": "Bearer xoxp-private-user-token"}


def test_private_coach_suggests_what_owner_can_say(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    session_id = client.post(
        "/sessions",
        json={"title": "Coach demo", "owner_name": "Muste"},
    ).json()["id"]
    response = client.post(
        f"/sessions/{session_id}/coach",
        json={
            "latest_message": "When can refunds ship?",
            "objective": "Be concise and avoid overpromising",
        },
    )
    assert response.status_code == 200
    assert response.json()["suggestion"].startswith("The refunds migration")
