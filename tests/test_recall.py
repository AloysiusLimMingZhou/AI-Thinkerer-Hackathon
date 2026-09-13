import asyncio
import base64
import hmac
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, WebSocketDisconnect

from meeting_agent.api import create_app
from meeting_agent.config import Settings
from meeting_agent.recall import RecallError, verify_webhook
from test_api import FakeBrain, FakeVoice

SECRET = "whsec_" + base64.b64encode(b"unit-test-secret-only").decode()
BOT_ID = str(uuid4())
CAL_ID = str(uuid4())
EVENT_ID = str(uuid4())


def test_separate_media_origin_preserves_stable_webhook(tmp_path):
    client, service, _ = make_backend(tmp_path)
    sid = session(client)
    service.settings = replace(
        service.settings, recall_media_base_url="https://media.example.com"
    )
    service.require_ready()
    config = service.bot_config(
        service.repository.get_session(sid), None, int(time.time() + 3600)
    )
    assert config["output_media"]["camera"]["config"]["url"].startswith(
        "https://media.example.com/recall/media/"
    )
    assert (
        config["recording_config"]["realtime_endpoints"][0]["url"]
        == "https://backend.example.com/webhooks/recall"
    )


def make_backend(tmp_path, handler=None):
    settings = Settings(
        database_path=tmp_path / "test.db",
        backend_api_token="test-admin",
        openai_api_key="test-openai",
        elevenlabs_api_key="test-elevenlabs",
        recall_api_key="test-recall",
        recall_webhook_verification_secret=SECRET,
        public_api_base_url="https://backend.example.com",
    )
    requests = []

    def transport(request):
        requests.append(request)
        if handler:
            return handler(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": BOT_ID})
        return httpx.Response(
            200,
            json={
                "id": BOT_ID,
                "status_changes": [
                    {"code": "in_call_recording", "created_at": "2026-09-13T00:00:00Z"}
                ],
            },
        )

    app = create_app(
        settings=settings,
        brain=FakeBrain(),
        voice=FakeVoice(),
        recall_transport=httpx.MockTransport(transport),
    )
    client = TestClient(app, headers={"Authorization": "Bearer test-admin"})
    return client, app.state.recall, requests


def session(client):
    result = client.post(
        "/sessions",
        json={
            "title": "Demo",
            "owner_name": "Aloy",
            "agent_name": "Alloy",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
        },
    )
    assert result.status_code == 201
    return result.json()["id"]


def launch(client, service, sid):
    response = client.post(
        f"/sessions/{sid}/bot",
        json={"idempotency_key": "test-launch-" + sid, "consent_confirmed": True},
    )
    assert response.status_code == 202, response.text
    asyncio.run(service.run_once())
    return response.json()


def signed(client, payload, delivery="test-delivery"):
    raw = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    signature = base64.b64encode(
        hmac.digest(
            b"unit-test-secret-only",
            delivery.encode() + b"." + stamp.encode() + b"." + raw,
            "sha256",
        )
    ).decode()
    return client.post(
        "/webhooks/recall",
        content=raw,
        headers={
            "webhook-id": delivery,
            "webhook-timestamp": stamp,
            "webhook-signature": "v1," + signature,
            "Content-Type": "application/json",
        },
    )


def transcript():
    return {
        "event": "transcript.data",
        "data": {
            "bot": {"id": BOT_ID},
            "data": {
                "participant": {"name": "Jamie"},
                "words": [
                    {
                        "text": "Alloy, when is the refunds migration?",
                        "start_timestamp": {"relative": 1},
                    }
                ],
            },
        },
    }


def test_authentication_and_readiness(tmp_path):
    client, service, _ = make_backend(tmp_path)
    assert (
        client.get("/sessions", headers={"Authorization": "Bearer wrong"}).status_code
        == 401
    )
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200
    assert client.get("/recall/status").json()["missing"] == []
    sid = session(client)
    assert (
        client.post(
            f"/sessions/{sid}/bot", json={"idempotency_key": "12345678"}
        ).status_code
        == 422
    )
    assert client.get(f"/recall/media/{sid}?token=wrong").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/sessions/{sid}/stream", headers={"Authorization": "Bearer wrong"}
        ):
            pass


def test_launch_is_durable_and_idempotent(tmp_path):
    client, service, requests = make_backend(tmp_path)
    sid = session(client)
    launch(client, service, sid)
    launch(client, service, sid)
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert "output_media" in body and "automatic_audio_output" not in body
    assert body["recording_config"]["realtime_endpoints"][0]["events"] == [
        "transcript.data"
    ]
    assert body["bot_name"] == "Alloy (AI delegate)"
    assert client.get(f"/sessions/{sid}/bot").json()["bot_id"] == BOT_ID
    assert (
        client.post(
            f"/sessions/{sid}/bot",
            json={"idempotency_key": "different-key", "consent_confirmed": True},
        ).status_code
        == 409
    )


def test_signed_transcript_to_voice_and_duplicate_delivery(tmp_path):
    client, service, _ = make_backend(tmp_path)
    sid = session(client)
    launch(client, service, sid)
    response = signed(client, transcript())
    assert response.status_code == 202
    assert signed(client, transcript()).json()["duplicate"]
    asyncio.run(service.run_once())
    # Different delivery ID, identical utterance: no duplicate transcript/TTS.
    signed(client, transcript(), "another-delivery")
    asyncio.run(service.run_once())
    assert len(client.get(f"/sessions/{sid}/transcript").json()) == 1
    bot = service.store.bot(sid)
    token = service.media_token(sid, bot["media_expires"])
    path = f"/recall/media/{sid}"
    assert client.get(path, params={"token": token}).status_code == 200
    item = client.get(path + "/next", params={"token": token}).json()
    assert client.get(path + "/next", params={"token": token}).status_code == 204
    assert (
        client.get(path + "/audio/" + item["id"], params={"token": token}).content
        == b"fake-mp3"
    )
    assert (
        client.post(
            path + "/audio/" + item["id"] + "/played", params={"token": token}
        ).status_code
        == 200
    )
    assert (
        client.get(path + "/audio/" + item["id"], params={"token": token}).status_code
        == 404
    )


def test_bad_signature_never_stored(tmp_path):
    client, service, _ = make_backend(tmp_path)
    assert client.post("/webhooks/recall", json=transcript()).status_code == 401
    assert service.store.all("SELECT * FROM recall_jobs") == []
    with pytest.raises(HTTPException):
        verify_webhook(
            b"{}",
            {
                "webhook-id": "x",
                "webhook-timestamp": "1",
                "webhook-signature": "v1,bad",
            },
            SECRET,
        )


def test_rate_limit_persists_retry_after(tmp_path):
    client, service, requests = make_backend(
        tmp_path, lambda req: httpx.Response(429, headers={"Retry-After": "90"})
    )
    sid = session(client)
    launch(client, service, sid)
    job = service.store.one("SELECT * FROM recall_jobs")
    assert job["state"] == "queued"
    assert job["next_at"] >= time.time() + 88
    assert not asyncio.run(service.run_once())
    assert len(requests) == 1


def test_ambiguous_create_is_not_retried(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("possibly created", request=request)

    client, service, requests = make_backend(tmp_path, timeout)
    sid = session(client)
    launch(client, service, sid)
    assert service.store.bot(sid)["state"] == "needs_attention"
    assert (
        service.store.one("SELECT state FROM recall_jobs")["state"] == "needs_attention"
    )
    launch(client, service, sid)
    assert len(requests) == 1


def test_interrupted_worker_does_not_repeat_audio(tmp_path):
    client, service, _ = make_backend(tmp_path)
    sid = session(client)
    launch(client, service, sid)
    service.store.enqueue("interrupted", transcript())
    service.store.claim_job()
    service.store.add_audio(sid, "Hi", b"audio")
    service.store.claim_audio(sid)
    service.store.recover()
    assert (
        service.store.one("SELECT state FROM recall_jobs WHERE id='interrupted'")[
            "state"
        ]
        == "needs_attention"
    )
    assert service.store.claim_audio(sid) is None


def test_calendar_opt_in_sync_reschedule_disable(tmp_path):
    now = datetime.now(UTC)
    event = {
        "id": EVENT_ID,
        "calendar_id": CAL_ID,
        "start_time": (now + timedelta(hours=2)).isoformat(),
        "end_time": (now + timedelta(hours=3)).isoformat(),
        "is_deleted": False,
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "raw": {"summary": "Standup"},
    }

    def handler(request):
        if request.url.path == f"/api/v2/calendars/{CAL_ID}/":
            return httpx.Response(
                200,
                json={
                    "id": CAL_ID,
                    "status": "connected",
                    "platform_email": "demo@example.com",
                },
            )
        if request.url.path == "/api/v2/calendar-events/":
            return httpx.Response(200, json={"results": [event], "next": None})
        if request.method == "DELETE":
            return httpx.Response(204)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                **event,
                "bots": [
                    {"bot_id": BOT_ID, "deduplication_key": body["deduplication_key"]}
                ],
            },
        )

    client, service, requests = make_backend(tmp_path, handler)
    sid = session(client)
    client.post(
        f"/sessions/{sid}/context",
        json={"notes": [{"title": "Context", "content": "Ship Tuesday"}]},
    )
    assert (
        client.post(
            "/recall/calendars",
            json={"calendar_id": CAL_ID, "template_session_id": sid},
        ).status_code
        == 201
    )
    asyncio.run(service.run_once())
    assert not [r for r in requests if r.method == "POST"]
    client.patch(
        f"/recall/calendars/{CAL_ID}",
        json={"auto_join": True, "consent_confirmed": True},
    )
    asyncio.run(service.run_once())
    mapped = service.store.one(
        "SELECT * FROM recall_calendar_events WHERE id=?", (EVENT_ID,)
    )
    assert mapped["state"] == "scheduled"
    assert (
        service.repository.get_context(mapped["session_id"])[0].content
        == "Ship Tuesday"
    )
    assert len([r for r in requests if r.method == "POST"]) == 1
    asyncio.run(service.sync_calendar(CAL_ID))
    assert len([r for r in requests if r.method == "POST"]) == 1
    event["start_time"] = (now + timedelta(hours=4)).isoformat()
    event["end_time"] = (now + timedelta(hours=5)).isoformat()
    asyncio.run(service.sync_calendar(CAL_ID))
    assert len([r for r in requests if r.method == "POST"]) == 2
    client.patch(
        f"/recall/calendars/{CAL_ID}",
        json={"auto_join": False, "consent_confirmed": True},
    )
    asyncio.run(service.run_once())
    assert len([r for r in requests if r.method == "DELETE"]) == 1


def test_pagination_cannot_leak_recall_key(tmp_path):
    client, service, requests = make_backend(tmp_path)
    with pytest.raises(RecallError):
        asyncio.run(service.client.request("GET", "https://attacker.example/api"))
    assert not requests


def test_calendar_callback_rejects_malformed_and_not_configured(tmp_path):
    client, _, _ = make_backend(tmp_path)
    assert (
        client.get("/recall/calendar/callback?state=x&code=x&error=y").status_code
        == 400
    )
    assert (
        client.get("/recall/calendar/callback?state=x&code=x&code=y").status_code == 400
    )
    assert client.get("/recall/calendar/callback?state=x&code=x").status_code == 503


def test_final_transcript_download_and_minutes(tmp_path):
    transcript_id = str(uuid4())
    final = [
        {
            "participant": {"name": "Jamie"},
            "words": [
                {
                    "text": "Approved Tuesday.",
                    "start_timestamp": {
                        "absolute": "2026-09-13T12:01:00Z",
                        "relative": 1,
                    },
                }
            ],
        }
    ]

    def handler(request):
        if request.url.host == "assets.s3.amazonaws.com":
            assert "authorization" not in request.headers
            return httpx.Response(200, json=final)
        if request.url.path == f"/api/v1/transcript/{transcript_id}/":
            return httpx.Response(
                200,
                json={
                    "id": transcript_id,
                    "created_at": "2026-09-13T12:00:00Z",
                    "data": {
                        "download_url": "https://assets.s3.amazonaws.com/transcript?signature=private"
                    },
                },
            )
        return httpx.Response(201, json={"id": BOT_ID})

    client, service, requests = make_backend(tmp_path, handler)
    sid = session(client)
    launch(client, service, sid)
    payload = {
        "event": "transcript.done",
        "data": {
            "bot": {"id": BOT_ID},
            "transcript": {"id": transcript_id},
            "recording": {"id": str(uuid4())},
        },
    }
    assert signed(client, payload).status_code == 202
    asyncio.run(service.run_once())
    assert (
        client.get(f"/sessions/{sid}/transcript").json()[0]["text"]
        == "Approved Tuesday."
    )
    assert client.get(f"/sessions/{sid}/minutes").status_code == 200
    signed(client, payload, "duplicate-final")
    asyncio.run(service.run_once())
    assert len([r for r in requests if r.url.host == "assets.s3.amazonaws.com"]) == 1


def test_malformed_meeting_url_and_naive_schedule_rejected(tmp_path):
    client, service, requests = make_backend(tmp_path)
    sid = session(client)
    service.store.execute(
        "UPDATE sessions SET meeting_url=? WHERE id=?",
        ("https://meet.google.com:bad/abc-defg-hij", sid),
    )
    response = client.post(
        f"/sessions/{sid}/bot",
        json={"idempotency_key": "bad-link-key", "consent_confirmed": True},
    )
    assert response.status_code == 422
    response = client.post(
        f"/sessions/{sid}/bot",
        json={
            "idempotency_key": "bad-link-key",
            "consent_confirmed": True,
            "join_at": "2026-10-01T09:00:00",
        },
    )
    assert response.status_code == 422
    assert not requests


def test_stale_transcript_is_saved_but_not_spoken(tmp_path):
    client, service, _ = make_backend(tmp_path)
    sid = session(client)
    launch(client, service, sid)
    payload = transcript()
    payload["data"]["alloy_received_at"] = time.time() - 120
    service.store.enqueue("stale", payload)
    asyncio.run(service.run_once())
    assert len(service.repository.get_transcript(sid)) == 1
    assert not service.store.all("SELECT * FROM recall_audio")


def test_real_lifespan_worker_consumes_launch(tmp_path):
    client, service, _ = make_backend(tmp_path)
    with client:
        sid = session(client)
        response = client.post(
            f"/sessions/{sid}/bot",
            json={"idempotency_key": "lifespan-test", "consent_confirmed": True},
        )
        assert response.status_code == 202
        for _ in range(30):
            if service.store.bot(sid)["bot_id"]:
                break
            time.sleep(0.02)
        assert service.store.bot(sid)["bot_id"] == BOT_ID


@pytest.mark.parametrize("same_speaker", [True, False])
def test_split_wake_phrase_followup(tmp_path, same_speaker):
    client, service, _ = make_backend(tmp_path)
    sid = session(client)
    launch(client, service, sid)
    first = transcript()
    first["data"]["data"]["words"][0]["text"] = "Hello Alloy"
    signed(client, first, "wake-chunk")
    asyncio.run(service.run_once())
    assert not service.store.all("SELECT id FROM recall_audio")
    followup = transcript()
    followup["data"]["data"]["words"][0]["text"] = "When is the demo launch?"
    if not same_speaker:
        followup["data"]["data"]["participant"]["name"] = "Someone else"
    signed(client, followup, "question-chunk")
    asyncio.run(service.run_once())
    assert bool(service.store.all("SELECT id FROM recall_audio")) is same_speaker
