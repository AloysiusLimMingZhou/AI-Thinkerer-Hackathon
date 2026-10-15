# Discord Voice Attendance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Attend Discord voice meetings through /join with optional website briefings, the selected AI models, shared Meet/Discord answering and notes, and a USD 5 soft / USD 8 hard estimated monthly API budget.

**Architecture:** A supervised Node worker owns Discord Gateway and DAVE voice transport. Python retains authorization, SQLite state, knowledge, gpt-transcribe transcription, gpt-6-luna answers/minutes, ElevenLabs dialogue synthesis and cost reservations. Meet and Discord share the meeting/playback pipeline.

**Tech Stack:** Python >=3.13, FastAPI, SQLite, AsyncOpenAI, asynchronous ElevenLabs Text to Dialogue WebSocket, Node >=22.12, discord.js 14.27.0, @discordjs/voice 0.19.2, locked Opus decoder, FFmpeg, Next.js 16, React 19, TypeScript, pytest and Node's built-in test runner.

**Spec:** docs/superpowers/specs/2026-10-15-discord-voice-attendance-design.md, approved 15 October 2026, plus the approved foundation design dated 14 October 2026 for knowledge, urgency and owner-reply semantics.

**Execution:** Preserve the owner's Native execution choice: implement in this session, then one independent whole-branch review. Approved by the owner on 15 October 2026: start Native implementation.

## Global Constraints

- Only Google Meet and Discord. Ordinary answers are spoken; slash acknowledgements are ephemeral. Owner mentions require confirmed question urgency.
- Models: gpt-transcribe, gpt-6-luna for both answers and minutes, eleven_v4_turbo. No silent substitutions.
- Live-answer context: current question, at most eight relevant knowledge chunks, latest 12 dialogue utterances, at most 2,000 characters per utterance. Final notes cover the whole chronological transcript in sections of at most 30,000 characters.
- One configured owner/guild, one active/joining Discord call, one backend process and one SQLite database.
- Keys stay server-side; Node receives only the Discord token. Missing keys permit authoring/offline tests but prevent real attendance.
- Shared OpenAI/ElevenLabs estimated usage budget: USD 5 soft, USD 8 hard, Asia/Kuala_Lumpur months. Recall, hosting, taxes, subscriptions and other applications are excluded.
- Reserve conservative maximum cost plus 10 percent before paid calls; count held/uncertain reservations. No automatic provider retries, top-ups, bypass or speech replay.
- Preserve knowledge upload limits, exact unknown wording and stored records. Use additive migrations.
- Audio clips <=15 seconds; two transcription calls in flight and eight waiting; voice queue depth two. Empty-channel grace 60 seconds; maximum attendance defaults to four hours.
- No real provider calls, Discord registration, joins or pings in implementation/tests. Keys and an authorized private-call check come later.

## Review Focus

1. Duplicate events during thread creation/reconnect must not duplicate mentions, speech, joins or paid operations. Pin in Tasks 1, 8 and 9.
2. Identical/changed display names must not merge participant identity or suppress humans sharing the bot's name. Pin in Tasks 5 and 9.
3. Provider acceptance before timeout/crash must retain possibly charged reservations across restart. Pin in Tasks 1-3.
4. Local month rollover must settle in-flight work in its original bucket without automatic rejoin/replay. Pin in Tasks 1 and 9.
5. Connected voice with broken decode/backlog/empty transcript must show gaps and truthful notes. Pin in Tasks 7, 9 and 10.

## Files and Verification Commands

New Python responsibilities:
- cost_rates.py: versioned rates and request bounds; budget.py: atomic SQLite ledger, paid-call context and monthly status; budget_api.py: read-only authenticated status.
- transcription.py: gpt-transcribe clips; voice.py: asynchronous dialogue synthesis, re-exported from services.py for compatibility.
- briefings.py/briefing_api.py: explicit briefing lifecycle/snapshots.
- discord_protocol.py: validated IPC; discord_worker.py: bounded stdio RPC/supervision; discord_store.py: attendance/interaction state.
- discord_attendance.py: authorization/lifecycle; discord_audio.py: bounded transcription dispatch; discord_playback.py: speech acknowledgements.
- discord_setup.py: explicit guild registration helper with sanitized child environment.

Node package apps/discord-voice contains package.json/package-lock.json, src/{protocol,audio,transport,gateway,worker,register}.mjs and test/*.test.mjs/local fixtures. Modules can be imported without logging in.

Web adds BudgetPanel.tsx, DiscordAttendancePanel.tsx, their CSS modules, lib/attendance.ts and tests/attendance.test.mjs. Modify existing form, actions, API client/types, home/detail pages, readiness and minutes rendering.

Existing Python modules touched only for specified integration: config.py, services.py, api.py, models.py, repository.py, knowledge.py, playback.py, meeting_service.py, minutes.py, escalations.py, discord_api.py, discord_client.py, recall.py and recall_api.py.

Commands, each checked separately:
    .\.venv\Scripts\python.exe -m pytest <test paths> -q
From apps/discord-voice:
    npm test
From apps/web:
    npm test
    npm run typecheck
    npm run build
Use uv sync --locked and npm ci for reproducible installs. Update lockfiles intentionally when adding dependencies. Tests never load real keys.

## Task 1: Persistent Cost Reservations and Monthly Status

**Files:** Create src/meeting_agent/cost_rates.py, budget.py, budget_api.py and tests/test_budget.py. Modify config.py, api.py, pyproject.toml, uv.lock and .env.example.

**Interfaces:**
- Consume SQLiteRepository._connect(), Settings and an injected clock: Callable[[], datetime].
- CostQuote(model: str, input_tokens: int = 0, output_tokens: int = 0, audio_seconds: float = 0, characters: int = 0); estimate_micro_usd(quote: CostQuote) -> int.
- PaidCallContext(session_id: str | None, operation_id: str, purpose: str); paid_call_context(context) is a synchronous context manager; current_paid_call(purpose: str) -> PaidCallContext. Outside event scopes use a fresh ID, not a shared constant.
- BudgetService.reserve(context: PaidCallContext, quote: CostQuote) -> Reservation; mark_dispatched(id: str) -> None; settle(id: str, usage: CostQuote, provider_request_id: str | None = None) -> None; release_unsent(id: str) -> None; mark_uncertain(id: str) -> None; status() -> BudgetStatus; ensure_available(quotes: Sequence[CostQuote]) -> None.
- Reservation has id/month/reserved_micro_usd. BudgetStatus has month/timezone/reset_at, soft/hard limits, settled/held/available, provider breakdown, warning/last-denial and price_version. Errors: BudgetExceeded, UnknownRate, DuplicateOperation.
- Authenticated GET /budget/status. BudgetExceeded -> HTTP 429 with code monthly_budget_exhausted, reset date and available estimate; invalid prices -> sanitized 503.

- [x] **Step 1: Write failing ledger/rate tests.** Cover concurrent boundary admission, duplicate operation IDs, double settlement, no automatic expiry of uncertain holds, invalid/negative/NaN amounts, upward rounding, once-per-month soft warning, restart persistence and month transition at 2026-10-31T16:00:00Z.

        assert estimate_micro_usd(CostQuote(model="gpt-transcribe", audio_seconds=60)) == 4500
        assert estimate_micro_usd(CostQuote(model="eleven_v4_turbo", characters=1000)) == 40000
        assert estimate_micro_usd(CostQuote(model="gpt-6-luna", input_tokens=100000, output_tokens=1000)) == 10500
        assert concurrent_results.count("admitted") == 1
        assert status.settled_micro_usd + status.held_micro_usd <= 8_000_000
        assert november_budget.status().month == "2026-11"

- [x] **Step 2: Run the existing backend suite once as baseline, then tests/test_budget.py.** Record the baseline and confirm new tests fail for the missing interface/behavior.
- [x] **Step 3: Implement the interfaces.** Rates dated 2026-10-15: transcription USD 0.0045/minute, Luna USD 0.10/M input and USD 0.50/M output, v4 Turbo USD 0.04/1K characters. Round clip duration upward to whole seconds and count all transmitted characters. Use Decimal and integer microdollars. Reject Luna input bounds >272,000 tokens, avoiding unaccounted long-context multipliers. Apply the 10 percent margin to reservation, not settlement.
  Use BEGIN IMMEDIATE for admission and unique operation IDs. A pre-midnight request settles in its original month. Definite unsent work can release; uncertain dispatch remains held indefinitely with attention status. Soft warning counts settled plus held, once per month. Keep budget events independent of a session FK.
  Add validated AI_MONTHLY_SOFT_LIMIT_USD=5, AI_MONTHLY_HARD_LIMIT_USD=8 and AI_BUDGET_TIMEZONE=Asia/Kuala_Lumpur; add tzdata for Windows. No mutation/reset HTTP endpoint.
- [x] **Step 4: Run test_budget.py, test_api.py and test_worker_concurrency.py.** Require all pass; verify unauthorized budget reads fail.
- [x] **Step 5: Commit ledger, route, configuration and tests.**

## Task 2: Guarded OpenAI Transcription, Answers and Full-Transcript Notes

**Files:** Create transcription.py and tests/test_provider_budget.py. Modify services.py, config.py, api.py, meeting_service.py, minutes.py, .env.example, tests/test_grounded_answers.py and tests/test_minutes.py.

**Interfaces:**
- Consume Task 1 budget/context. Retain Brain.answer(session, question, transcript, context) -> BrainAnswer and Brain.summarize_minutes(session, material, *, synthesis: bool) -> str.
- Transcriber protocol: async transcribe(wav: bytes, *, session_id: str, event_id: str) -> str. OpenAITranscriber(settings, budget, *, client=None) implements it.
- OpenAIBrain(settings, budget: BudgetService | None = None, *, client=None) retains Brain methods. Production create_app supplies one shared budget; a live adapter cannot dispatch without it.
- Defaults: openai_transcription_model=gpt-transcribe, openai_model=gpt-6-luna, openai_answer_model=gpt-6-luna. Answer reasoning none/max output 1000; segment summaries low/2000; final synthesis low/4000.
- Conservative input quote: UTF-8 bytes of complete serialized instructions/input/schema plus 2048 wrapper tokens. Reject above 272,000; reserve the full configured output-token limit. No image/tool input.

- [x] **Step 1: Write failing mocked-provider tests.** Assert exact models, no retries, zero calls on cap/key refusal, bounded mono 16 kHz PCM WAV, blank/oversized transcript rejection, billed reasoning usage settlement, timeout/cancellation holds and incomplete output refusal. Pin recent answer context versus full chronological minutes:

        assert request["model"] == "gpt-6-luna"
        assert request["reasoning"]["effort"] == "none"
        assert "EARLY_PRIVATE_SENTINEL" not in request["input"]
        assert any("EARLY_DECISION" in material for material, synthesis in summarizer.calls if not synthesis)
        assert denied_client.calls == []

- [x] **Step 2: Run test_provider_budget.py plus grounded-answer/minutes tests and confirm intended failures.**
- [x] **Step 3: Implement provider-boundary guards.** Validate before reservation; mark dispatched immediately before I/O. AsyncOpenAI uses max_retries=0. Settle response.usage input/output tokens; reasoning is already part of output, not counted twice. Missing usage retains a conservative charge/attention state.
  Validate WAV channels/width/rate, duration <=15 seconds and <=512 KiB before one audio.transcriptions request with a 20-second deadline and output <=10,000 characters. Use only verified supported hint parameters.
  Keep exact answer schemas/evidence validation and 12 utterances/2,000 characters/eight chunks. Retain existing 30,000-character whole-transcript minutes batching and authoritative appendix. Scope paid contexts around ingest, each summary stage and direct coach/preview calls. Remove gpt-5-only reasoning/output heuristics.
- [x] **Step 4: Run test_provider_budget.py, test_grounded_answers.py, test_meeting_service.py, test_minutes.py, test_api.py and test_review_regressions.py.** All network is mocked; early decisions and owner corrections must survive final notes.
- [x] **Step 5: Commit guarded OpenAI adapters and defaults.**

## Task 3: ElevenLabs v4 Turbo Dialogue WebSocket

**Files:** Create voice.py and tests/test_voice_provider.py. Modify services.py, playback.py, api.py, recall.py, config.py, pyproject.toml, uv.lock and .env.example.

**Interfaces:**
- Consume Task 1 budget/context. ElevenLabsVoice(settings, budget: BudgetService | None = None, *, connect=None) exposes async generate(text: str) -> bytes. Preserve services.ElevenLabsVoice export and Voice protocol.
- Production requires the shared budget. Default elevenlabs_model_id=eleven_v4_turbo; preserve configured voice ID.
- Constants: 30-second overall deadline, 8 MiB MP3 limit, 1-5000 input characters, strict base64 and bounded frames.

- [x] **Step 1: Write failing fake-socket tests.** Assert exact URL model/output format, one registered voice, complete text, documented close/flush/final marker, and exact concatenated audio bytes. Reject malformed/error/unfinished/oversized output. Hold reservations after possible text acceptance and timeout. No retries/old Flash endpoint; cap or missing key yields zero connections.
  Name the primary case test_v4_dialogue_finalizes_once; its assertions include:

        assert socket.registration["voices"] == [settings.elevenlabs_voice_id]
        assert socket.inputs[0]["text"] == "Hello."
        assert socket.sent[-1] == {"close_socket": True}
        assert result == b"first-second"

- [x] **Step 2: Run test_voice_provider.py and playback tests; confirm new protocol tests fail.**
- [x] **Step 3: Implement the asynchronous Text to Dialogue adapter.** Use xi-api-key header, voices registration, inputs with voice_id/text, close_socket finalization and audio through is_final; close in finally. Add explicit websockets dependency. Redact remote errors.
  Add paid contexts to every live speech path: /speak, Recall manual say, answers, intro and owner relay. Do not use client.text_to_speech.convert or an ElevenAgents session for v4 Turbo. A post-dispatch failure is possibly charged even if no audio reaches the meeting.
- [x] **Step 4: Run test_voice_provider.py, test_provider_budget.py, test_playback.py, test_recall.py and test_api.py.** Both direct and automatic speech denial must produce zero provider calls.
- [x] **Step 5: Commit the v4 adapter and speech-path coverage.**

## Task 4: Discord Briefings and Additive Session Metadata

**Files:** Create briefings.py, briefing_api.py and tests/test_briefings.py. Modify models.py, repository.py, knowledge.py, api.py and tests/test_knowledge_api.py.

**Interfaces:**
- SessionCreate/View add platform: Literal["google_meet","discord"]="google_meet", purpose: Literal["meeting","briefing"]="meeting", source_briefing_id: str | None and briefing_ready: bool = False. Old rows get Google Meet/meeting defaults. A newly saved briefing is a draft until all requested knowledge has been saved.
- BriefingService(repository, knowledge): create(payload: SessionCreate) -> SessionView; list(query: str = "", limit: int = 25, *, include_drafts: bool = False) -> list[SessionView]; prepare(id: str) -> SessionView; update(id: str, *, title: str, owner_name: str, agent_name: str) -> SessionView; delete(id: str) -> None; snapshot(id: str | None, payload: SessionCreate) -> SessionView.
- Authenticated GET/POST /briefings, PATCH/DELETE /briefings/{id} and POST /briefings/{id}/prepare. Default listing/snapshot accepts ready briefings only; the website can request include_drafts=true to finish a failed upload. Existing /sessions/{id}/knowledge accepts the same text/files for briefings. Metadata edits cannot convert a briefing into attendance.
- snapshot copies full knowledge into a fresh purpose=meeting/platform=discord session, recording source_briefing_id as provenance. The copy is independent of the template's continued existence.

- [x] **Step 1: Write failing migration/briefing tests.** Open a literal old-schema database and preserve its rows/text. Test no-URL creation, supported-file validation, zero provider dispatch, explicit Discord-only autocomplete, edits, unknown/deleted IDs, empty snapshot by omission, full text/locators, duplicate content and later source deletion preserving the meeting copy.
  Name cases test_briefing_copy_survives_source_delete and test_failed_upload_stays_unselectable; assertions include:

        assert meeting.platform == "discord" and meeting.purpose == "meeting"
        assert copied_source.content == original_source.content
        assert copied_chunk.locator == original_chunk.locator
        assert draft.id not in [item.id for item in service.list()]
        assert fake_transport.join_calls == []

- [x] **Step 2: Run test_briefings.py and test_knowledge_api.py; confirm intended failures.**
- [x] **Step 3: Implement additive columns and explicit routes.** Validate platform/purpose combinations; Discord briefings have no URL. Reuse KnowledgeService.copy_into with transaction protection so concurrent template mutation/deletion cannot produce a mixed snapshot. Delete only that briefing's dependent source/chunk/context/event rows in one transaction; retain meeting copies and provenance IDs. Refuse purpose=meeting deletion through this route. Mark ready only after the website completes all requested text/file submissions; failures leave a visible editable draft, excluded from command selection. Retain previously ready versions on an atomic failed edit. Preserve old /sessions clients with optional new fields.
- [x] **Step 4: Run test_briefings.py, test_knowledge.py, test_knowledge_api.py, test_platform_scope.py and test_api.py.**
- [x] **Step 5: Commit briefing lifecycle and migration.**

## Task 5: Playback Router and Participant Identity

**Files:** Modify playback.py, meeting_service.py, services.py, escalations.py, api.py, tests/test_playback.py, tests/test_conversation.py, tests/test_urgency.py and tests/test_grounded_answers.py.

**Interfaces:**
- Playback: async enqueue(session_id: str, text: str, key: str) -> str; async is_live(session_id: str) -> bool; muted(session_id: str) -> bool; available(session_id: str) -> bool; async mute(session_id: str, muted: bool) -> None; async stop(session_id: str) -> None.
- PlaybackRouter(repository, adapters: Mapping[str, Playback]) implements that contract, selecting SessionView.platform and rejecting purpose=briefing. RecallPlayback implements the full contract.
- conversation_gate adds participant_id: str | None = None. Compare IDs when both current/prior entries have IDs; fallback to names only where IDs are absent. Public ingestion never grants notification authorization.

- [x] **Step 1: Write failing fake-adapter tests.** Discord speech must not call Recall; common availability/mute gates must hold; briefings cannot play. Test humans named Alloy, equal display names/different IDs, renamed users/same ID and bot self-ID exclusion.
  Name the primary case test_same_display_name_does_not_merge_speakers; assert:

        assert other_participant_decision.action == "stay_silent"
        assert renamed_same_participant_decision.action == "answer"
        assert recall_adapter.calls == []
        assert discord_adapter.calls == [(sid, "Hello.", "intent-1")]

- [x] **Step 2: Run playback/conversation/urgency tests; confirm intended failures.**
- [x] **Step 3: Implement the router and identity changes.** Remove Recall queue introspection from MeetingService. Use Discord IDs/self flags, retaining the old name fallback only without stable identity. Scope speech paid context to its durable intent key. Preserve freshness, evidence, urgency and owner checks.
- [x] **Step 4: Run test_playback.py, test_conversation.py, test_urgency.py, test_grounded_answers.py, test_owner_replies.py and test_recall.py.**
- [x] **Step 5: Commit shared transport and identity changes.**

## Task 6: Bounded IPC and Worker Supervision

**Files:** Create discord_protocol.py, discord_worker.py, tests/test_discord_worker.py, tests/fixtures/discord_worker_stub.py, apps/discord-voice/package.json, src/protocol.mjs and test/protocol.test.mjs. Modify config.py and .env.example.

**Interfaces:**
- WorkerCommand/WorkerEvent are Pydantic discriminated unions: protocol_version=1, request_id, event type, call generation. Newline-framed UTF-8 JSON limit 12 MiB; WAV <=512 KiB; MP3 <=8 MiB.
- DiscordCommandRequest(interaction_id, command, guild_id, actor_id, channel_id: str | None, briefing_id: str | None).
- AudioUtterance(session_id, generation, event_id, participant_id, speaker, spoken_at, received_at, wav_base64).
- PlaybackAck(session_id, generation, key, state); WorkerHealth(gateway, connection, decoder, receiver, player).
- DiscordWorker(settings, *, process_factory=None): async start() -> None; async run(on_event: Callable[[WorkerEvent], Awaitable[None]]) -> None; async request(command: WorkerCommand, *, timeout: float = 15) -> dict; async close() -> None; health() -> WorkerHealth.
- Commands: join, leave, mute, stop, play, status, interaction_result. Events: ready, command, autocomplete, owner_reply, utterance, audio_gap, playback, health, disconnected. Interaction tokens stay in Node.

- [x] **Step 1: Write failing stub-process and Node protocol tests.** Valid RPC; unknown/extra fields; malformed/oversized input; missing IDs; stale generations; timeout/EOF; bounded logs; child reaping. Assert no OPENAI_API_KEY, ELEVENLABS_API_KEY or backend token in child environment.
  Name cases test_worker_env_and_generation_fence and test_child_reaped_after_eof; assert:

        assert "OPENAI_API_KEY" not in child_env
        assert "ELEVENLABS_API_KEY" not in child_env
        assert handled_old_generation_events == []
        assert process.returncode is not None

- [x] **Step 2: Run test_discord_worker.py and Node npm test.** New interface failures must not open a real Gateway.
- [x] **Step 3: Implement bounded readers/RPC and ESM validation.** Spawn Node without a shell, explicit script path and sanitized environment. Whitelist OS runtime variables and Discord token; deliver nonsecret settings over the initial config frame. Limits: 16 pending RPCs, 64 KiB diagnostics, health heartbeat every five seconds, lost-worker detection at 15 seconds. Expose safe error codes, not arbitrary remote text. close terminates then kills/reaps only its managed child if required.
  Add DISCORD_VOICE_ENABLED=false, DISCORD_NODE_EXECUTABLE=node, DISCORD_FFMPEG_EXECUTABLE=ffmpeg and DISCORD_MAX_ATTENDANCE_SECONDS=14400, with readiness checks. Pure protocol tests run before Task 7's Discord dependencies are installed.
- [x] **Step 4: Run Python worker and Node protocol tests; confirm stub children exit and no login occurs.**
- [x] **Step 5: Commit protocol and bridge.**

## Task 7: Node DAVE Voice, Capture and Guild Interaction Adapter

**Files:** Create apps/discord-voice/src/audio.mjs, transport.mjs, gateway.mjs, worker.mjs, register.mjs, test/audio.test.mjs, transport.test.mjs, gateway.test.mjs and local fixtures. Modify package.json/package-lock.json.

**Interfaces:**
- VoiceTransport({voice, client, ffmpegPath, emit, clock}): async join({sessionId, generation, guildId, channelId}) -> WorkerHealth; async leave({sessionId, generation}) -> void; mute({sessionId, generation, muted}) -> void; stop({sessionId, generation}) -> void; async play({sessionId, generation, key, audioBase64}) -> void; status() -> object.
- AudioCapture({emit, clock, normalize}): subscribe(receiver, member, call) -> void; close() -> void; emits AudioUtterance/audio_gap.
- GatewayAdapter({client, transport, emit}) owns deferred ephemeral interactions, autocomplete, member-state events and raw owner-message forwarding. Filter configured guild and bots/webhooks. Python reauthorizes every command.
- register.mjs exports guildCommands() for /join channel:GuildVoice briefing:string autocomplete, /leave, /mute, /unmute, /stop-speaking, /status and an explicit CLI main. Module imports never log in/register.

- [x] **Step 1: Write failing fake voice/Gateway and local codec tests.** Voice-only channel and permissions; self/bot ID filtering; 15-second nonoverlapping splits; same-user order; 60-second no-human grace; four-hour maximum; bounded reconnect and complete cleanup. Decode a real local Opus fixture through normalizer and assert mono/16 kHz/16-bit WAV and duration. Broken decode must report audio_gap/unhealthy receiver despite a connected socket.
  Name Node cases capture splits at fifteen seconds and decoder failure degrades receive; assert:

        assert.equal(wav.sampleRate, 16000);
        assert.equal(wav.channels, 1);
        assert.equal(wav.bitsPerSample, 16);
        assert.ok(clips.every((clip) => clip.duration <= 15));
        assert.equal(health.receiver, 'failed');

- [x] **Step 2: Run worker npm test and confirm new runtime module/behavior failures.**
- [x] **Step 3: Implement and lock runtime.** Pin discord.js 14.27.0 and @discordjs/voice 0.19.2; resolve/lock opusscript as pure-JS Opus fallback and retain DAVE dependency. selfDeaf=false. Per-user streams close after 700 ms silence and split at 15 seconds. Bound active capture buffers to eight; report overflow gaps. Convert PCM through bounded FFmpeg stdin/stdout, without a shell/file paths; construct a finite WAV header from returned PCM.
  Use createAudioPlayer/createAudioResource for MP3, queue depth two, generation/key deduplication and explicit playback acknowledgements. Complete only on the relevant player completion; stop/mute/leave cancel player and queue. Parent EOF disconnects/exits.
  Intents: Guilds, GuildVoiceStates, GuildMessages, MessageContent. Defer private control replies promptly; autocomplete has a one-second Python deadline and <=25 choices. Unauthorized actors get private refusal. Text content never chooses destinations.
- [x] **Step 4: Run worker npm test including actual local codec fixtures.** Validate dependency reports on the installed Node version without a token. Assert tests never call login or registration REST.
- [x] **Step 5: Commit locked runtime and tests.**

## Task 8: Durable Attendance and Authorized Owner Commands

**Files:** Create discord_store.py, discord_attendance.py, discord_setup.py and tests/test_discord_attendance.py. Modify discord_api.py, discord_client.py, api.py, config.py and .env.example.

**Interfaces:**
- DiscordStore(repository): attendance rows and unique interaction results. Enforce one joining/active/leaving row per guild with a partial unique index. Store session/guild/channel IDs, generation, state, health, mute, start/end and sanitized error.
- DiscordAttendance(settings, repository, briefings, worker, playback, budget): async handle_command(request: DiscordCommandRequest) -> dict; async handle_event(event: WorkerEvent) -> None; async leave(session_id: str, *, reason: str = "owner") -> dict; async recover() -> None; status(session_id: str | None = None) -> dict; choices(query: str) -> list[dict].
- Authenticated GET /sessions/{id}/discord-attendance and POST /sessions/{id}/discord-attendance/{action}, action in leave/mute/unmute/stop-speaking. GET /discord/status gains safe readiness/health.
- Explicit setup CLI uv run python -m meeting_agent.discord_setup runs register.mjs with sanitized environment and configured guild. Do not execute it against Discord in this plan.

- [x] **Step 1: Write failing fake-worker controller tests.** Owner/guild reauthorization; DMs/Stage/bad briefing; readiness before join; duplicate interactions; same-channel idempotency; other-channel refusal; concurrent joins; full/empty snapshots; startup failure; uncertain join timeout reconciled before another join; no Recall row.
  Name cases test_join_is_owner_only_and_idempotent and test_uncertain_join_is_reconciled; assert:

        assert denied["code"] == "owner_required"
        assert repeated["session_id"] == first["session_id"]
        assert len(worker.join_calls) == 1
        assert recall_store.bot(first["session_id"]) is None

- [x] **Step 2: Run test_discord_attendance.py, test_briefings.py and test_discord.py; confirm intended failures.**
- [x] **Step 3: Implement lifecycle/readiness.** Persist joining intent before RPC, snapshot before voice starts. Require configured provider/Discord keys, Node/FFmpeg/decoder/worker readiness and budget headroom for intro plus first bounded operation. Reconcile uncertain ownership through worker status before another join. Successful private response includes the dashboard link.
  Bind the Discord playback adapter through the common router and lifespan. Voice enabled -> Node owns Gateway; voice disabled -> existing Python Gateway supports owner replies. No automatic registration/join/rejoin. Recover unfinished attendance/speech as interrupted/attention. No-briefing sessions use existing default names. Web operator-token controls are permitted; no public IPC endpoint.
- [x] **Step 4: Run test_discord_attendance.py, test_discord_worker.py, test_briefings.py, test_discord.py and test_api.py.** Without keys startup must not connect/start a real child and Meet/knowledge must stay usable.
- [x] **Step 5: Commit attendance and explicit setup tooling.**

## Task 9: Shared Voice Pipeline, Owner Relay and Budget Stop

**Files:** Create discord_audio.py, discord_playback.py and tests/test_discord_voice_flow.py. Modify discord_attendance.py, api.py, meeting_service.py, minutes.py, escalations.py and tests/test_owner_replies.py.

**Interfaces:**
- Consume Tasks 1-8's ledger, transcriber, meeting/router, worker, store and controller.
- DiscordAudio(transcriber: Transcriber, meeting: MeetingService, attendance: DiscordAttendance): async submit(event: AudioUtterance) -> bool; async close_session(session_id: str, generation: str) -> None; async close() -> None.
- DiscordPlayback(store: DiscordStore, worker: DiscordWorker, voice: Voice) implements Task 5's contract; async acknowledge(event: PlaybackAck) -> None updates durable speech/owner-reply state.
- MinutesService adds pending_budget and deterministic appendix-only preservation when model work is blocked. Its async _stage(session_id: str, fingerprint: str, stage_key: str, material: str, *, synthesis: bool) -> str caches successful stage results in a minutes_stages table keyed by session/fingerprint/stage_key, with attempt IDs linking to paid operations. Uncertain attempts retain their charges; an explicit retry creates a new attempt without rerunning successful stages. A manual minutes request retries explicitly; polling/rollover does not.
- handle_event normalizes owner message events into the existing OwnerReply model and calls EscalationService.receive_owner_reply. Python's existing user/guild/thread checks remain authoritative.

- [x] **Step 1: Write failing full-flow tests using real services/fake worker/providers.** Cover join -> transcript -> grounded spoken answer; unknown -> speaker-confirmed urgency -> one question thread -> authorized owner reply -> one associated playback. Cover empty knowledge, unrelated/edited/non-owner replies, same-name participants, mute/cancellation/stale speech, wrong generations/late acknowledgements, budget denial, worker/parent crash, empty calls and capture gaps.
  Assert paid calls have ledger provenance, duplicate events add no provider calls, midnight settlement retains the original month, and denied work dispatches no network request.
  Name cases test_urgent_owner_reply_spoken_once and test_hard_cap_leaves_without_paid_notice; assert:

        assert len(notifier.question_messages) == 1
        assert spoken_owner_messages == ["Aloy says: The budget is 500."]
        assert attendance.status(sid)["state"] == "budget_stopped"
        assert provider_calls_after_denial == []
        assert minutes.status(sid)["state"] == "pending_budget"

- [x] **Step 2: Run test_discord_voice_flow.py; confirm intended integration failures.**
- [x] **Step 3: Implement bounded dispatch and routing.** Queue eight waiting items and run two STT calls concurrently. Maintain each speaker's sequence when STT responses finish out of order. Validate generation before STT/ingest/playback; retain speech timestamps and explicit overflow/failure gaps. Emit only final successful MeetingUtterance(platform="discord"); reject bot/self inputs before spending.
  Send intro through the common voice guard and require receiver readiness plus valid intro acknowledgement before claiming full health. Speech intent/generation/question identity must match; an uncertain acknowledgement cannot trigger regeneration.
  On BudgetExceeded at an active Discord paid pipeline boundary, cancel unstarted work, mark budget_stopped and leave without new paid speech. Preserve transcript/questions/replies and pending_budget notes, including already generated partial sections. Cache successful summary stages for explicit retry; do not automatically rerun possibly charged stages. Normal departure uses full-transcript finalization. Discard all raw audio after bounded processing.
- [x] **Step 4: Run test_discord_voice_flow.py, test_owner_replies.py, test_minutes.py, test_personal_agent_acceptance.py, test_review_regressions.py and worker npm test.** No stale speech may reach a departed/new call; uncertain delivery remains visible.
- [x] **Step 5: Commit the complete offline-tested attendance flow.**

## Task 10: Website Briefings, Platform Status and Budget Visibility

**Files:** Create apps/web/components/BudgetPanel.tsx, BudgetPanel.module.css, DiscordAttendancePanel.tsx, DiscordAttendancePanel.module.css, lib/attendance.ts, tests/attendance.test.mjs and tests/test_discord_web_contract.py (backend tests directory). Modify apps/web/lib/api-types.ts, backend.ts, meeting.ts, app/actions.ts, app/page.tsx, app/meetings/[id]/page.tsx, components/SendForm.tsx, Readiness.tsx, MeetingPanels.tsx, tests/meeting.test.mjs and relevant CSS.

**Interfaces:**
- backend gains budgetStatus(), listBriefings(), createBriefing(body), updateBriefing(id, body), deleteBriefing(id), discordAttendance(id) and discordControl(id, action).
- Session TS mirrors platform/purpose/source_briefing_id/briefing_ready. DiscordAttendance stays separate from Bot. Finalization includes pending_budget.
- attendanceView(session: Session, bot: Bot | null, discord: DiscordAttendance | null) -> {label, detail, tone, live, canSpeak, canLeave}. A briefing is never live/dispatchable.
- saveDiscordBriefing(prev: ActionState, form: FormData) saves names/text/files and prepares the completed briefing without launching. backend gains prepareBriefing(id) and listBriefings({includeDrafts: true}) for draft recovery. Preserve existing Meet retry semantics. BudgetPanel accepts server-fetched BudgetStatus; no provider credentials or billing mutations in props.

- [x] **Step 1: Write failing state/contract tests.** Discord can be live with no Recall Bot; briefings cannot be active; old history remains readable; Discord details do not request /bot; reset/warning/held amounts are truthful; pending_budget never says minutes written; Discord save never calls Recall. Include no-key authoring and actionable cap errors.
  Name the primary case Discord attendance is live without Recall; assert:

        assert.equal(attendanceView(discordSession, null, activeDiscord).live, true);
        assert.equal(attendanceView(briefing, null, null).canSpeak, false);
        assert.equal(attendanceView(briefing, null, null).live, false);

- [x] **Step 2: Run web npm test and test_discord_web_contract.py; confirm intended failures.**
- [x] **Step 3: Implement focused UI in the existing visual style.** Meet retains required URL/scheduling/consent. Discord saves a briefing without URL/schedule, adds requested knowledge, then calls prepare; failed uploads remain labelled drafts and excluded from slash choices. Display /join instructions. List briefings separately, allow metadata edit/delete and preserve meeting copies.
  Branch detail loads and server actions by platform; show receiver health/gaps, mute/unmute/stop/leave and stored knowledge/questions without fabricating a Bot. BudgetPanel shows local month/reset, USD 5/8, settled/held/available, provider breakdown and excluded costs. Surface soft warning without Discord pings. pending_budget displays explicit Generate notes. Preserve server-only tokens and sanitized actionable errors.
- [x] **Step 4: Run web npm test, npm run typecheck, npm run build, then briefing/web contract backend tests.** Verify with a local fake-backed browser when needed: both creation choices, a Discord record, warning/block states and saved notes. No real provider credentials.
- [x] **Step 5: Commit website integration and contract tests.**

## Task 11: Reproducible Setup, Full Verification and Independent Review

**Files:** Modify README.md, .env.example, docs/BACKEND_HANDOFF.md, docs/IMPLEMENTATION_VERIFICATION.md and this plan. Add docs/DISCORD_VOICE_SETUP.md and tests/test_discord_setup_contract.py.

**Interfaces:** No new runtime contract. Setup describes the exact model IDs, guild registration, minimal permissions/intents, Node/FFmpeg, enable flag, briefing syntax, budget scope and remaining live-call checks.

- [ ] **Step 1: Write failing setup-contract tests.** Missing keys never log in/register/join/call providers. Run the CLI with incomplete configuration, fake subprocess/REST transports and sentinel secrets; assert safe failure before external I/O. Review documentation/configuration agreement manually rather than adding source-string mirror tests.
  Name the primary case test_registration_requires_config_without_network; assert:

        assert result.returncode != 0
        assert discord_http_calls == []
        assert gateway_login_calls == []
        assert "secret-token-value" not in result.stderr

- [ ] **Step 2: Run test_discord_setup_contract.py; confirm the new safe-CLI behavior fails for the intended reason.**
- [ ] **Step 3: Finish setup/operational docs.** Include locked installs, View Channel/Connect/Speak plus existing escalation/thread/history permissions, Message Content setup, FFmpeg prerequisite, no automatic rejoin, uncertain charges and pending-budget notes. List credentials to configure locally later without asking for secrets in chat.
  Mark real provider compatibility, live DAVE receive and transcription accuracy unverified until a separately authorized private test. Preserve earlier foundation review limitations.
- [ ] **Step 4: Run fresh full verification, checking each exit code.** Backend: uv sync --locked then full pytest suite. Worker: npm ci then npm test. Web: npm ci, npm test, npm run typecheck, npm run build. Run git diff --check; reject unrelated/generated/secret artifacts. Record exact results and real-call limits.
- [ ] **Step 5: Request one independent whole-branch review under Native execution using superpowers:requesting-code-review.** Supply approved spec/plan, base 9943ca3c78db53dafdcd7d1b68f9fa8985df8c0e and exact implemented head; use the most capable available reviewer as that workflow requires. Do not delegate implementation tasks. Focus on authorization, correctness, concurrency, cost bypass/uncertain charges, DAVE receive, recovery/cleanup and regressions. Validate feedback through receiving-code-review, fix reproduced issues and rerun affected checks. If independent review is unavailable, report incomplete review explicitly.
- [ ] **Step 6: Commit documentation/validated fixes and present concrete diff/results.** Use finishing-a-development-branch for integration; attach any created PR. Offline success does not authorize deployment, live command registration or a real meeting.

## Dependency Order and Self-Review

Execute Tasks 1-11 in order with Native execution. Tasks 2-3 share the ledger/context; Task 4 defines briefing snapshots; Task 5 defines shared playback/identity; Tasks 6-7 define worker transport; Tasks 8-9 bind attendance and policy; Task 10 exposes the complete flow; Task 11 verifies/reviews the branch.

Coverage: model/context bounds Tasks 2-3; briefing migration Task 4; identity/routing Task 5; IPC/audio limits Tasks 6-7; slash authorization/readiness/recovery Task 8; urgency/owner replies/hard stop/full notes Task 9; website/budget visibility Task 10; setup and unverified real-call checks Task 11. Review Focus cases are pinned to their owning task tests.

Plan approved on 15 October 2026. Native implementation proceeds without live provider calls or Discord registration/joins; one whole-branch review gates final completion.
