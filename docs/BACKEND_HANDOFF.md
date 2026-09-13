# Alloy backend: frontend integration contract

This is a **single-operator hackathon backend**, not a multi-tenant service. The frontend
is independently owned. No frontend files were changed by this integration.

## Run and authenticate

From the repository root: `uv sync`, configure `.env`, then `uv run python main.py`.
The server binds to `127.0.0.1:8000`. Use one process/worker for this SQLite prototype.
Interactive API: <http://localhost:8000/docs>. Click **Authorize** and enter
`BACKEND_API_TOKEN` from your local `.env`. Do not paste it into GitHub or commit it.

Every private HTTP request requires `Authorization: Bearer <BACKEND_API_TOKEN>`.
There is no unauthenticated development bypass. `/health`, API documentation,
signed Recall webhooks, OAuth callbacks and scoped bot-media routes are public entrypoints
with their own controls. Keep proxy access logs off/redacted: callback query strings
contain authorization codes, and bot-media URLs contain a scoped capability token.

Recommended frontend: Next.js server routes proxy requests to this backend and inject
the backend token server-side. Never put the shared token or vendor keys into
`NEXT_PUBLIC_*`, committed frontend code, or browser localStorage. A public frontend
proxy still needs its own user authentication. Configure `CORS_ORIGINS` for the exact
local UI origin if making direct development requests.

## Frontend teammate: wire the demo

The current `apps/web/lib/data.ts` still returns fixtures; pulling this backend does
not automatically connect the UI. Keep the existing design and replace fixture reads
with the real endpoint flow below. For this demo, skip calendar/account linking and
start with a meeting URL plus briefing notes.

In the frontend's ignored `apps/web/.env.local`, configure server-only variables:

```dotenv
ALLOY_BACKEND_URL=https://your-backend-tunnel.example
BACKEND_API_TOKEN=replace-with-the-operator-token-shared-privately
```

Use `http://127.0.0.1:8000` only if the backend runs on the same machine as the
Next.js server. Otherwise ask the backend operator for the current HTTPS tunnel URL.
Keep the backend and both tunnels running during the demo. These environment names
are the proposed proxy contract, not an already-implemented frontend integration.
The Next.js server proxy must attach `Authorization: Bearer ...`, use `cache: "no-store"`,
preserve backend status codes, and never return credentials to the browser. Protect
the proxy with frontend authentication before exposing it publicly; for a supervised
local demo, bind the frontend to localhost.

Minimum UI: create a session, save notes, launch with explicit consent, poll bot
status/transcript/events, show answers, send an explicit `/bot/say` message, and leave.
Use a new session for every new bot test, even when reusing the same meeting URL.
The delegate defaults to **Alloy** and speaks with **Charlie**. Direct addresses such
as "Alloy, what's our budget?" and "Hi Alloy" work; generic "AI notetaker" and isolated
third-person mentions such as "what does Alloy think?" do not. For the Alloy/Aloy
name pair only, direct-address ASR spelling "Aloy" is accepted too; this is a limited
heuristic, not general name/entity recognition. A bare name can carry to the same
speaker's question within six seconds. After a reply, that same speaker can follow up
without repeating the name for 25 seconds, provided no other participant intervenes
and the gap between captions is at most 30 seconds. Unknown speakers cannot carry a
conversation window. A manual `/bot/say` message does not require the wake name.

The API and database schema are unchanged. Continue sending frontend document text
via `POST /sessions/{id}/context`. To include communication style and owner preferences
even without keyword overlap, use note `source: "owner-profile"` (also accepts
`"profile"` or `"briefing"`). Use authenticated operator-provided notes, e.g.:

```json
{"notes":[{"source":"owner-profile","title":"How Aloy communicates","content":"Aloy uses he/him. Prefers casual, concise English. Explain approved decisions; do not authorize spending or make new commitments."}]}
```

No document parsing/upload UI was added: the frontend still supplies extracted text.
Notes are reference data, not unrestricted system instructions. The delegate has no
message-sending, notification, approval or scheduling tools in its conversational
answer path. Prior generated replies now accompany captions in model context, without
altering the raw transcript API. Citations list selected reference notes; they are not
model-verified, sentence-level attribution.

Local provider smoke test (uses API credits, creates no meeting bot):
`uv run python scripts/preflight_live.py`. It saves generated audio under ignored `data/`.
This tests answer generation and TTS only; verify admission, live transcription and
audible playback separately in a meeting. Run `uv run python scripts/eval_conversation.py`
for opt-in live conversational checks, including provider timing (uses API credits,
never launches a bot or plays into a meeting).

`OPENAI_ANSWER_MODEL=gpt-4.1-mini` selects the fast spoken-answer/coach model;
`OPENAI_MODEL=gpt-5-mini` remains the minutes model. `ELEVENLABS_MODEL_ID=eleven_flash_v2_5`
uses Flash speech with the same Charlie voice. Existing explicit environment values
still take precedence; restart after changing `.env`. This remains a sequential
transcript-to-text-to-audio pipeline, not full-duplex streaming. One follow-up reply can
queue behind current audio; a further addressed utterance is skipped with an explicit
`agent.decision` reason `reply queue full` to avoid a backlog of stale speech.
No claim of subsecond end-to-end meeting response is made.

## Required configuration

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Responses API access and available API credit |
| `ELEVENLABS_API_KEY` | Text to Speech permission and available credits |
| `ELEVENLABS_VOICE_ID` | Authorized voice; default Charlie ID is in `.env.example` |
| `RECALL_API_KEY` | REST key for Alloy Bot, Tokyo |
| `RECALL_WEBHOOK_VERIFICATION_SECRET` | Workspace verification secret, not an arbitrary endpoint secret |
| `RECALL_REGION` | Must remain `ap-northeast-1` |
| `PUBLIC_API_BASE_URL` | Stable public HTTPS backend/tunnel address |
| `RECALL_MEDIA_BASE_URL` | Optional separate HTTPS origin for the bot webpage, serving this same backend; defaults to the public API origin |
| `BACKEND_API_TOKEN` | Random shared backend operator secret |
| `OAUTH_ENCRYPTION_KEY` | Random key for optional context-connector tokens |

ElevenLabs needs **Text to Speech: Access**. **Voices: Read** is useful for future voice
selection but the current fixed-voice path doesn't list voices. Other permissions are
unnecessary. Keep leak auto-disable enabled; use a credit cap. No ElevenAgents or
ElevenLabs STT key permission is required: Recall performs transcription.

The Recall MCP login is a developer connection, **not the runtime API key**, and is
not authorization to read the user's Google Calendar. Google requires a separate
OAuth client and browser consent. No Google/Zoom/Teams account password is needed
for this guest-bot implementation. Meeting hosts may still need to admit the bot
and grant recording permission; organization policies can prevent admission.

## Frontend journey and endpoints

1. `GET /recall/status`: show missing configuration names (never secret values).
   `configured=true` means variables exist, **not that live meeting tests passed**.
2. `POST /sessions`:

   ```json
   {"title":"Daily standup","owner_name":"Aloy","agent_name":"Alloy","meeting_url":"https://meet.google.com/xxx-yyyy-zzz"}
   ```

3. `POST /sessions/{id}/context`:

   ```json
   {"notes":[{"source":"past-meeting","title":"Project brief","content":"Approved facts, previous decisions and current tasks."}]}
   ```

4. `POST /sessions/{id}/bot` returns **202** (queued, not joined):

   ```json
   {"idempotency_key":"a-unique-key-for-this-meeting","consent_confirmed":true}
   ```

   Omit `join_at` to join immediately; or supply a timezone-aware ISO timestamp at
   least ten minutes ahead, up to 28 days away. Ask the operator to confirm the
   specific meeting and participant notice before submitting. The bot is visibly
   named `Alloy (AI delegate)` and sends a transcription/AI notice in meeting chat.
   Reuse the SAME key when retrying the same submission. A session supports one
   bot launch; a genuinely different meeting needs a new session.

5. Poll **local backend state**, not Recall: `GET /sessions/{id}/bot` and
   `GET /sessions/{id}/events?after=<last sequence>`. Display queued, retrying,
   scheduled, joining_call, in_waiting_room, in_call_recording, fatal, call_ended,
   done and needs_attention. Unknown states should still be shown verbatim.
   Do not display “joined” just because launch returned 202.
6. `GET /sessions/{id}/transcript`: stored live captions; after `transcript.done`,
   returns the downloaded, persisted final transcript. No ephemeral signed download
   URL is passed to the UI. `GET /sessions/{id}/minutes`: 404 until ready.
   `POST /sessions/{id}/minutes` manually generates/retries minutes from stored data.
7. `POST /sessions/{id}/bot/leave`: cancel a queued/scheduled bot or request departure.

Optional controls:

- `POST /sessions/{id}/coach` with `latest_message` and optional `objective`: private
  text suggestion. It is **not automatically spoken** into the meeting.
- `POST /sessions/{id}/speak` with `text`: returns MP3 to the caller only.
- `POST /sessions/{id}/bot/say` with `text`: explicitly queue speech into a live meeting.
- `GET /sessions/{id}/stream` is a WebSocket route (connect with `ws://` or `wss://`).
  A trusted server can send an Authorization header; a dev browser can supply
  `bearer.<BACKEND_API_TOKEN>` as its WebSocket subprotocol. Prefer a server proxy
  for the frontend; HTTP event polling is also supported.

Event types include `transcript.utterance`, `agent.decision`, `voice.queued`,
`voice.played`, `voice.failed`, `bot.status`, `transcript.saved`, and `minutes.generated`.
Voice generated/queued is not proof the meeting heard it. `voice.played` means the
media page reported playback completion; only a live participant can confirm sound
actually reached the call.

`agent.decision` now also reports silence reasons and the triggering `utterance_id`.
Answered decisions include `answer_ms`; `voice.queued` adds `answer_ms`, `voice_ms`,
and `response_ready_ms` (model start to ready audio; excludes transcription/network
delivery before model start and meeting playback). All additions are optional event
payload fields; keep existing frontend event handling tolerant of extra fields.
`voice.queued.replies_ahead` reports the pending audio count before that reply was added.

## Calendar V2 setup and scheduling

Before enabling automatic joins, finish Recall's Google Calendar V2 onboarding:

1. Use a stable public backend address. Set `PUBLIC_API_BASE_URL` and expose this
   server over HTTPS. A random temporary URL is not suitable for saved OAuth setup.
2. Start Recall MCP calendar setup for `google_calendar` in Alloy Bot (Tokyo), using
   `PUBLIC_API_BASE_URL/recall/calendar/callback` as the production redirect URI.
3. Set `RECALL_CALENDAR_CALLBACK_URI` to the **exact** `regional_callback_uri`
   returned by the setup action, restart, and verify its forwarding probe. The route
   forwards only `state` plus one of `code`, `error`, or `recall_calendar_setup_probe=1`.
4. Follow the action's exact Google Cloud project/API/branding/audience/scopes/client
   instructions. Download the dedicated Web OAuth client JSON outside source control
   and import it into Recall through the setup flow. Do not paste the JSON into chat.
5. Authorize the Google mailbox through the returned browser consent URL. Wait for
   Recall to report the calendar connected, full sync complete, and ready for testing.
   External Google apps in Testing normally have seven-day Calendar refresh tokens;
   production publishing/verification is a separate milestone.

Once connected, attach the Recall calendar and opt in through this backend:

```text
POST /recall/calendars
  {"calendar_id":"<Recall UUID>","template_session_id":"<briefing session UUID>"}
GET /recall/calendars
GET /recall/calendars/{calendar_id}/events
PATCH /recall/calendars/{calendar_id}
  {"auto_join":true,"consent_confirmed":true}
POST /recall/calendars/{calendar_id}/sync
DELETE /recall/calendars/{calendar_id}
```

Auto-join is **off by default**. Enabling it selects future supported meeting links
on that calendar, excluding deleted/cancelled/declined events. There is no invitation
acceptance, calendar write, or arbitrary join based on text in a meeting note.
Each event gets a meeting session and a snapshot of the template session's notes.
Subsequent template edits are not automatically copied into already-created sessions.
Schedule changes use Recall's Calendar V2 deduplication mechanism. Disabling auto-join
queues unscheduling; inspect jobs to ensure it succeeded. Disconnect calls Recall's
calendar-delete API, which cleans up its future scheduled bots. This is separate
from disconnecting the optional `/integrations/google` context-import connector.

## Recall webhook configuration

Dashboard endpoint: `PUBLIC_API_BASE_URL/webhooks/recall`. Subscribe to `bot.*`,
`recording.done`, `recording.failed`, `transcript.done`, `transcript.failed`,
`calendar.update`, and `calendar.sync_events`. Subscribe to `transcript.data` in
the create-bot `recording_config.realtime_endpoints` (already done in code), not in
the dashboard. This workspace uses the workspace verification secret for both.

The receiver verifies HMAC signatures over raw bytes and enforces five-minute
timestamp tolerance before parsing or storing. It commits a deduplicated job then
returns 202; the worker performs AI/network work separately. Recall API rate-limit
and transient retry delays are stored, including `Retry-After` plus jitter.

Use `GET /recall/jobs` to inspect retries and `needs_attention`. Ambiguous Create Bot
timeouts and interrupted external work are **not blindly replayed**, to avoid duplicate
bots or speech. Inspect Recall's bot explorer. If the bot exists, use
`POST /sessions/{id}/bot/reconcile` with `{"bot_id":"<verified UUID>"}`; its Recall
metadata must match the local session. If no bot exists, verify that fact before
creating a new session. Failed speech is not automatically replayed; `/bot/say`
is an explicit operator action. Stored transcript/minutes work can be retried manually.

## What is verified / what remains

Automated tests use fake Recall, OpenAI and ElevenLabs transports. They cover API
authentication, webhook validation and duplicate handling, durable launch intents,
voice outbox claim/ack, uncertain-create behavior, rate limits, calendar opt-in,
rescheduling and unscheduling. Run `uv run pytest -q`.

Live-read verification completed against Recall Tokyo using the purpose-named REST
key. **No live meeting, live OpenAI generation, ElevenLabs synthesis, public webhook
delivery, or Google Calendar authorization has been verified yet.** Finish configuration
and authorize a specific private test call before claiming end-to-end readiness.

Known prototype boundaries: one trusted operator and one worker; no per-user auth,
billing, encryption-at-rest for meeting content, retention policy, transcript pagination,
or horizontal scaling. Context connector refresh-token renewal is not implemented.
Google Drive import is not implemented. Live speech waits for a finalized utterance,
then OpenAI + TTS: it is not full-duplex, streaming voice-to-voice or barge-in capable.
Output Media displays a simple AI-delegate video card as well as playing audio.
If a free ngrok endpoint shows its browser warning, use a warning-free media origin
via `RECALL_MEDIA_BASE_URL`. A temporary Cloudflare quick tunnel is only for a live,
supervised direct-link demo; keep it running and never register it for calendar OAuth.
The stable ngrok origin can continue receiving the non-browser webhook requests.
Audio expires after 60 seconds; media access expires eight hours after intended join.
Do not expose a production multi-user app on top of the shared demo token.

Primary integration references:
[Output Media](https://docs.recall.ai/docs/stream-media),
[Webhook verification](https://docs.recall.ai/docs/authenticating-requests-from-recallai),
[Calendar scheduling](https://docs.recall.ai/docs/scheduling-guide),
[OpenAI incomplete-response handling](https://developers.openai.com/api/docs/guides/reasoning#controlling-costs).
