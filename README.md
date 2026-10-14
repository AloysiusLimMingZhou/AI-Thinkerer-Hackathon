# Meeting Agent

A personal meeting assistant that joins a call with your briefing, listens, responds when addressed, and saves the transcript and minutes.

The product is being focused on **Google Meet and Discord**. Google Meet participation currently uses Recall. File knowledge, Discord escalation and the shared pipeline are specified in the [proposed foundation design](docs/superpowers/specs/2026-10-14-personal-meeting-agent-design.md); these features are awaiting design review and implementation. Discord voice attendance with `/join` is a subsequent milestone.

## Verified baseline

Fresh checks on 14 October 2026:

| Check | Result |
| --- | --- |
| Backend suite, Python 3.13.13 | 67 passed; one Starlette/AnyIO deprecation warning |
| Frontend TypeScript check | Passed |
| Production build, Node 24.18.0 / npm 11.8.0 | Passed |

Tests use fake external providers. Live meeting admission, public webhooks, audible playback, Google consent and live OpenAI/ElevenLabs calls remain unverified here. No provider credits were used and no Discord messages were sent during baseline checks.

The Next.js dashboard is connected to the backend through a server-only client and Server Actions. The detailed [project assessment](docs/PROJECT_ASSESSMENT.md) records feature gaps and evidence.

## Local setup

Install Python 3.13 with `uv`, and Node.js 24 with npm. Runtime selectors are `.python-version` and `.node-version`; dependency lockfiles are `uv.lock` and `apps/web/package-lock.json`. Installation requires network access; backend tests run offline afterward.

From the repository root:

```powershell
uv sync --locked
# Copy only when .env does not already exist.
Copy-Item .env.example .env
uv run --locked python main.py
```

Before starting, set a random `BACKEND_API_TOKEN` in the ignored `.env`. Live generation/dispatch also needs OpenAI, ElevenLabs and Recall credentials. See [the backend handoff](docs/BACKEND_HANDOFF.md) for public HTTPS/webhooks and optional Calendar V2 setup.

The API listens on `http://127.0.0.1:8000`. At `http://127.0.0.1:8000/docs`, choose Authorize and enter the backend token.

In a second terminal:

```powershell
cd apps/web
npm ci
# Copy only when .env.local does not already exist.
Copy-Item .env.example .env.local
```

Set server-only variables in `apps/web/.env.local`:

```dotenv
ALLOY_BACKEND_URL=http://127.0.0.1:8000
BACKEND_API_TOKEN=the-same-backend-token
```

Start the dashboard and open `http://127.0.0.1:3000`:

```powershell
npm run dev -- --hostname 127.0.0.1
```

The prototype assumes one trusted operator. Keep provider keys and the backend token out of browser code. The frontend has no login; public deployment requires frontend authentication.

## Checks

From the repository root:

```powershell
uv run --locked pytest -q
cd apps/web
npm run typecheck
npm run build
```

The build downloads Google Fonts if uncached. Restricted Windows agent environments can require a writable `uv` cache (e.g. `data/cache/uv`), a workspace-owned pytest temporary directory, and filesystem access for Next.js path canonicalization. The verified baseline used the existing lockfiles without changing dependency versions.

## Current architecture

```text
Next.js server components/actions -> authenticated FastAPI -> SQLite

Recall meeting bot -> signed transcript/lifecycle webhooks -> durable worker
  -> address/follow-up gate -> session note retrieval -> OpenAI Responses API
  -> ElevenLabs MP3 -> SQLite audio outbox -> Recall Output Media -> meeting

Recall final transcript -> OpenAI Markdown minutes -> SQLite -> dashboard/downloads
```

Backend: Python 3.13, FastAPI, Pydantic, HTTPX, SQLite and encrypted OAuth credential storage. Spoken answers/coaching default to `gpt-4.1-mini`; minutes to `gpt-5-mini`. Speech defaults to ElevenLabs Flash with Charlie. Models and voice are configurable through backend environment variables.

Frontend: Next.js 16, React 19, TypeScript, CSS modules and `react-markdown`. It keeps the operator token server-side, polls backend state and provides briefing text, transcripts, Q&A, meeting history, controls and downloads.

## Current workflow and limits

1. Create a meeting with its URL, owner/delegate names and briefing text.
2. Confirm participants know the delegate will transcribe and may speak, then dispatch it. A queued launch is not proof of admission.
3. Recall supplies transcription. Direct addresses and bounded same-speaker follow-ups can receive replies, including greetings.
4. Recall's completed transcript triggers Markdown minutes; manual generation is also available.

Legacy Slack/Microsoft/Zoom adapters still exist in code. Removing them and restricting new dispatch to Google Meet are part of the proposed foundation work. Historical records will remain readable; the new product scope is Google Meet and Discord.

Knowledge currently consists of session text notes and explicit connector imports. Retrieval uses local overlap scoring. There is no file upload, global personal knowledge library, structured supported/unknown result, urgency state or Discord escalation yet. Speech is a complete MP3, not full-duplex or barge-in audio. No 2.5-second audible-response target has been verified.

Code is under `src/meeting_agent/`, `apps/web/` and `tests/`. The original Playwright/PulseAudio/Scribe architecture, simulator commands and four-track plan are preserved in [the historical hackathon design](docs/HACKATHON_DESIGN.md). Those commands and the README's former `live`/`api` optional dependency groups do not exist in the current package.

For operations and endpoint details see [BACKEND_HANDOFF.md](docs/BACKEND_HANDOFF.md). Its older frontend instructions predate dashboard wiring: the actual client is `apps/web/lib/backend.ts`, not a fixture data module.
