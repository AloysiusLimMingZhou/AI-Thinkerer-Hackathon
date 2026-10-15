# Personal Meeting Agent Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add meeting-scoped text/file knowledge, grounded answers, urgency-confirmed Discord escalation and automatic owner-reply relay, backed by a common meeting pipeline.

**Architecture:** Keep FastAPI/SQLite and Recall for Google Meet. Extract one meeting service with transport-independent utterance/playback contracts; isolate file knowledge, persisted escalation state and Discord transport. Discord voice attendance is the following milestone.

**Tech Stack:** Python 3.13, FastAPI/Pydantic/SQLite, HTTPX, OpenAI Responses API, ElevenLabs, `pypdf`, `python-docx`, `discord.py>=2.6,<3` for the Gateway connection, Next.js 16/React 19/TypeScript. Lock new dependencies through `uv`; do not install Discord voice extras. Gateway lifecycle/events follow the [official discord.py documentation](https://discordpy.readthedocs.io/en/stable/quickstart.html); explicit HTTPX REST operations keep nonce, rate-limit and uncertain-send handling under the durable outbox's control.

**Spec:** [Approved design](../specs/2026-10-14-personal-meeting-agent-design.md).

## Global Constraints

- Supported product platforms become Google Meet and Discord. Remove Slack integration and stop offering Zoom/Teams. Keep existing stored meeting records readable.
- Keep knowledge explicitly attached to the meeting. No automatic Discord-history or global past-meeting ingestion.
- Supported first-version file types: UTF-8 `.txt`, `.md`, text-containing `.pdf`, and `.docx`.
- Limits: five files per submission; 10 MiB per file; 20 MiB combined file bytes; 100,000 characters of pasted text per submission; 500,000 extracted characters per file; 1,000,000 total knowledge characters per meeting. Upload request limit: 22 MiB.
- PDFs: at most 300 pages. DOCX: at most 2,000 archive entries and 50 MiB expanded content. Extraction: 10-second per-file timeout in a terminable worker process.
- Chunks: up to 2,000 characters, 200-character overlap; at most eight positive-match evidence chunks per answer.
- Unsupported factual answer: “I don't know based on the knowledge I have. Is this urgent?” Urgency window: 60 seconds from queueing this prompt; cancel on playback failure.
- Discord answers are spoken in the meeting; Discord text is for urgency escalation and owner replies. Relay only new plaintext replies from the configured owner and mapped question thread/parent.
- Discord messages: at most 2,000 characters; split question text into segments of at most 1,800 characters. Mention the owner once. Owner spoken relays: at most 2,000 characters, introduced as “[owner name] says: …”.
- Server-only configuration: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_ESCALATION_CHANNEL_ID`, `DISCORD_OWNER_USER_ID`; never model-chosen IDs.
- Use additive database migrations, durable side-effect records and deduplication. A network timeout is not proof of delivery. No destructive database reset or automatic uncertain replay.
- Preserve the single-operator deployment boundary. Preview/rehearsal never sends Discord messages. Force-answer never bypasses knowledge evidence requirements.
- Tests use fake external providers. Do not launch a real call, send a Discord ping or use provider credits during normal verification.

## Review Focus

- A mixed valid/invalid upload must not launch a meeting or silently discard knowledge; test atomic ingestion and saved-session retry in Task 2.
- “No, it is not urgent” must not match a positive urgency signal; test negatives, another speaker, simultaneous questions and expiry in Task 4.
- A Discord timeout/restart must not create duplicate owner pings or replay uncertain speech; test durable outbox recovery and message-ID deduplication in Task 5.
- A delayed final transcript or owner reply must not be lost after call end; test finalization polling and post-call replies in Tasks 5–6.
- Legacy databases and calendar-copied notes must remain readable and visible; test additive schema opening and knowledge listing in Tasks 2–3.

## Baseline already completed

- [x] Install existing locked backend/frontend dependencies without changing versions.
- [x] Verify Python 3.13.13 backend suite: **67 passed**, one dependency deprecation warning.
- [x] Verify frontend typecheck and production build on Node 24.18.0/npm 11.8.0.
- [x] Rewrite README to actual architecture, archive old hackathon design, add `.node-version`, update assessment.
- [x] Save the owner's approved design. Baseline/spec checkpoint: `1b959c8`.

## Task 1: Reduce the active platform scope

**Files:** Modify `src/meeting_agent/models.py`, `config.py`, `integrations.py`, `api.py`, `recall.py`; `apps/web/app/actions.ts`, `apps/web/lib/meeting.ts`, `apps/web/components/Icon.tsx`; `.env.example`; `tests/test_api.py`, `tests/test_recall.py`; add `tests/test_platform_scope.py`.

**Interfaces:** Keep `Provider` for Google OAuth/import only. Keep `validate_meeting_url(value: str) -> None`, now permitting Google Meet only. Add a distinct meeting-platform value `google_meet | discord` when defining normalized meeting input in Task 3; Discord messaging is not an OAuth context provider.

- [ ] **Step 1: Write scope regression tests.** Replace the Slack fake OAuth/import fixture with a Google authorization-code/Calendar fixture. Add these assertions:

```python
def test_new_dispatch_accepts_only_google_meet():
    validate_meeting_url("https://meet.google.com/abc-defg-hij")
    for url in ["https://zoom.us/j/123", "https://teams.microsoft.com/l/meetup-join/x"]:
        with pytest.raises(HTTPException) as exc:
            validate_meeting_url(url)
        assert exc.value.status_code == 422
```

Also assert removed provider imports/authorization are unavailable, Google import persists notes, and historical non-Google session records still return from read endpoints.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_platform_scope.py tests/test_api.py -q`. Expected: new scope assertions fail before implementation.
- [ ] **Step 3: Remove** non-Google OAuth specs/branches/settings and callback public exemptions. Update new-dispatch validation, calendar eligibility, frontend validation/labels/source icons and `.env.example`. Preserve historical DB rows and source strings. Do not advertise Discord voice readiness.
- [ ] **Step 4: Run** the tests from Step 2 and `npm run typecheck` in `apps/web`. Expected: passes; prior session/API flows retained.
- [ ] **Step 5: Commit** `refactor: focus active platforms on Google Meet and Discord` with only this task's files.

## Task 2: Add meeting text/file knowledge and the existing-form upload flow

**Files:** Add `src/meeting_agent/knowledge.py`, `knowledge_store.py`, `knowledge_api.py`; modify `models.py`, `api.py`, `repository.py`, `pyproject.toml`, `uv.lock`; `apps/web/lib/backend.ts`, `api-types.ts`, `app/actions.ts`, `components/SendForm.tsx`, `components/Forms.tsx`, `components/MeetingPanels.tsx`, meeting page, `next.config.ts`, relevant CSS modules; add `tests/test_knowledge.py`, `tests/test_knowledge_api.py` and small generated/document fixtures.

**Interfaces:**

- `KnowledgeSource`: `id`, `session_id`, `title`, `source`, optional `filename`, `content_hash`, `created_at`.
- `KnowledgeChunk`: `id`, `source_id`, `source`, `title`, optional `filename`, `text`, `locator` (page/paragraph/line label).
- `KnowledgeService.ingest(session_id: str, text: str, files: Sequence[UploadFile]) -> KnowledgeIngestResult`, with `sources: list[KnowledgeSource]` and `duplicates: list[str]`.
- `KnowledgeService.list_sources(session_id: str) -> list[KnowledgeSource]` and `search(session_id: str, query: str, limit: int = 8) -> list[KnowledgeChunk]`.
- Authenticated `GET /sessions/{id}/knowledge` and multipart `POST /sessions/{id}/knowledge`; existing JSON `/context` writes through the same knowledge store. Endpoint errors: 413 for byte limits, 422 for unsupported/extraction errors, 404 for unknown session.

- [ ] **Step 1: Add tests using real extraction**, generated UTF-8/Markdown/PDF/DOCX fixtures and temporary SQLite. Assert text/locators survive; duplicate content is idempotent; unrelated retrieval returns `[]`; chunk lengths/overlap meet the spec. Add input-limit/error cases and an all-or-nothing mixed-file batch:

```python
def test_invalid_file_batch_does_not_store_partial_knowledge(client, session_id):
    response = client.post(f"/sessions/{session_id}/knowledge", files=[
        ("files", ("brief.txt", b"Launch is Friday", "text/plain")),
        ("files", ("broken.pdf", b"not a PDF", "application/pdf")),
    ])
    assert response.status_code == 422
    assert client.get(f"/sessions/{session_id}/knowledge").json() == []
```

Cover blank/encrypted/scanned PDFs, malformed/expanded DOCX, invalid UTF-8, total meeting limits, worker timeout and reopening an old schema. Fixtures are local; no document download.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_knowledge.py tests/test_knowledge_api.py -q`. Expected: fail for absent service/routes.
- [ ] **Step 3: Implement** bounded extraction in a terminable process, provenance/chunk storage and atomic ingestion. Add/lock `pypdf`, `python-docx` and multipart support. Index/backfill existing text notes idempotently; expose calendar-copied notes in the list. Preserve any source text that an existing record already stores.

Extend both existing knowledge forms with multi-file selection and a source list. Submit multipart through the server-only backend client, set the 22 MiB Server Action limit, and launch only after successful ingestion. Return/reuse a saved session ID after a partial create-flow failure; provide a clear route to finish that session rather than creating another bot. Keep delegate name, owner and text values on validation errors.

- [ ] **Step 4: Run** the new tests, backend suite and frontend typecheck/build. Browser-check valid upload, mixed-file rejection and retry into the saved meeting; assert no launch was submitted on upload failure.
- [ ] **Step 5: Commit** `feat: add meeting-scoped text and file knowledge`.

## Task 3: Extract shared ingestion, structured answers and playback contracts

**Files:** Add `src/meeting_agent/meeting_service.py`, `meeting_models.py`, `playback.py`; modify `services.py`, `models.py`, `repository.py`, `api.py`, `recall.py`, `recall_api.py`, `recall_media.html`; update frontend decision/citation types/rendering; add `tests/test_meeting_service.py`, `tests/test_grounded_answers.py`; adapt existing brain fakes and conversational/Recall tests.

**Interfaces:**

- `MeetingUtterance`: `event_id`, `platform` (`google_meet | discord | preview`), optional `participant_id`, `speaker`, timezone-aware `spoken_at`, `received_at`, `text`, `is_final`, `is_self`, `force_answer`.
- `AnswerEvidence`: `chunk_id`, `quote`; `BrainAnswer`: `kind` (`supported | unknown | social`), `text`, `evidence: list[AnswerEvidence]`.
- Change `Brain.answer(session, question, transcript, context: Sequence[KnowledgeChunk]) -> BrainAnswer` and implement structured provider output/validation in `OpenAIBrain`.
- `Playback.enqueue(session_id: str, text: str, key: str) -> str`, `is_live(session_id: str) -> bool`, `mute(session_id: str, muted: bool) -> None`, `stop(session_id: str) -> None`, all async. Recall implementation wraps current audio queue/media transport; preview implementation records intent without audio/network.
- `MeetingService.ingest(session_id: str, utterance: MeetingUtterance, *, preview: bool = False) -> AgentDecision`; existing decision adds `defer` and evidence-bearing citations. Task 4 adds an injected urgency handler before normal gating.

- [ ] **Step 1: Write service contract tests** with fake brain/voice/playback and real temporary storage. Assert supported answers cite only known chunks with exact excerpts; invalid/missing evidence returns the unknown prompt; no matching knowledge cannot produce a factual answer; social speech can be citation-free. Pin force-answer, self-voice, provider-ID deduplication and timestamp preservation:

```python
async def test_replayed_provider_event_has_one_decision_and_one_audio(harness):
    event = harness.utterance(event_id="provider-1", text="Alloy, when is launch?")
    await harness.service.ingest(harness.session_id, event)
    await harness.service.ingest(harness.session_id, event)
    assert len(harness.playback.queued) == 1
    assert len(harness.answer_decisions()) == 1
```

Define the harness in `tests/test_meeting_service.py` using these interfaces. Add a comparison of preview and Recall decisions; preview must have zero external messages/audio. Ensure another session can progress during a blocked model call.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_meeting_service.py tests/test_grounded_answers.py -q`. Expected: contract/evidence tests fail before extraction.
- [ ] **Step 3: Implement** `MeetingService`, structured brain output, provenance validation and per-session serialization. Move repeated API/Recall gating/retrieval/Q&A behavior into it. Normalize Recall participant IDs and original timestamps, retaining receive-time fallback and existing stale/backlog guards. Use current/previous question text for follow-up retrieval. Keep coaching private and `/speak`/manual operator speech explicit; do not open urgency or notify from preview/coaching.

Add additive processing-state records keyed by session/platform/event ID to distinguish ingest deduplication from side-effect completion. Store decision/queue intent durably; uncertain interrupted speech is not blindly retried. Implement transport-level mute/stop so common controls have a real Recall behavior.

- [ ] **Step 4: Run** the new tests plus `tests/test_conversation.py`, `tests/test_recall.py`, `tests/test_api.py`; update fakes/expected outcomes only where the approved grounding policy deliberately changes behavior. Run frontend typecheck.
- [ ] **Step 5: Commit** `refactor: share the grounded meeting decision and playback pipeline`.

## Task 4: Persist unanswered questions and urgency-confirmed escalation

**Files:** Add `src/meeting_agent/escalations.py`, `escalation_store.py`; modify `meeting_service.py`, shared models, repository wiring and decision events; add `tests/test_urgency.py`, `tests/test_escalation_store.py`; update dashboard activity/question display.

**Interfaces:**

- `UnansweredQuestion`: `id`, `session_id`, `utterance_id`, optional `participant_id`, `speaker`, `question`, `state`, `asked_at`, `urgency_deadline`, optional Discord parent/thread IDs.
- States from the spec plus outbox `needs_attention`; preserve a delivery error separately from the question content.
- `EscalationService.open_question(session_id: str, utterance: MeetingUtterance) -> UnansweredQuestion`.
- `handle_confirmation(session_id: str, utterance: MeetingUtterance) -> UrgencyResult`, where result is `not_applicable | ambiguous | confirmed | declined | expired`, with question ID when mapped.
- Define `DiscordQuestionRef(parent_message_id: str, thread_id: str)` and `NotificationTransport.send_question(question: UnansweredQuestion) -> DiscordQuestionRef` (async); fake transport until Task 5. Durable outbox stores request ID, state, attempt time and confirmed provider IDs.

- [ ] **Step 1: Write timestamp-controlled tests** for the exact unknown prompt, 60-second window, same-speaker confirmation, explicit-reference handling, two pending questions, duplicate confirmation and negative-first interpretation:

```python
@pytest.mark.parametrize("reply", ["No, it is not urgent", "No rush", "Don't contact them"])
async def test_negative_confirmation_never_notifies(harness, reply):
    await harness.ask_unknown("What is the approved budget?")
    await harness.respond(reply, same_speaker=True)
    assert harness.notifications.sent == []
    assert harness.question().state == "not_urgent"
```

Assert unknown-speaker “yes”, expiry, self speech and preview do not notify. Playback failure cancels the question's urgency window. Question/outbox state survives reopening the DB.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_urgency.py tests/test_escalation_store.py -q`. Expected: failures for absent state handling.
- [ ] **Step 3: Implement** persisted questions, conservative confirmation routing before ordinary wake-name gating, outbox deduplication and truthful spoken statuses. Never ask the model to choose notification targets or make delivery claims. Emit question/delivery events that the dashboard can render.
- [ ] **Step 4: Run** new tests plus Task 3 tests. Assert two identical confirmations create exactly one local escalation request; this is distinct from guaranteed network delivery.
- [ ] **Step 5: Commit** `feat: escalate unanswered questions only after urgency confirmation`.

## Task 5: Connect Discord owner threads and relay authorized replies

**Files:** Add `src/meeting_agent/discord_client.py`, `discord_api.py`; modify `config.py`, `api.py` lifespan wiring, `escalations.py`, shared playback integration, `.env.example`, manifests/lockfile, frontend readiness; add `tests/test_discord.py`, `tests/test_owner_replies.py`.

**Interfaces:**

- Consume `DiscordQuestionRef` and `NotificationTransport` from Task 4.
- `DiscordTransport.send_question(question) -> DiscordQuestionRef` implements Task 4's transport with rate-limit and ambiguous-send handling.
- `OwnerReply(message_id: str, guild_id: str, channel_id: str, author_id: str, text: str, created_at: datetime, parent_message_id: str | None)`.
- `EscalationService.receive_owner_reply(reply: OwnerReply) -> ReplyOutcome` (async), with `ignored | queued | saved_after_end | too_long | needs_attention` outcomes.
- `GET /discord/status` reports missing configuration names, Gateway connection state and `voice_attendance_available: false`.

- [ ] **Step 1: Write fake REST/Gateway tests** verifying the configured owner is the sole allowed mention, long questions are segmented without lost text, thread/parent IDs are persisted, a 429 respects retry time, and ambiguous create failures are not replayed blindly. No test hits Discord.

```python
async def test_owner_reply_deduplicates_and_stays_in_its_meeting(harness):
    reply = harness.owner_reply(message_id="discord-1", text="The approved budget is 500.")
    await harness.escalations.receive_owner_reply(reply)
    await harness.escalations.receive_owner_reply(reply)
    assert [item.text for item in harness.playback.queued] == [
        "Aloy says: The approved budget is 500."
    ]
    assert harness.other_session_audio() == []
```

Also cover non-owner/bot/webhook senders, unknown guild/channel/thread, parent-reply race, edits/attachments, 2,001-character replies, multiple owner corrections, duplicate Gateway deliveries, meeting ending before playback and replies arriving after end. Preserve accepted owner text as meeting-scoped knowledge.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_discord.py tests/test_owner_replies.py -q`. Expected: fails for absent transport/relay.
- [ ] **Step 3: Implement** server-only configured transport and optional lifespan Gateway task; use the SDK's Message Content intent and explicit required channel permissions. Match IDs rather than display names. Queue owner replies with message-ID keys through Task 3 playback, mark resolved only when accepted, and recheck liveness before speaking. Send a thread acknowledgement after end without rejoining. Expose setup/delivery failures in readiness/activity.
- [ ] **Step 4: Run** new tests and the urgency/meeting tests; verify startup/shutdown with no Discord settings still supports Meet notes. Run frontend typecheck/build.
- [ ] **Step 5: Commit** `feat: relay urgent owner answers through Discord question threads`.

## Task 6: Finalize the whole meeting and retain unresolved questions

**Files:** Add `src/meeting_agent/minutes.py`; modify `services.py`, `meeting_service.py`, `repository.py`, `recall.py`, minutes routes; `apps/web/lib/api-types.ts`, `lib/meeting.ts`, meeting/home pages and panels; add `tests/test_minutes.py`, extend Recall final-transcript tests.

**Interfaces:** `MinutesService.finalize(session_id: str, transcript: Sequence[TranscriptEntry]) -> MinutesView` (async), called by Recall and manual API. Persist `processing | ready | failed` finalization state independently of transport liveness. Generate chronological segments of at most 30,000 text characters and synthesize all segment summaries together with persisted unanswered questions/owner replies; use hierarchical batches if combined summaries exceed 30,000 characters. A single oversize utterance is split with speaker/time provenance retained.

- [ ] **Step 1: Write tests** with a fake summarizer that captures every segment and final synthesis input. Place a decision in entry 1 of a 601-entry transcript, and assert it is retained along with an unresolved question and owner reply:

```python
async def test_long_meeting_keeps_early_decisions_and_unresolved_questions(harness):
    await harness.finalize_entries(count=601, first="Decision: launch Friday.")
    assert "Decision: launch Friday." in harness.all_segment_input()
    assert harness.unanswered_question_text in harness.synthesis_input()
    assert harness.owner_reply_text in harness.synthesis_input()
```

Test duplicate completion, empty transcript, model failure/retry, multiple final transcript artifacts and post-call owner updates. Add frontend polling checks for `call_ended + processing` versus `ready`/visible failure.

- [ ] **Step 2: Run** `uv run --locked pytest tests/test_minutes.py tests/test_recall.py -q`. Expected: long-meeting/finalization tests fail before implementation.
- [ ] **Step 3: Implement** bounded full-transcript minutes and question/answer appendices. Route both existing minutes-generation paths through it. Keep polling after call end until finalization completes or visibly fails; do not equate bot departure with notes readiness. Refresh generated minutes when an accepted post-call owner answer changes the record, using explicit queued processing state.
- [ ] **Step 4: Run** the new tests and frontend typecheck/build; browser-check a delayed final-transcript event updates the meeting screen without manual reload.
- [ ] **Step 5: Commit** `fix: finalize complete meeting notes after transport departure`.

## Task 7: Verify and document the finished phase

**Files:** Update `README.md`, `docs/BACKEND_HANDOFF.md`, `docs/DEMO_RUNBOOK.md`, `.env.example`, `docs/PROJECT_ASSESSMENT.md`; add a concise Discord setup/operations document and any focused integration tests missing from Tasks 1–6. Keep archived hackathon material marked historical.

**Interfaces:** No new runtime contracts. Documentation must describe implemented endpoints, exact file limits, config/intent/permission setup, voice-only relay behavior, failed-delivery recovery, database upgrade backup and the still-pending Discord voice `/join` milestone.

- [ ] **Step 1: Add one cross-component acceptance test** using real storage/API/extraction and fake model/Discord/playback: upload briefing, answer supported question, ask unsupported question, confirm urgency, receive owner's thread reply, queue it once and generate complete minutes. Include an injected malicious document and a non-owner reply; neither can cause unauthorized side effects.
- [ ] **Step 2: Run the acceptance test** and investigate any failure before correcting the integration/config issue it exposes. If it already passes, keep that evidence and do not manufacture a failure or an unnecessary change.
- [ ] **Step 3: Run** `uv sync --locked`, `uv run --locked pytest -q`, `npm run typecheck`, `npm run build`, plus browser acceptance checks from Tasks 2 and 6. Run `npm ci` again only if the frontend lockfile changed. Record fresh results; do not infer live provider readiness from fakes. Preserve existing lockfile versions unless a new approved dependency requires changes.
- [ ] **Step 4: Self-review** spec coverage, additive migration behavior, source citation correctness, thread/session matching, uncertain side effects and end-of-meeting liveness. Use the chosen execution method's independent final reviewer, then address verified findings and rerun only affected checks.
- [ ] **Step 5: Commit** `docs: document personal knowledge and urgent Discord relay` and report implemented behavior, verification, deployment configuration still needed, and remaining Discord voice transport work.

## Execution review

The owner has approved the written design. This plan still needs review and an execution-method selection before product code/dependency changes. Recommended execution is **Native**, because these seven tasks share the same session, evidence, question and playback contracts; one implementer can keep those interfaces consistent, followed by an independent review of the complete change.
