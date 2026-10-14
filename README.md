# Meeting Agent

A personal meeting assistant for Google Meet, with meeting-scoped knowledge, grounded spoken answers, and urgent questions routed to your Discord question threads. The product name is neutral; each meeting can use your chosen owner and delegate names.

This implements the approved [foundation design](docs/superpowers/specs/2026-10-14-personal-meeting-agent-design.md). **Discord voice attendance and `/join` are the next milestone.** Slack, Microsoft and Zoom integrations are removed from active use; existing meeting records remain readable.

## What works in this phase

1. Create a Google Meet session with pasted text and TXT, Markdown, text PDF or DOCX files. Uploads finish before a bot launch is submitted; a failed upload can be retried in the same saved meeting.
2. The Recall bot transcribes the call. Addressed factual answers require retrieved meeting knowledge and valid evidence excerpts, shown with filename and location in the dashboard.
3. An unsupported question receives: “I don't know based on the knowledge I have. Is this urgent?” A clear confirmation within 60 seconds creates a persisted Discord escalation. Negations, uncertain references and unknown speakers cannot notify the owner.
4. Discord tags only the configured owner and creates a question thread. New text replies by that owner are saved as knowledge for this meeting and spoken as “[owner] says: …”. Replies after the meeting update notes without rejoining.
5. Complete transcripts are summarized in chronological segments of at most 30,000 characters, with hierarchical synthesis for long meetings. Tracked questions and owner replies are retained in an appendix. The dashboard keeps polling through final processing and shows failures.

Ordinary answers are spoken in the meeting. Discord text is used for urgent questions and owner replies. Manual caption preview/coaching never notifies Discord or speaks into a meeting.

## Local setup

Use Python 3.13 and Node.js 24; selectors and lockfiles are committed.

```powershell
uv sync --locked
# Copy only when .env does not exist.
Copy-Item .env.example .env
uv run --locked python main.py
```

Set `BACKEND_API_TOKEN` in the ignored root `.env`. Live Meet attendance needs Recall, OpenAI and ElevenLabs settings. Discord is optional and has four separate settings; follow [Discord setup and recovery](docs/DISCORD_SETUP.md).

```powershell
cd apps/web
npm ci
# Copy only when .env.local does not exist.
Copy-Item .env.example .env.local
npm run dev -- --hostname 127.0.0.1
```

In `apps/web/.env.local`, set server-only `ALLOY_BACKEND_URL=http://127.0.0.1:8000` and the same `BACKEND_API_TOKEN`. Open `http://127.0.0.1:3000`. API documentation is at `http://127.0.0.1:8000/docs`; Authorize with the backend token.

Run one backend process. This is a single trusted operator app with no frontend login: keep it on localhost until authentication is added. Provider keys and tokens stay in the backend/server environment.

## Knowledge limits

- Five files per submission, 10 MiB per file, 20 MiB of files combined; total multipart request 22 MiB.
- Pasted text: 100,000 characters per submission. Normalized knowledge: 1,000,000 characters per meeting.
- TXT/Markdown must be UTF-8. PDFs need embedded text; encrypted/scanned documents require conversion/OCR outside the app. PDF limit: 300 pages.
- DOCX expansion limit: 50 MiB and 2,000 ZIP entries. Extraction has a 10-second process timeout and a 500,000-character document limit.
- Sources are chunked at 2,000 characters with 200-character overlap. Exact duplicate normalized content is skipped. Invalid mixed batches save nothing.

Original file bytes are discarded after extraction. Normalized text, provenance, transcripts and audio are stored in local SQLite. There is no global knowledge library or automatic Discord history ingestion.

## Architecture

```text
Next.js server components/actions -> authenticated FastAPI -> SQLite
Recall Google Meet captions -> MeetingService -> knowledge + structured OpenAI answer
  -> ElevenLabs MP3 -> Recall playback outbox -> meeting
Unknown question -> urgency confirmation -> durable outbox -> Discord parent + thread
Configured owner reply -> meeting knowledge + deduplicated spoken relay
Final Recall transcript + Q&A + tracked questions/replies -> MinutesService -> dashboard
```

Python/FastAPI/Pydantic/HTTPX/SQLite; Next.js 16/React 19/TypeScript/CSS modules. Recall handles Meet transport; discord.py handles optional Gateway messages and HTTPX handles controlled REST operations. Spoken answers default to `gpt-4.1-mini`, minutes to `gpt-5-mini`, speech to ElevenLabs Flash with Charlie; all remain configurable.

## Verification and remaining work

```powershell
uv sync --locked
uv run --locked pytest -q
cd apps/web
npm test
npm run typecheck
npm run build
```

The current automated checks pass: 144 backend tests, two frontend behavior tests, TypeScript and the production build, on Python 3.13.13 and Node 24.18.0/npm 11.8.0. Tests use fake providers, real SQLite and real local document extraction. Browser checks cover upload rejection/retry and notes updating after call end. See [current assessment](docs/PROJECT_ASSESSMENT.md) for the original incomplete specs.

Live provider credentials, Discord intent/permissions, public Recall webhooks, Google consent, meeting admission and audible playback still require an operator test. No live provider calls or Discord messages were used to verify this phase. Speech uses complete MP3 clips; full-duplex audio, barge-in and a 2.5-second audible-response target are unverified. Google Drive import, automatic connector token refresh, retention controls and multi-user authentication remain incomplete.

For operations use [backend handoff](docs/BACKEND_HANDOFF.md), [demo runbook](docs/DEMO_RUNBOOK.md) and [Discord setup](docs/DISCORD_SETUP.md). The [original hackathon design](docs/HACKATHON_DESIGN.md) is historical, including its unimplemented browser/audio architecture and simulator commands.
