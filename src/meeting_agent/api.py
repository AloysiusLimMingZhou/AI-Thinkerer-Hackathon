from __future__ import annotations

import asyncio
import hmac
from uuid import uuid4
from .meeting_service import MeetingService, grounded_result
from .meeting_models import MeetingUtterance
from .playback import RecallPlayback
from contextlib import asynccontextmanager, suppress

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import Settings
from .budget import BudgetService, BudgetExceeded, PaidCallContext, paid_call_context
from .budget_api import budget_router
from .escalations import EscalationService
from .discord_client import DiscordTransport
from .discord_api import discord_router
from .minutes import MinutesService
from .knowledge import KnowledgeService
from .knowledge_api import knowledge_router
from .briefings import BriefingService
from .briefing_api import briefing_router
from .integrations import (
    ContextImporter,
    IntegrationError,
    OAuthManager,
    Requester,
    provider_capabilities,
)
from .models import (
    AgentDecision,
    CoachRequest,
    CoachSuggestion,
    ContextBatch,
    ContextImportRequest,
    ContextNoteView,
    HealthView,
    IntegrationView,
    MinutesView,
    OAuthStartView,
    Provider,
    ProviderCapabilityView,
    SessionCreate,
    SessionView,
    SpeakRequest,
    TranscriptEntry,
    UtteranceCreate,
)
from .recall import RecallError, RecallService
from .recall_api import router_for
from .repository import SQLiteRepository
from .services import (
    Brain,
    ElevenLabsVoice,
    IntegrationUnavailable,
    OpenAIBrain,
    Voice,
    citations_for,
    conversation_gate,
    retrieve_context,
)


def create_app(
    *,
    settings: Settings | None = None,
    repository: SQLiteRepository | None = None,
    brain: Brain | None = None,
    voice: Voice | None = None,
    provider_requester: Requester | None = None,
    recall_transport=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = repository or SQLiteRepository(settings.database_path)
    budget = BudgetService(repository, settings)
    brain = brain or OpenAIBrain(settings, budget)
    voice = voice or ElevenLabsVoice(settings, budget)
    oauth = OAuthManager(settings, repository, provider_requester)
    context_importer = ContextImporter(oauth)
    knowledge = KnowledgeService(repository)
    briefings = BriefingService(repository, knowledge)
    recall = RecallService(settings, repository, brain, voice, recall_transport)
    playback = RecallPlayback(recall)
    meeting = MeetingService(repository, brain, knowledge, playback)
    recall.meeting = meeting
    escalations=EscalationService(repository,meeting)
    meeting.escalations=escalations
    discord=DiscordTransport(settings,escalations.store)
    escalations.notifier=discord
    escalations.settings=settings
    minutes_service=MinutesService(repository,brain,escalations)
    minutes_service.transcript=lambda sid: recall.final_transcript(sid) or repository.get_transcript(sid)
    meeting.minutes=minutes_service

    @asynccontextmanager
    async def lifespan(app):
        worker = asyncio.create_task(recall.worker())
        escalation_worker = asyncio.create_task(escalations.worker())
        gateway = asyncio.create_task(discord.gateway(escalations))
        minutes_worker = asyncio.create_task(minutes_service.worker())
        try:
            yield
        finally:
            worker.cancel()
            escalation_worker.cancel()
            gateway.cancel()
            minutes_worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            with suppress(asyncio.CancelledError):
                await escalation_worker
            with suppress(asyncio.CancelledError):
                await gateway
            with suppress(asyncio.CancelledError):
                await minutes_worker

    app = FastAPI(
        title="Meeting Agent API",
        version="0.2.0",
        description="Context-aware meeting delegate backend.",
        lifespan=lifespan,
    )
    app.state.budget = budget
    app.include_router(budget_router(budget))

    @app.exception_handler(BudgetExceeded)
    async def budget_error(request, exc):
        return JSONResponse({'detail': {'code':'monthly_budget_exhausted','message':str(exc),'reset_at':exc.status.reset_at.isoformat(),'available_micro_usd':exc.status.available_micro_usd}},status_code=429)

    app.state.recall = recall
    app.state.knowledge = knowledge
    app.state.briefings = briefings
    app.include_router(briefing_router(briefings))
    app.state.meeting = meeting
    app.state.playback = playback
    app.state.escalations = escalations
    app.state.discord = discord
    app.state.minutes = minutes_service
    app.include_router(discord_router(discord))
    app.include_router(knowledge_router(knowledge))

    @app.middleware("http")
    async def private_backend(request: Request, call_next):
        path = request.url.path
        public = (
            path in ("/health", "/docs", "/openapi.json", "/docs/oauth2-redirect")
            or (request.method == "POST" and path == "/webhooks/recall")
            or path.startswith("/recall/media/")
            or (
                request.method == "GET"
                and (
                    path == "/recall/calendar/callback"
                    or path
                    in {
                        f"/integrations/{p}/callback"
                        for p in ("google",)
                    }
                )
            )
        )
        if request.method != "OPTIONS" and not public:
            if not settings.backend_api_token:
                return JSONResponse(
                    {"detail": "Set BACKEND_API_TOKEN before using the backend"},
                    status_code=503,
                )
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(
                supplied, "Bearer " + settings.backend_api_token
            ):
                return JSONResponse(
                    {"detail": "Backend authentication required"}, status_code=401
                )
        if request.method == 'POST' and path.endswith('/knowledge'):
            maximum = 22 * 1024 * 1024
            try:
                if int(request.headers.get('content-length','0')) > maximum:
                    return JSONResponse({'detail':'Upload request exceeds 22 MiB'},status_code=413)
            except ValueError:
                return JSONResponse({'detail':'Invalid content length'},status_code=400)
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>maximum:
                    return JSONResponse({'detail':'Upload request exceeds 22 MiB'},status_code=413)
            request._body=bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(RecallError)
    async def recall_error(request, exc):
        headers = (
            {"Retry-After": str(int(exc.retry_after) + 1)} if exc.retry_after else None
        )
        return JSONResponse(
            {"detail": str(exc), "needs_reconciliation": exc.ambiguous},
            status_code=503,
            headers=headers,
        )

    @app.exception_handler(IntegrationUnavailable)
    async def integration_unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    app.include_router(router_for(recall))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_session(session_id: str) -> SessionView:
        session = repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    def require_meeting(session_id: str):
        session = require_session(session_id)
        if session.purpose != "meeting":
            raise HTTPException(409, "This is a briefing; use /join to create a meeting")
        return session

    @app.get('/sessions/{session_id}/questions',tags=['meeting'])
    async def questions(session_id: str):
        require_session(session_id)
        return escalations.questions(session_id)

    @app.get("/health", response_model=HealthView, tags=["system"])
    async def health() -> HealthView:
        return HealthView(
            openai_configured=bool(settings.openai_api_key),
            elevenlabs_configured=bool(settings.elevenlabs_api_key),
        )

    @app.get(
        "/platforms",
        response_model=list[ProviderCapabilityView],
        tags=["integrations"],
    )
    async def platforms() -> list[ProviderCapabilityView]:
        return provider_capabilities()

    @app.get(
        "/integrations",
        response_model=list[IntegrationView],
        tags=["integrations"],
    )
    async def integrations() -> list[IntegrationView]:
        return oauth.list_integrations()

    @app.post(
        "/integrations/{provider}/authorize",
        response_model=OAuthStartView,
        tags=["integrations"],
    )
    async def authorize(provider: Provider) -> OAuthStartView:
        try:
            return oauth.start(provider)
        except IntegrationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get(
        "/integrations/{provider}/callback",
        response_model=IntegrationView,
        tags=["integrations"],
    )
    async def oauth_callback(
        provider: Provider,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> IntegrationView:
        if error:
            raise HTTPException(status_code=400, detail=f"OAuth denied: {error}")
        if not code or not state:
            raise HTTPException(status_code=400, detail="Missing OAuth code or state")
        try:
            return await oauth.callback(provider, code=code, state=state)
        except IntegrationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete(
        "/integrations/{provider}",
        status_code=204,
        tags=["integrations"],
    )
    async def disconnect(provider: Provider) -> Response:
        oauth.repository.delete_integration(provider)
        return Response(status_code=204)

    @app.post(
        "/sessions", response_model=SessionView, status_code=201, tags=["sessions"]
    )
    async def create_session(payload: SessionCreate) -> SessionView:
        session = repository.create_session(payload)
        repository.record_event(
            session.id, "session.created", session.model_dump(mode="json")
        )
        return session

    @app.get("/sessions", response_model=list[SessionView], tags=["sessions"])
    async def list_sessions() -> list[SessionView]:
        return repository.list_sessions()

    @app.get("/sessions/{session_id}", response_model=SessionView, tags=["sessions"])
    async def get_session(session_id: str) -> SessionView:
        return require_session(session_id)

    @app.post(
        "/sessions/{session_id}/context",
        response_model=list[ContextNoteView],
        status_code=201,
        tags=["context"],
    )
    async def add_context(
        session_id: str, payload: ContextBatch
    ) -> list[ContextNoteView]:
        require_session(session_id)
        notes = knowledge.add_notes(session_id, payload.notes)
        repository.record_event(
            session_id,
            "context.added",
            {"notes": [note.model_dump(mode="json") for note in notes]},
        )
        return notes

    @app.post(
        "/sessions/{session_id}/context/import",
        response_model=list[ContextNoteView],
        status_code=201,
        tags=["context"],
    )
    async def import_context(
        session_id: str, payload: ContextImportRequest
    ) -> list[ContextNoteView]:
        require_session(session_id)
        try:
            imported = await context_importer.import_context(payload)
        except IntegrationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        notes = knowledge.add_notes(session_id, [imported])
        repository.record_event(
            session_id,
            "context.imported",
            {
                "provider": payload.provider,
                "resource_type": payload.resource_type,
                "notes": [note.model_dump(mode="json") for note in notes],
            },
        )
        return notes

    @app.get(
        "/sessions/{session_id}/transcript",
        response_model=list[TranscriptEntry],
        tags=["meeting"],
    )
    async def transcript(session_id: str) -> list[TranscriptEntry]:
        require_session(session_id)
        return recall.final_transcript(session_id) or repository.get_transcript(
            session_id
        )

    @app.post(
        "/sessions/{session_id}/utterances",
        response_model=AgentDecision,
        tags=["meeting"],
    )
    async def ingest_utterance(
        session_id: str, payload: UtteranceCreate
    ) -> AgentDecision:
        require_meeting(session_id)
        return await meeting.ingest(session_id,MeetingUtterance(
            event_id=payload.event_id or str(uuid4()),platform="preview",
            participant_id=payload.participant_id,speaker=payload.speaker,
            text=payload.text,spoken_at=payload.spoken_at,is_final=payload.is_final,
            is_self=payload.is_self,force_answer=payload.force_answer),preview=True)

    @app.post(
        "/sessions/{session_id}/coach",
        response_model=CoachSuggestion,
        tags=["meeting"],
    )
    async def coach(session_id: str, payload: CoachRequest) -> CoachSuggestion:
        session = require_meeting(session_id)
        query = " ".join(
            item for item in (payload.latest_message, payload.objective) if item
        )
        selected_context = knowledge.search(session_id, query)
        coaching_prompt = (
            "Privately suggest exactly what the meeting owner should say next. "
            f"Latest message: {payload.latest_message}"
        )
        if payload.objective:
            coaching_prompt += f"\nOwner's objective: {payload.objective}"
        try:
            suggestion = await brain.answer(
                session,
                coaching_prompt,
                repository.get_dialogue(session_id),
                selected_context,
            )
        except IntegrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        result = CoachSuggestion(
            suggestion=grounded_result(suggestion,selected_context)[0],
            citations=grounded_result(suggestion,selected_context)[1],
        )
        repository.record_event(
            session_id, "coach.suggestion", result.model_dump(mode="json")
        )
        return result

    @app.post("/sessions/{session_id}/speak", tags=["voice"])
    async def speak(session_id: str, payload: SpeakRequest) -> Response:
        require_meeting(session_id)
        try:
            with paid_call_context(PaidCallContext(session_id, str(uuid4()), 'manual-speech')):
                audio = await voice.generate(payload.text)
        except IntegrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        repository.record_event(session_id, "voice.generated", {"text": payload.text})
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
        )

    @app.post(
        "/sessions/{session_id}/minutes",
        response_model=MinutesView,
        tags=["minutes"],
    )
    async def generate_minutes(session_id: str) -> MinutesView:
        require_meeting(session_id)
        transcript_entries = recall.final_transcript(
            session_id
        ) or repository.get_transcript(session_id)
        try:
            return await minutes_service.finalize(session_id,transcript_entries)
        except IntegrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get('/sessions/{session_id}/finalization')
    async def finalization_status(session_id: str):
        require_session(session_id)
        return minutes_service.status(session_id)

    @app.get(
        "/sessions/{session_id}/minutes",
        response_model=MinutesView,
        tags=["minutes"],
    )
    async def get_minutes(session_id: str) -> MinutesView:
        require_session(session_id)
        minutes = repository.get_minutes(session_id)
        if minutes is None:
            raise HTTPException(status_code=404, detail="Minutes not generated")
        return minutes

    @app.get("/sessions/{session_id}/events", tags=["events"])
    async def get_events(
        session_id: str, after: int = Query(default=0, ge=0)
    ) -> list[dict[str, object]]:
        require_session(session_id)
        return repository.get_events(session_id, after)

    @app.websocket("/sessions/{session_id}/stream")
    async def event_stream(websocket: WebSocket, session_id: str) -> None:
        supplied = websocket.headers.get("authorization", "")
        protocols = websocket.scope.get("subprotocols", [])
        selected_protocol = None
        if not supplied and protocols:
            selected_protocol = next(
                (p for p in protocols if p.startswith("bearer.")), None
            )
            if selected_protocol:
                supplied = "Bearer " + selected_protocol.removeprefix("bearer.")
        if not settings.backend_api_token or not hmac.compare_digest(
            supplied, "Bearer " + settings.backend_api_token
        ):
            await websocket.close(code=4401, reason="Backend authentication required")
            return
        if repository.get_session(session_id) is None:
            await websocket.close(code=4404, reason="Session not found")
            return
        await websocket.accept(subprotocol=selected_protocol)
        sequence = 0
        try:
            while True:
                events = repository.get_events(session_id, sequence)
                for event in events:
                    await websocket.send_json(event)
                    sequence = int(event["sequence"])
                await asyncio.sleep(0.25)
        except WebSocketDisconnect:
            return

    schema = app.openapi()
    schema.setdefault("components", {})["securitySchemes"] = {
        "BackendToken": {"type": "http", "scheme": "bearer"}
    }
    schema["security"] = [{"BackendToken": []}]
    return app


app = create_app()
