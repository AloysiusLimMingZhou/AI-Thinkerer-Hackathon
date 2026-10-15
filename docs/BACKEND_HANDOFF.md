# Meeting Agent backend handoff

The Next.js dashboard is connected through `apps/web/lib/backend.ts` and Server Actions. This is a single-operator SQLite app: run one backend process, protect the frontend before public deployment, and keep provider secrets server-side.

## Run and authenticate

Use the locked installation in README. Root `.env` supplies backend settings; `apps/web/.env.local` supplies `ALLOY_BACKEND_URL` and the same `BACKEND_API_TOKEN` to the Next.js server. All private endpoints require `Authorization: Bearer <token>`. The public entrypoints are health/docs, Google OAuth callbacks, signed Recall webhooks and scoped Recall media URLs. Avoid logging callback codes or media capability query strings.

Before upgrading an existing database, stop the backend and back up the database plus any SQLite WAL/SHM files. Startup creates new tables, adds session platform/purpose/briefing fields and the transcript participant column without removing historical records. Keep the backup for rollback; older code does not understand the new processing state.

## Main API

| Method and path | Purpose |
| --- | --- |
| POST /sessions; GET /sessions; GET /sessions/{id} | Create/list/read meeting records |
| POST /sessions/{id}/knowledge | Multipart `text` and repeated `files` fields; 201 with `sources` and `duplicates` |
| GET /sessions/{id}/knowledge | Normalized source metadata, filename, character count, preview |
| POST /sessions/{id}/context | Legacy JSON `notes`; indexed through the same knowledge service |
| POST /sessions/{id}/context/import | Explicit Google Calendar context import; no Slack/Drive import |
| POST /sessions/{id}/utterances | Private preview, shared grounded decisions; no audio or notifications |
| POST /sessions/{id}/coach | Private grounded suggestion; no notification or automatic speech |
| POST /sessions/{id}/speak | Explicit operator TTS preview; returns MP3 |
| POST /sessions/{id}/bot | Google Meet dispatch; `idempotency_key`, `consent_confirmed: true`, optional aware `join_at` |
| GET /sessions/{id}/bot | Persisted transport state; queued does not mean admitted |
| POST /sessions/{id}/bot/say | Explicit operator speech in a live call |
| POST /sessions/{id}/bot/leave | Leave/cancel using Recall |
| POST /sessions/{id}/mute | JSON `muted`; muting also stops queued/playing output |
| POST /sessions/{id}/stop-speaking | Cancel queued/playing output |
| GET /sessions/{id}/transcript; GET /sessions/{id}/events | Final transcript when available, otherwise live captions; audit events |
| GET /sessions/{id}/questions | Persisted questions, delivery states/errors and Discord IDs |
| POST /sessions/{id}/minutes; GET /sessions/{id}/minutes | Generate/read Markdown minutes |
| GET /sessions/{id}/finalization | `idle`, `processing`, `ready`, `failed` or `pending_budget`, independent of bot liveness |
| GET /recall/status; GET /discord/status | Configuration names and transport readiness; no secret values |
| GET /recall/jobs | Recall processing/recovery status |

Knowledge POST rejects excess bytes with 413; unsupported or unreadable documents with 422; unknown sessions with 404. All-or-nothing extraction happens before saving a mixed batch. Limits and supported formats are in README. Existing sources are backfilled idempotently, including copied Calendar template knowledge. Source text is retained in full, alongside chunk provenance; the UI preview is bounded.

Decisions are `stay_silent`, `answer` or `defer`. Supported factual answers require valid retrieved chunk IDs and exact quoted excerpts; this validates provenance, not a mathematical guarantee of semantic correctness. Transcript and generated answers are context for follow-ups, not owner-supplied factual evidence. Unknown/defer responses use the fixed urgency prompt.

Stable provider event IDs deduplicate decisions and speech intents. Only finalized, current, non-self captions can produce live speech. Ordinary answers use a bounded queue. PlaybackRouter selects Recall or Discord by the session platform. Briefings cannot play. Recall cancellation is checked by its media page; Discord confirms generation/key-bound player acknowledgements.

## Recall configuration

Set `RECALL_REGION=ap-northeast-1`, `RECALL_API_KEY`, `RECALL_WEBHOOK_VERIFICATION_SECRET`, `PUBLIC_API_BASE_URL`, `BACKEND_API_TOKEN`, `OPENAI_API_KEY`, and `ELEVENLABS_API_KEY`. The public origin must be stable HTTPS and reach this backend. Optional `RECALL_MEDIA_BASE_URL` is a warning-free alternate origin reaching the same backend.

Subscribe the workspace webhook `/webhooks/recall` to `bot.status_change`, `transcript.done`, `transcript.failed`, `calendar.update`, and `calendar.sync_events`. Bot creation config already subscribes the real-time endpoint to `transcript.data`. Signed requests use raw-body HMAC and a five-minute timestamp tolerance. Ingestion commits a durable job and returns 202; network/model work runs later.

A completed transcript is downloaded from a validated storage host and saved locally. Multiple artifacts are combined chronologically and duplicate utterances removed. Minutes process all final text, Q&A and tracked questions. Each model segment is at most 30,000 text characters, with hierarchical synthesis. The appendices preserve exact questions and accepted owner text. Partial live captions are excluded.

After call departure, the UI polls finalization through completion or failure. A final transcript absent for five minutes becomes a visible failure; inspect Recall and retry after it arrives. Model failures and interrupted finalization are visible and can be retried with POST minutes. Accepted post-call owner replies schedule refreshed minutes without reopening a call.

## Optional calendars

Explicit Google OAuth context import is distinct from Recall Calendar V2 scheduling. Configure Google client settings/encryption only when using that import. Drive import and connector refresh-token renewal remain absent.

For Recall Calendar V2, configure the dedicated Google OAuth application using Recall's setup instructions, a stable public callback `/recall/calendar/callback`, and the exact `RECALL_CALENDAR_CALLBACK_URI` returned by setup. Complete Google mailbox consent and Recall synchronization before testing. Do not commit client JSON or tokens.

```text
POST /recall/calendars {"calendar_id":"Recall UUID","template_session_id":"session UUID"}
GET /recall/calendars
GET /recall/calendars/{id}/events
PATCH /recall/calendars/{id} {"auto_join":true,"consent_confirmed":true}
POST /recall/calendars/{id}/sync
DELETE /recall/calendars/{id}
```

Auto-join is off by default. Future Google Meet events exclude cancelled/deleted/declined events. Each new event receives a snapshot of full template knowledge; later template edits do not alter existing event sessions. Calendar writes/invitation acceptance are not implemented.

## Recovery and verification

Discord voice, /join and recovery are described in [DISCORD_VOICE_SETUP.md](DISCORD_VOICE_SETUP.md). Meet notifications remain documented in [DISCORD_SETUP.md](DISCORD_SETUP.md).

Inspect `needs_attention` before retrying ambiguous writes. For a verified existing Recall bot, POST `/sessions/{id}/bot/reconcile` with its `bot_id`; Recall metadata must match. Do not resubmit an uncertain Create Bot blindly. Failed or interrupted speech is not automatically replayed; use explicit operator speech after checking the call. Audio expires after 60 seconds; media access expires eight hours after intended join.

Tests fake providers and never join meetings or ping people. Live-readiness checks require an operator-configured private call. This phase has not verified live admission, audible playback, external webhook delivery, Google consent or real Discord permissions. Optional scripts `preflight_live.py` and `eval_conversation.py` use provider credits when explicitly run.

There is no production multi-user auth, encryption-at-rest for meeting content, retention policy, pagination or horizontal scaling. Speech is sequential text-to-MP3, not full-duplex/barge-in audio.


## Discord attendance, briefings and budget

| Method and path | Purpose |
| --- | --- |
| GET/POST /briefings | Explicit Discord templates; GET ready-only unless include_drafts=true |
| PATCH/DELETE /briefings/{id} | Edit metadata/delete template, preserving snapshots |
| POST /briefings/{id}/prepare | Mark a successfully authored draft selectable |
| GET /sessions/{id}/discord-attendance | Separate attendance/health/intro/mute state; no Recall Bot |
| POST /sessions/{id}/discord-attendance/{action} | Operator controls: leave, mute, unmute, stop-speaking |
| GET /budget/status | Local month/reset, thresholds, settled/held/available, warnings, provider estimates |

Sessions have platform=google_meet|discord and purpose=meeting|briefing. Old rows migrate to google_meet/meeting. Discord briefings have no URL, never dispatch or generate meeting work, and snapshot full knowledge into a fresh meeting. Slash commands are owner/guild restricted and durably deduplicated. The Node worker has bounded versioned stdin/stdout IPC, no AI credentials, no public port and no automatic rejoin.

The provider defaults are gpt-transcribe, gpt-6-luna (answers and minutes), and eleven_v4_turbo (dialogue WebSocket). Every paid operation shares BudgetService, including previews. Budget denial returns HTTP 429 with detail.code=monthly_budget_exhausted and reset_at. Unknown model rates fail closed. No provider retries are automatic. Possibly charged operations remain held after timeouts/crashes.

A Discord hard-stop preserves transcript/appendices and pending_budget finalization. Successful minutes sections are cached per session/fingerprint/stage; explicit retry creates a new reserved attempt only for missing stages. Failed/uncertain stages and budget rollover never retry automatically. Normal Meet and Discord departure can schedule new finalization; already failed/budget-blocked notes need explicit retry. Late owner replies remain saved.

When DISCORD_VOICE_ENABLED=true the supervised Node process is the sole Gateway owner; otherwise discord.py supports Meet owner replies. Python remains the authorization, notification, answer and billing authority. Worker loss interrupts attendance and speech; inspect attention states before any replay. Setup and genuine-call acceptance remain operator work.
