"""Recall Tokyo adapter: dispatch, signed ingestion, durable work, and audio outbox."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlparse
from uuid import UUID

import httpx
from fastapi import HTTPException

from .config import Settings
from .models import ContextNoteCreate, SessionCreate, TranscriptEntry, UtteranceCreate
from .recall_store import RecallStore
from .services import citations_for, retrieve_context, should_answer

logger = logging.getLogger(__name__)
TERMINAL = {"done", "fatal", "call_ended", "deleted"}


class RecallError(Exception):
    def __init__(self, message, *, retry_after=None, ambiguous=False):
        super().__init__(message)
        self.retry_after = retry_after
        self.ambiguous = ambiguous


def public_url(value: str):
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("PUBLIC_API_BASE_URL must be a stable public HTTPS URL")
    if (
        host == "localhost"
        or host.endswith((".local", ".localhost"))
        or "." not in host
    ):
        raise ValueError("A public hostname is required")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return value.rstrip("/")
    raise ValueError("Use a public hostname, not an IP address")


def validate_meeting_url(value):
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        raise HTTPException(422, "Invalid meeting URL") from None
    host = parsed.hostname or ""
    supported = ("meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not any(host == h or host.endswith("." + h) for h in supported)
    ):
        raise HTTPException(422, "Use a Google Meet, Zoom, or Teams HTTPS meeting link")
    if not parsed.path or parsed.path == "/":
        raise HTTPException(
            422, "A meeting link, not the platform home page, is required"
        )


def verify_webhook(raw: bytes, headers, secret: str | None, now=None):
    if not secret:
        raise HTTPException(503, "Recall webhook secret is not configured")
    try:
        identifier = headers.get("webhook-id") or headers["svix-id"]
        stamp = headers.get("webhook-timestamp") or headers["svix-timestamp"]
        signatures = headers.get("webhook-signature") or headers["svix-signature"]
        if abs((time.time() if now is None else now) - int(stamp)) > 300:
            raise ValueError()
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        expected = base64.b64encode(
            hmac.digest(
                key, identifier.encode() + b"." + stamp.encode() + b"." + raw, "sha256"
            )
        ).decode()
        if not any(
            hmac.compare_digest(part, "v1," + expected) for part in signatures.split()
        ):
            raise ValueError()
        return identifier
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid Recall signature") from None


class RecallClient:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        if settings.recall_region != "ap-northeast-1":
            raise ValueError("This integration is pinned to Alloy Bot in Tokyo")
        self.base_url = "https://ap-northeast-1.recall.ai"
        self.transport = transport

    async def request(self, method, path, *, body=None, params=None):
        if not self.settings.recall_api_key:
            raise RecallError("RECALL_API_KEY is missing")
        url = path if path.startswith("https://") else self.base_url + path
        if (
            urlparse(url).netloc != urlparse(self.base_url).netloc
            or urlparse(url).scheme != "https"
        ):
            raise RecallError(
                "Rejected Recall pagination outside the configured region"
            )
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    url,
                    json=body,
                    params=params,
                    headers={"Authorization": self.settings.recall_api_key},
                )
        except httpx.HTTPError:
            raise RecallError(
                "Recall network failure; reconcile writes before retrying",
                ambiguous=method not in ("GET", "DELETE"),
            ) from None
        if response.status_code in (429, 503, 507, 409):
            retry = {429: 10, 503: 10, 507: 30, 409: 5}[response.status_code]
            raw_retry = response.headers.get("Retry-After")
            if raw_retry:
                try:
                    retry = max(retry, float(raw_retry))
                except ValueError:
                    try:
                        retry = max(
                            retry,
                            parsedate_to_datetime(raw_retry).timestamp() - time.time(),
                        )
                    except (ValueError, TypeError):
                        pass
            raise RecallError(
                f"Recall temporarily unavailable (HTTP {response.status_code})",
                retry_after=retry + random.random() * 2,
            )
        if response.is_error:
            raise RecallError(
                f"Recall request rejected (HTTP {response.status_code})",
                ambiguous=response.status_code >= 500 and method == "POST",
            )
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError:
            raise RecallError(
                "Recall returned an invalid response", ambiguous=method == "POST"
            ) from None


class RecallService:
    def __init__(self, settings, repository, brain, voice, transport=None):
        self.settings, self.repository, self.brain, self.voice = (
            settings,
            repository,
            brain,
            voice,
        )
        self.store = RecallStore(repository)
        self.client = RecallClient(settings, transport)

    def missing(self):
        values = {
            "RECALL_API_KEY": self.settings.recall_api_key,
            "RECALL_WEBHOOK_VERIFICATION_SECRET": self.settings.recall_webhook_verification_secret,
            "PUBLIC_API_BASE_URL": self.settings.public_api_base_url,
            "BACKEND_API_TOKEN": self.settings.backend_api_token,
            "OPENAI_API_KEY": self.settings.openai_api_key,
            "ELEVENLABS_API_KEY": self.settings.elevenlabs_api_key,
        }
        return [key for key, value in values.items() if not value]

    def require_ready(self):
        missing = self.missing()
        if missing:
            raise HTTPException(503, {"missing": missing})
        try:
            public_url(self.settings.public_api_base_url)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from None

    def media_token(self, session_id, expires):
        return hmac.new(
            self.settings.backend_api_token.encode(),
            f"media:{session_id}:{expires}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def authorize_media(self, session_id, token):
        bot = self.store.bot(session_id)
        if (
            not bot
            or not self.settings.backend_api_token
            or bot["media_expires"] < time.time()
            or bot["state"] in TERMINAL
            or not hmac.compare_digest(
                token, self.media_token(session_id, bot["media_expires"])
            )
        ):
            raise HTTPException(401, "Invalid or expired media session")
        return bot

    def bot_config(self, session, join_at, expires):
        url = self.settings.public_api_base_url
        token = self.media_token(session.id, expires)
        config = {
            "meeting_url": session.meeting_url,
            "bot_name": f"{session.agent_name} (AI delegate)",
            "metadata": {"alloy_session_id": session.id},
            "chat": {
                "on_bot_join": {
                    "send_to": "everyone",
                    "message": "I am an AI delegate. This meeting is transcribed for notes and AI responses.",
                }
            },
            "recording_config": {
                "transcript": {
                    "provider": {
                        "recallai_streaming": {
                            "mode": "prioritize_low_latency",
                            "language_code": "en",
                        }
                    },
                    "diarization": {"use_separate_streams_when_available": True},
                },
                "include_bot_in_recording": {"audio": False},
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": url + "/webhooks/recall",
                        "events": ["transcript.data"],
                    }
                ],
            },
            "output_media": {
                "camera": {
                    "kind": "webpage",
                    "config": {
                        "url": f"{url}/recall/media/{session.id}?{urlencode({'token': token})}"
                    },
                }
            },
        }
        if join_at:
            config["join_at"] = join_at
        return config

    def reserve(self, session_id, key, join_at):
        expires = int(
            (datetime.fromisoformat(join_at).timestamp() if join_at else time.time())
            + 8 * 3600
        )
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM recall_bots WHERE session_id=? OR launch_key=?",
                (session_id, key),
            ).fetchone()
            if existing:
                if (
                    existing["session_id"] != session_id
                    or existing["launch_key"] != key
                    or existing["join_at"] != join_at
                ):
                    raise HTTPException(
                        409,
                        "A bot or idempotency key already exists; use a new meeting session",
                    )
                return dict(existing), False
            db.execute(
                "INSERT INTO recall_bots(session_id,launch_key,state,join_at,media_expires) VALUES(?,?,'queued',?,?)",
                (session_id, key, join_at, expires),
            )
        return self.store.bot(session_id), True

    def launch(self, session, key, join_at):
        self.require_ready()
        validate_meeting_url(session.meeting_url or "")
        row, created = self.reserve(session.id, key, join_at)
        if created:
            self.store.enqueue(
                "launch:" + session.id,
                {"event": "internal.launch", "session_id": session.id},
            )
        return row

    def final_transcript(self, session_id):
        entries = []
        artifacts = self.store.all(
            "SELECT * FROM recall_transcripts WHERE session_id=? ORDER BY created_at",
            (session_id,),
        )
        for artifact in artifacts:
            for index, utterance in enumerate(json.loads(artifact["body"])):
                words = utterance.get("words", [])
                if not words:
                    continue
                stamp = (
                    words[0].get("start_timestamp", {}).get("absolute")
                    or artifact["created_at"]
                )
                text = " ".join(word["text"] for word in words).strip()
                if text:
                    entries.append(
                        TranscriptEntry(
                            id=artifact["id"] + ":" + str(index),
                            speaker=utterance.get("participant", {}).get("name")
                            or "Unknown participant",
                            text=text,
                            is_final=True,
                            spoken_at=stamp,
                        )
                    )
        return entries

    async def capture_final_transcript(self, session_id, data):
        transcript_id = str(UUID(data["transcript"]["id"]))
        if self.store.one(
            "SELECT id FROM recall_transcripts WHERE id=?", (transcript_id,)
        ):
            return
        artifact = await self.client.request(
            "GET", f"/api/v1/transcript/{transcript_id}/"
        )
        url = artifact.get("data", {}).get("download_url")
        host = urlparse(url or "").hostname or ""
        # Signed storage URLs get no Recall Authorization header and no redirects.
        if urlparse(url or "").scheme != "https" or not any(
            host == domain or host.endswith("." + domain)
            for domain in ("amazonaws.com", "cloudfront.net", "recall.ai")
        ):
            raise RecallError(
                "Unexpected transcript download host; review before fetching"
            )
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.client.transport, follow_redirects=False
            ) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise RecallError(
                            "Transcript download unavailable", retry_after=15
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 20_000_000:
                            raise RecallError(
                                "Transcript exceeds the 20 MB demo storage limit"
                            )
            body = json.loads(raw)
            if not isinstance(body, list):
                raise RecallError("Unexpected transcript artifact format")
            # Validate the actual data before persisting it for downstream readers.
            for utterance in body:
                if (
                    not isinstance(utterance, dict)
                    or not isinstance(utterance.get("words"), list)
                    or not isinstance(utterance.get("participant"), dict)
                ):
                    raise RecallError("Invalid transcript artifact entry")
        except httpx.HTTPError:
            raise RecallError(
                "Transcript download network failure", retry_after=15
            ) from None
        self.store.execute(
            "INSERT OR IGNORE INTO recall_transcripts(id,session_id,recording_id,created_at,body) VALUES(?,?,?,?,?)",
            (
                transcript_id,
                session_id,
                data.get("recording", {}).get("id"),
                artifact.get("created_at") or datetime.now(UTC).isoformat(),
                json.dumps(body),
            ),
        )
        self.repository.record_event(
            session_id,
            "transcript.saved",
            {"transcript_id": transcript_id, "utterances": len(body)},
        )

    async def create_bot(self, session_id):
        bot = self.store.bot(session_id)
        session = self.repository.get_session(session_id)
        if bot["bot_id"]:
            return
        self.store.execute(
            "UPDATE recall_bots SET state='creating' WHERE session_id=?", (session_id,)
        )
        try:
            result = await self.client.request(
                "POST",
                "/api/v1/bot/",
                body=self.bot_config(session, bot["join_at"], bot["media_expires"]),
            )
            bot_id = str(UUID(result["id"]))
        except RecallError as exc:
            self.store.execute(
                "UPDATE recall_bots SET state=?,error=? WHERE session_id=?",
                (
                    "needs_attention"
                    if exc.ambiguous
                    else "retrying"
                    if exc.retry_after
                    else "failed",
                    str(exc),
                    session_id,
                ),
            )
            raise
        self.store.execute(
            "UPDATE recall_bots SET bot_id=?,state='scheduled',error=NULL WHERE session_id=?",
            (bot_id, session_id),
        )
        self.repository.record_event(session_id, "bot.scheduled", {"bot_id": bot_id})

    async def process(self, job):
        payload = json.loads(job["body"])
        event = payload.get("event", "")
        if event == "internal.launch":
            await self.create_bot(payload["session_id"])
            return
        data = payload.get("data", {})
        if event.startswith("calendar.") or event == "internal.calendar_sync":
            calendar_id = data.get("calendar_id")
            if self.store.one(
                "SELECT id FROM recall_calendars WHERE id=?", (calendar_id,)
            ):
                await self.sync_calendar(calendar_id)
            return
        bot_id = data.get("bot", {}).get("id")
        bot = self.store.one("SELECT * FROM recall_bots WHERE bot_id=?", (bot_id,))
        if not bot:
            raise RecallError(
                "Webhook bot is not mapped locally; reconcile dispatch", retry_after=5
            )
        session_id = bot["session_id"]
        if event == "transcript.data":
            await self.process_transcript(job["id"], session_id, data)
        elif event.startswith("bot."):
            # Status is fetched once per lifecycle notification, not periodically polled.
            detail = await self.client.request("GET", f"/api/v1/bot/{bot_id}/")
            history = detail.get("status_changes", [])
            if history:
                latest = max(history, key=lambda item: item.get("created_at", ""))
                state = latest["code"]
                self.store.execute(
                    "UPDATE recall_bots SET state=?,last_status_at=? WHERE session_id=?",
                    (state, latest.get("created_at"), session_id),
                )
                status = (
                    "ended"
                    if state in TERMINAL
                    else "active"
                    if state.startswith("in_call")
                    else "created"
                )
                self.store.execute(
                    "UPDATE sessions SET status=? WHERE id=?", (status, session_id)
                )
                self.repository.record_event(
                    session_id,
                    "bot.status",
                    {"state": state, "sub_code": latest.get("sub_code")},
                )
                if state in TERMINAL:
                    self.store.execute(
                        "UPDATE recall_audio SET state='expired',audio=X'' WHERE session_id=? AND state IN ('queued','playing')",
                        (session_id,),
                    )
        else:
            self.repository.record_event(
                session_id,
                event,
                {
                    "recording_id": data.get("recording", {}).get("id"),
                    "transcript_id": data.get("transcript", {}).get("id"),
                    "status": data.get("data", {}),
                },
            )
            if event == "transcript.done":
                transcript_id = data.get("transcript", {}).get("id")
                if self.store.one(
                    "SELECT id FROM recall_transcripts WHERE id=?", (transcript_id,)
                ) and self.repository.get_minutes(session_id):
                    return
                await self.capture_final_transcript(session_id, data)
                entries = self.final_transcript(session_id)
                if not entries:
                    return
                session = self.repository.get_session(session_id)
                content = await self.brain.generate_minutes(
                    session,
                    entries,
                    self.repository.get_context(session_id),
                    self.repository.get_qa_log(session_id),
                )
                minutes = self.repository.save_minutes(session_id, content)
                self.repository.record_event(
                    session_id, "minutes.generated", minutes.model_dump(mode="json")
                )

    async def process_transcript(self, job_id, session_id, data):
        utterance = data.get("data", {})
        text = " ".join(word["text"] for word in utterance.get("words", [])).strip()
        if not text:
            return
        session = self.repository.get_session(session_id)
        speaker = utterance.get("participant", {}).get("name") or "Unknown participant"
        if speaker.casefold() in (
            session.agent_name.casefold(),
            f"{session.agent_name} (AI delegate)".casefold(),
        ):
            return
        # The content hash survives redelivery with a different webhook identifier.
        entry_id = hashlib.sha256(
            json.dumps(
                {"session": session_id, "utterance": utterance}, sort_keys=True
            ).encode()
        ).hexdigest()
        item = UtteranceCreate(speaker=speaker[:100], text=text)
        inserted = self.store.execute(
            "INSERT OR IGNORE INTO transcript(id,session_id,speaker,text,is_final,spoken_at) VALUES(?,?,?,?,1,?)",
            (entry_id, session_id, item.speaker, text, item.spoken_at.isoformat()),
        )
        if not inserted:
            return
        self.repository.record_event(
            session_id,
            "transcript.utterance",
            {"id": entry_id, **item.model_dump(mode="json")},
        )
        approved, reason = should_answer(
            text,
            agent_name=session.agent_name,
            owner_name=session.owner_name,
            force_answer=False,
        )
        bot = self.store.bot(session_id)
        # Don't answer historical transcripts, the bot's own playback, or queued backlogs.
        stale = time.time() - float(data.get("alloy_received_at", time.time())) > 30
        busy = self.store.one(
            "SELECT id FROM recall_audio WHERE session_id=? AND expires>? AND state IN ('queued','playing')",
            (session_id, time.time()),
        )
        if not approved or stale or busy or bot["state"] in TERMINAL:
            return
        notes = retrieve_context(text, self.repository.get_context(session_id))
        answer = await self.brain.answer(
            session, text, self.repository.get_transcript(session_id), notes
        )
        citations = citations_for(notes)
        self.repository.add_qa(session_id, text, answer, citations)
        self.repository.record_event(
            session_id,
            "agent.decision",
            {
                "action": "answer",
                "reason": reason,
                "answer": answer,
                "citations": [c.model_dump() for c in citations],
            },
        )
        audio = await self.voice.generate(answer)
        # Never speak a stale reply after a long API stall or after meeting end.
        if (
            time.time() - float(data.get("alloy_received_at", time.time())) <= 60
            and self.store.bot(session_id)["state"] not in TERMINAL
        ):
            self.store.add_audio(session_id, answer, audio, job_id)
            self.repository.record_event(session_id, "voice.queued", {"id": job_id})

    async def run_once(self):
        job = self.store.claim_job()
        if not job:
            return False
        try:
            await self.process(job)
        except RecallError as exc:
            retry = (
                exc.retry_after is not None
                and not exc.ambiguous
                and job["attempts"] < 5
            )
            self.store.execute(
                "UPDATE recall_jobs SET state=?,next_at=?,error=? WHERE id=?",
                (
                    "queued" if retry else "needs_attention",
                    time.time() + (exc.retry_after or 0),
                    str(exc),
                    job["id"],
                ),
            )
            payload = json.loads(job["body"])
            if not retry and payload.get("event") == "internal.launch":
                self.store.execute(
                    "UPDATE recall_bots SET state='needs_attention',error=? WHERE session_id=?",
                    (str(exc), payload["session_id"]),
                )
        except Exception as exc:
            # No exception values: provider errors can contain tokens or input text.
            self.store.execute(
                "UPDATE recall_jobs SET state='needs_attention',error=? WHERE id=?",
                (type(exc).__name__, job["id"]),
            )
            logger.warning("Recall job needs attention (%s)", type(exc).__name__)
        else:
            self.store.execute(
                "UPDATE recall_jobs SET state='done',error=NULL WHERE id=?",
                (job["id"],),
            )
        return True

    async def worker(self):
        logger.info("Recall worker region: %s", self.settings.recall_region)
        self.store.recover()
        while True:
            try:
                if not await self.run_once():
                    await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Recall worker unavailable (%s)", type(exc).__name__)
                await asyncio.sleep(1)

    async def sync_calendar(self, calendar_id):
        # Full bounded Recall window avoids losing changes across retries/pagination.
        calendar = self.store.one(
            "SELECT * FROM recall_calendars WHERE id=?", (calendar_id,)
        )
        detail = await self.client.request("GET", f"/api/v2/calendars/{calendar_id}/")
        self.store.execute(
            "UPDATE recall_calendars SET status=? WHERE id=?",
            (detail.get("status", "unknown"), calendar_id),
        )
        if detail.get("status") != "connected":
            return
        path = "/api/v2/calendar-events/"
        params = {"calendar_id": calendar_id}
        while path:
            page = await self.client.request("GET", path, params=params)
            for event in sorted(page.get("results", []), key=lambda e: e["start_time"]):
                await self.sync_event(calendar, event)
            path, params = page.get("next"), None
        self.store.execute(
            "UPDATE recall_calendars SET last_sync=? WHERE id=?",
            (datetime.now(UTC).isoformat(), calendar_id),
        )

    async def sync_event(self, calendar, event):
        calendar = self.store.one(
            "SELECT * FROM recall_calendars WHERE id=?", (calendar["id"],)
        )
        event_id = str(UUID(event["id"]))
        prior = self.store.one(
            "SELECT * FROM recall_calendar_events WHERE id=?", (event_id,)
        )
        self.store.execute(
            "INSERT INTO recall_calendar_events(id,calendar_id,body) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (event_id, calendar["id"], json.dumps(event)),
        )
        start = datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(event["end_time"].replace("Z", "+00:00"))
        if end <= datetime.now(UTC):
            return
        raw = event.get("raw") or {}
        declined = (
            any(
                a.get("self") and a.get("responseStatus") == "declined"
                for a in raw.get("attendees", [])
            )
            or raw.get("responseStatus", {}).get("response") == "declined"
        )
        eligible = bool(
            calendar["auto_join"]
            and calendar["status"] == "connected"
            and event.get("meeting_url")
            and not event.get("is_deleted")
            and not declined
            and raw.get("status") != "cancelled"
            and not raw.get("isCancelled")
            and not (prior and prior["state"] == "excluded")
        )
        if eligible:
            try:
                validate_meeting_url(event["meeting_url"])
            except (HTTPException, ValueError):
                eligible = False
        if not eligible:
            if prior and prior["fingerprint"]:
                await self.client.request(
                    "DELETE", f"/api/v2/calendar-events/{event_id}/bot/"
                )
                self.store.execute(
                    "UPDATE recall_calendar_events SET fingerprint=NULL,state='unscheduled' WHERE id=?",
                    (event_id,),
                )
            return
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    event["meeting_url"],
                    event["start_time"],
                    calendar["template_session_id"],
                ]
            ).encode()
        ).hexdigest()
        if prior and prior["fingerprint"] == fingerprint:
            return
        # Avoid surprise late arrivals to events already in progress.
        if start <= datetime.now(UTC):
            return
        self.require_ready()
        template = self.repository.get_session(calendar["template_session_id"])
        session = (
            self.repository.get_session(prior["session_id"])
            if prior and prior["session_id"]
            else None
        )
        if not session:
            session = self.repository.create_session(
                SessionCreate(
                    title=(
                        raw.get("summary") or raw.get("subject") or "Calendar meeting"
                    )[:200],
                    owner_name=template.owner_name,
                    agent_name=template.agent_name,
                    meeting_url=event["meeting_url"],
                )
            )
            notes = self.repository.get_context(template.id)
            if notes:
                self.repository.add_context(
                    session.id,
                    [
                        ContextNoteCreate(
                            source=n.source, title=n.title, content=n.content
                        )
                        for n in notes
                    ],
                )
            self.store.execute(
                "UPDATE recall_calendar_events SET session_id=? WHERE id=?",
                (session.id, event_id),
            )
            self.reserve(session.id, "calendar:" + event_id, event["start_time"])
        else:
            self.store.execute(
                "UPDATE sessions SET meeting_url=? WHERE id=?",
                (event["meeting_url"], session.id),
            )
            session = self.repository.get_session(session.id)
        expires = int(start.timestamp() + 8 * 3600)
        self.store.execute(
            "UPDATE recall_bots SET join_at=?,media_expires=? WHERE session_id=?",
            (event["start_time"], expires, session.id),
        )
        result = await self.client.request(
            "POST",
            f"/api/v2/calendar-events/{event_id}/bot/",
            body={
                "deduplication_key": "alloy:" + event_id + ":" + fingerprint,
                "bot_config": self.bot_config(session, event["start_time"], expires),
            },
        )
        bots = result.get("bots", [])
        matching = [
            b
            for b in bots
            if b.get("deduplication_key") == "alloy:" + event_id + ":" + fingerprint
        ]
        if not matching:
            raise RecallError(
                "Calendar schedule response has no matching bot; reconcile",
                ambiguous=True,
            )
        bot_id = str(UUID(matching[-1]["bot_id"]))
        self.store.execute(
            "UPDATE recall_bots SET bot_id=?,state='scheduled',error=NULL WHERE session_id=?",
            (bot_id, session.id),
        )
        self.store.execute(
            "UPDATE recall_calendar_events SET fingerprint=?,state='scheduled' WHERE id=?",
            (fingerprint, event_id),
        )
