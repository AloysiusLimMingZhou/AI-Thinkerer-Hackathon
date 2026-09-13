from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import AwareDatetime, BaseModel, Field

from .recall import RecallService, verify_webhook


class LaunchRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    join_at: AwareDatetime | None = None
    consent_confirmed: Literal[True]


class CalendarAttach(BaseModel):
    calendar_id: UUID
    template_session_id: UUID


class CalendarPreference(BaseModel):
    auto_join: bool
    consent_confirmed: Literal[True]


class BotReconcile(BaseModel):
    bot_id: UUID


class SayRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


def router_for(service: RecallService):
    router = APIRouter()
    store, repo = service.store, service.repository

    def session_or_404(session_id):
        session = repo.get_session(str(session_id))
        if not session:
            raise HTTPException(404, "Session not found")
        return session

    def calendar_or_404(calendar_id):
        row = store.one(
            "SELECT * FROM recall_calendars WHERE id=?", (str(calendar_id),)
        )
        if not row:
            raise HTTPException(404, "Calendar not attached")
        return row

    @router.get("/recall/status", tags=["Recall"])
    async def status():
        return {
            "workspace": "Alloy Bot",
            "region": service.settings.recall_region,
            "missing": service.missing(),
            "configured": not service.missing(),
            "calendar_count": len(store.all("SELECT id FROM recall_calendars")),
            "note": "Configuration presence is not live-provider verification.",
        }

    @router.post("/sessions/{session_id}/bot", status_code=202, tags=["Recall"])
    async def launch(session_id: UUID, payload: LaunchRequest):
        if payload.join_at and payload.join_at < datetime.now(UTC) + timedelta(
            minutes=10
        ):
            raise HTTPException(
                422,
                "Schedule at least 10 minutes ahead, or omit join_at for immediate joining",
            )
        if payload.join_at and payload.join_at > datetime.now(UTC) + timedelta(days=28):
            raise HTTPException(422, "Schedule within 28 days")
        session = session_or_404(session_id)
        return service.launch(
            session,
            payload.idempotency_key,
            payload.join_at.isoformat() if payload.join_at else None,
        )

    @router.get("/sessions/{session_id}/bot", tags=["Recall"])
    async def bot_status(session_id: UUID):
        session_or_404(session_id)
        bot = store.bot(str(session_id))
        if not bot:
            raise HTTPException(404, "No bot requested for this session")
        return bot

    @router.post("/sessions/{session_id}/bot/reconcile", tags=["Recall"])
    async def reconcile(session_id: UUID, payload: BotReconcile):
        session_or_404(session_id)
        bot = store.bot(str(session_id))
        if not bot or bot["state"] not in ("needs_attention", "failed", "creating"):
            raise HTTPException(409, "Only an unresolved launch can be reconciled")
        detail = await service.client.request("GET", f"/api/v1/bot/{payload.bot_id}/")
        if detail.get("metadata", {}).get("alloy_session_id") != str(session_id):
            raise HTTPException(409, "Recall bot does not belong to this local session")
        store.execute(
            "UPDATE recall_bots SET bot_id=?,state='scheduled',error=NULL WHERE session_id=?",
            (str(payload.bot_id), str(session_id)),
        )
        store.enqueue(
            "reconcile:" + str(uuid4()),
            {"event": "bot.reconcile", "data": {"bot": {"id": str(payload.bot_id)}}},
        )
        return store.bot(str(session_id))

    @router.post("/sessions/{session_id}/bot/leave", tags=["Recall"])
    async def leave(session_id: UUID):
        bot = store.bot(str(session_id))
        if not bot:
            raise HTTPException(404, "Bot not found")
        if not bot["bot_id"]:
            # A worker might already have claimed it. Only cancel still-queued work.
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    "UPDATE recall_jobs SET state='cancelled' WHERE id=? AND state='queued'",
                    ("launch:" + str(session_id),),
                ).rowcount
                if not changed:
                    raise HTTPException(
                        409, "Launch is in progress or unresolved; reconcile first"
                    )
                db.execute(
                    "UPDATE recall_bots SET state='deleted' WHERE session_id=?",
                    (str(session_id),),
                )
            return {"state": "deleted"}
        calendar_event = store.one(
            "SELECT id,calendar_id FROM recall_calendar_events WHERE session_id=?",
            (str(session_id),),
        )
        if calendar_event:
            await service.client.request(
                "DELETE", f"/api/v2/calendar-events/{calendar_event['id']}/bot/"
            )
            store.execute(
                "UPDATE recall_calendar_events SET state='excluded',fingerprint=NULL WHERE id=?",
                (calendar_event["id"],),
            )
            if bot["state"].startswith("in_call"):
                await service.client.request(
                    "POST", f"/api/v1/bot/{bot['bot_id']}/leave_call/"
                )
        elif bot["join_at"] and datetime.fromisoformat(bot["join_at"]) > datetime.now(
            UTC
        ) + timedelta(minutes=10):
            await service.client.request("DELETE", f"/api/v1/bot/{bot['bot_id']}/")
        else:
            await service.client.request(
                "POST", f"/api/v1/bot/{bot['bot_id']}/leave_call/"
            )
        store.execute(
            "UPDATE recall_bots SET state='call_ended' WHERE session_id=?",
            (str(session_id),),
        )
        store.execute(
            "UPDATE sessions SET status='ended' WHERE id=?", (str(session_id),)
        )
        return {"state": "leave_requested"}

    @router.post("/sessions/{session_id}/bot/say", status_code=202, tags=["Recall"])
    async def say(session_id: UUID, payload: SayRequest):
        bot = store.bot(str(session_id))
        if not bot or bot["state"] not in (
            "in_call_recording",
            "in_call_not_recording",
        ):
            raise HTTPException(409, "Bot is not currently in a call")
        audio = await service.voice.generate(payload.text)
        audio_id = store.add_audio(str(session_id), payload.text, audio)
        return {"id": audio_id, "state": "queued"}

    @router.post("/webhooks/recall", status_code=202, tags=["Recall callbacks"])
    async def webhook(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 1_000_000:
                raise HTTPException(413, "Webhook body too large")
        delivery_id = verify_webhook(
            bytes(raw),
            request.headers,
            service.settings.recall_webhook_verification_secret,
        )
        try:
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("event"), str)
                or not isinstance(payload.get("data"), dict)
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(400, "Malformed Recall event") from None
        # Unknown events acknowledge without interpreting unrecognized shapes.
        event = payload["event"]
        if not event.startswith(("bot.", "transcript.", "recording.", "calendar.")):
            return {"accepted": True, "ignored": True}
        payload["data"]["alloy_received_at"] = time.time()
        inserted = store.enqueue("webhook:" + delivery_id, payload)
        return {"accepted": True, "duplicate": not inserted}

    @router.get("/recall/jobs", tags=["Recall"])
    async def jobs():
        return store.all(
            "SELECT id,state,attempts,next_at,error FROM recall_jobs ORDER BY rowid DESC LIMIT 100"
        )

    @router.get(
        "/recall/media/{session_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def media(session_id: UUID, token: str = Query()):
        service.authorize_media(str(session_id), token)
        return HTMLResponse(
            Path(__file__).with_name("recall_media.html").read_text(),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            },
        )

    @router.get("/recall/media/{session_id}/next", include_in_schema=False)
    async def next_audio(session_id: UUID, token: str = Query()):
        service.authorize_media(str(session_id), token)
        item = store.claim_audio(str(session_id))
        return item or Response(status_code=204)

    @router.get("/recall/media/{session_id}/audio/{audio_id}", include_in_schema=False)
    async def get_audio(session_id: UUID, audio_id: str, token: str = Query()):
        service.authorize_media(str(session_id), token)
        item = store.one(
            "SELECT audio FROM recall_audio WHERE id=? AND session_id=? AND state='playing' AND expires>?",
            (audio_id, str(session_id), time.time()),
        )
        if not item:
            raise HTTPException(404, "Audio expired or unavailable")
        return Response(
            bytes(item["audio"]),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )

    @router.post(
        "/recall/media/{session_id}/audio/{audio_id}/{outcome}", include_in_schema=False
    )
    async def audio_ack(
        session_id: UUID,
        audio_id: str,
        outcome: Literal["played", "failed"],
        token: str = Query(),
    ):
        service.authorize_media(str(session_id), token)
        updated = store.execute(
            "UPDATE recall_audio SET state=?,audio=X'' WHERE id=? AND session_id=? AND state='playing'",
            (outcome, audio_id, str(session_id)),
        )
        if updated:
            repo.record_event(str(session_id), "voice." + outcome, {"id": audio_id})
        return {"accepted": True}

    @router.get("/recall/calendar/callback", include_in_schema=False)
    async def calendar_forward(request: Request):
        params = request.query_params
        fields = ("code", "error", "recall_calendar_setup_probe")
        if (
            not params.get("state")
            or len(params.getlist("state")) != 1
            or sum(bool(params.get(k)) for k in fields) != 1
            or any(len(params.getlist(k)) > 1 for k in fields)
        ):
            raise HTTPException(
                400, "Expected state plus exactly one authorization result"
            )
        if (
            "recall_calendar_setup_probe" in params
            and params["recall_calendar_setup_probe"] != "1"
        ):
            raise HTTPException(400, "Invalid callback probe")
        target = service.settings.recall_calendar_callback_uri
        if not target:
            raise HTTPException(
                503, "Recall calendar setup has not supplied its callback URI yet"
            )
        parsed = urlparse(target)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "ap-northeast-1.recall.ai"
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(503, "Invalid regional calendar callback configuration")
        forwarded = {k: params[k] for k in ("state", *fields) if k in params}
        return RedirectResponse(
            target + "?" + urlencode(forwarded),
            status_code=302,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @router.post("/recall/calendars", status_code=201, tags=["Calendar"])
    async def attach_calendar(payload: CalendarAttach):
        session_or_404(payload.template_session_id)
        detail = await service.client.request(
            "GET", f"/api/v2/calendars/{payload.calendar_id}/"
        )
        if detail.get("status") != "connected":
            raise HTTPException(409, "Finish calendar authorization before attaching")
        store.execute(
            "INSERT OR IGNORE INTO recall_calendars(id,template_session_id,status,email) VALUES(?,?,?,?)",
            (
                str(payload.calendar_id),
                str(payload.template_session_id),
                detail["status"],
                detail.get("platform_email"),
            ),
        )
        store.enqueue(
            "sync:" + str(uuid4()),
            {
                "event": "internal.calendar_sync",
                "data": {"calendar_id": str(payload.calendar_id)},
            },
        )
        return calendar_or_404(payload.calendar_id)

    @router.get("/recall/calendars", tags=["Calendar"])
    async def calendars():
        return store.all("SELECT * FROM recall_calendars")

    @router.patch("/recall/calendars/{calendar_id}", tags=["Calendar"])
    async def preferences(calendar_id: UUID, payload: CalendarPreference):
        calendar_or_404(calendar_id)
        if payload.auto_join:
            service.require_ready()
        store.execute(
            "UPDATE recall_calendars SET auto_join=? WHERE id=?",
            (int(payload.auto_join), str(calendar_id)),
        )
        store.enqueue(
            "sync:" + str(uuid4()),
            {
                "event": "internal.calendar_sync",
                "data": {"calendar_id": str(calendar_id)},
            },
        )
        return {
            "auto_join": payload.auto_join,
            "sync": "queued",
            "rule": "Future supported meeting links, excluding deleted/cancelled/declined events",
        }

    @router.post(
        "/recall/calendars/{calendar_id}/sync", status_code=202, tags=["Calendar"]
    )
    async def calendar_sync(calendar_id: UUID):
        calendar_or_404(calendar_id)
        store.enqueue(
            "sync:" + str(uuid4()),
            {
                "event": "internal.calendar_sync",
                "data": {"calendar_id": str(calendar_id)},
            },
        )
        return {"state": "queued"}

    @router.get("/recall/calendars/{calendar_id}/events", tags=["Calendar"])
    async def calendar_events(calendar_id: UUID):
        calendar_or_404(calendar_id)
        rows = store.all(
            "SELECT * FROM recall_calendar_events WHERE calendar_id=?",
            (str(calendar_id),),
        )
        return [{**row, "body": json.loads(row["body"])} for row in rows]

    @router.delete("/recall/calendars/{calendar_id}", tags=["Calendar"])
    async def disconnect_calendar(calendar_id: UUID):
        calendar_or_404(calendar_id)
        await service.client.request("DELETE", f"/api/v2/calendars/{calendar_id}/")
        store.execute(
            "UPDATE recall_calendars SET auto_join=0,status='disconnected' WHERE id=?",
            (str(calendar_id),),
        )
        return {"status": "disconnected"}

    return router
