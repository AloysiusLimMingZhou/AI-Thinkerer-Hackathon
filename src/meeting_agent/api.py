from __future__ import annotations

import asyncio
import hmac
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

from .recall import RecallError, RecallService
from .recall_api import router_for

from .config import Settings
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
from .repository import SQLiteRepository
from .services import (
    Brain,
    ElevenLabsVoice,
    IntegrationUnavailable,
    OpenAIBrain,
    Voice,
    citations_for,
    retrieve_context,
    should_answer,
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
    brain = brain or OpenAIBrain(settings)
    voice = voice or ElevenLabsVoice(settings)
    oauth = OAuthManager(settings, repository, provider_requester)
    context_importer = ContextImporter(oauth)
    recall = RecallService(settings, repository, brain, voice, recall_transport)

    @asynccontextmanager
    async def lifespan(app):
        worker = asyncio.create_task(recall.worker())
        try:
            yield
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker

    app = FastAPI(
        title="Meeting Agent API",
        version="0.2.0",
        description="Context-aware meeting delegate backend.",
        lifespan=lifespan,
    )
    app.state.recall = recall

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
                        for p in ("google", "slack", "microsoft", "zoom")
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
        notes = repository.add_context(session_id, payload.notes)
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
        notes = repository.add_context(session_id, [imported])
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
        session = require_session(session_id)
        entry = repository.add_transcript(session_id, payload)
        repository.record_event(
            session_id, "transcript.utterance", entry.model_dump(mode="json")
        )

        if not payload.is_final and not payload.force_answer:
            decision = AgentDecision(
                action="stay_silent", reason="waiting for final caption"
            )
        else:
            approved, reason = should_answer(
                payload.text,
                agent_name=session.agent_name,
                owner_name=session.owner_name,
                force_answer=payload.force_answer,
            )
            if not approved:
                decision = AgentDecision(action="stay_silent", reason=reason)
            else:
                selected_context = retrieve_context(
                    payload.text, repository.get_context(session_id)
                )
                try:
                    answer = await brain.answer(
                        session,
                        payload.text,
                        repository.get_transcript(session_id),
                        selected_context,
                    )
                except IntegrationUnavailable as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                citations = citations_for(selected_context)
                repository.add_qa(session_id, payload.text, answer, citations)
                decision = AgentDecision(
                    action="answer",
                    reason=reason,
                    answer=answer,
                    citations=citations,
                )

        repository.record_event(
            session_id, "agent.decision", decision.model_dump(mode="json")
        )
        return decision

    @app.post(
        "/sessions/{session_id}/coach",
        response_model=CoachSuggestion,
        tags=["meeting"],
    )
    async def coach(session_id: str, payload: CoachRequest) -> CoachSuggestion:
        session = require_session(session_id)
        query = " ".join(
            item for item in (payload.latest_message, payload.objective) if item
        )
        selected_context = retrieve_context(query, repository.get_context(session_id))
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
                repository.get_transcript(session_id),
                selected_context,
            )
        except IntegrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        result = CoachSuggestion(
            suggestion=suggestion,
            citations=citations_for(selected_context),
        )
        repository.record_event(
            session_id, "coach.suggestion", result.model_dump(mode="json")
        )
        return result

    @app.post("/sessions/{session_id}/speak", tags=["voice"])
    async def speak(session_id: str, payload: SpeakRequest) -> Response:
        require_session(session_id)
        try:
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
        session = require_session(session_id)
        transcript_entries = recall.final_transcript(
            session_id
        ) or repository.get_transcript(session_id)
        if not transcript_entries:
            raise HTTPException(status_code=409, detail="Cannot generate empty minutes")
        try:
            content = await brain.generate_minutes(
                session,
                transcript_entries,
                repository.get_context(session_id),
                repository.get_qa_log(session_id),
            )
        except IntegrationUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        minutes = repository.save_minutes(session_id, content)
        repository.record_event(
            session_id, "minutes.generated", minutes.model_dump(mode="json")
        )
        return minutes

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
