# Meeting Agent

A personal meeting delegate for **Google Meet and Discord**. Prepare text/file knowledge on the website, let the agent take notes, and get grounded answers aloud. Unknown questions ask whether they are urgent; a confirmed urgent question tags the configured owner in a Discord thread. New replies from that thread are spoken once in the associated live meeting.

Discord voice attendance and `/join` are implemented and verified with offline transports. **Real Discord DAVE reception, provider compatibility, transcription accuracy and audible playback still need the private-call acceptance check after credentials are supplied.** No live registration, meeting join, owner ping or paid provider request was performed during implementation.

## Use it

- **Google Meet:** paste the meeting URL, add knowledge, confirm participant awareness, then send or schedule the Recall bot.
- **Discord:** choose Discord briefing, give it a name and add text/TXT/Markdown/text PDF/DOCX. Save, then use `/join channel:#voice-channel briefing:<prepared briefing>` in your configured guild. The briefing picker is optional: no selection starts with empty knowledge. Failed uploads remain recoverable drafts.
- Only the configured Discord owner can use `/join`, `/leave`, `/mute`, `/unmute`, `/stop-speaking` and `/status`. Controls reply privately; meeting answers are voice only.
- Muting stops speech while notes continue. After departure, the complete chronological transcript becomes minutes with tracked-question, owner-answer and capture-gap appendices. Budget-blocked notes show **Generate notes** for an explicit later retry.

Slack, Microsoft and Zoom integrations remain outside active use. Historical records remain readable. Full-duplex interruption, Google Drive import, connector token renewal, retention controls and multi-user authentication remain incomplete.

## Local setup

Python 3.13, Node 22.12+ (tested on 24.18.0), and FFmpeg with Opus support are required for Discord voice.

```powershell
uv sync --locked
# Copy only if .env does not exist.
Copy-Item .env.example .env
uv run --locked python main.py
```

Set `BACKEND_API_TOKEN` in root `.env`. Credentials can be added later; knowledge authoring and stored notes work without AI keys. For Discord dependencies, run `npm ci --prefix apps/discord-voice`. Follow [Discord voice setup](docs/DISCORD_VOICE_SETUP.md) before enabling attendance or explicitly registering guild commands.

```powershell
cd apps/web
npm ci
# Copy only if .env.local does not exist.
Copy-Item .env.example .env.local
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1
```

Set server-only `ALLOY_BACKEND_URL=http://127.0.0.1:8000` and the same `BACKEND_API_TOKEN` in `apps/web/.env.local`. Open `http://127.0.0.1:3000`. Set root `WEB_BASE_URL` to the website's actual origin for Discord dashboard links. API docs: `http://127.0.0.1:8000/docs`.

Run **one backend process** with one SQLite database. The website is a trusted local operator console with no login: bind it to loopback and add authentication before public deployment. Provider secrets stay server-side.

## Models and monthly budget

| Operation | Default API model | Published rate checked 15 October 2026 |
| --- | --- | --- |
| Transcription | `gpt-transcribe` | USD 0.0045 / audio minute |
| Answers and minutes | `gpt-6-luna` | USD 0.10 / million input tokens; USD 0.50 / million output tokens |
| Speech | `eleven_v4_turbo` | USD 0.04 / 1,000 characters |

Sources: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api). Model access and the configured voice must be validated with your accounts; there is no automatic fallback.

The shared estimated budget defaults to **USD 5 soft / USD 8 hard per Asia/Kuala_Lumpur calendar month**, across both platforms, previews and finalization. Every paid request reserves a conservative amount atomically before dispatch, including a 10% margin. Unknown rates fail closed. Timeouts and uncertain charges stay held across restart; unused successful reservations are released. Luna requests above 272,000 estimated input tokens are rejected.

At the hard boundary, Discord attendance stops receiving/playing and leaves without buying a spoken notice. Saved transcript and deterministic appendices remain available. Successful summary sections are cached for manual retry; a new month does not automatically retry or rejoin.

At 60 billed audio minutes, 5,000 spoken characters and 50,000 input/5,000 output text tokens per hour, **4-8 hours costs about USD 1.91-3.82**. More bot speech, overlapping speakers and retries increase usage. This cap is an application estimate, not an invoice guarantee. It excludes Recall, hosting, subscriptions, taxes and other applications using the same credentials.

## Knowledge and context

- Five files per submission; 10 MiB each, 20 MiB combined; 22 MiB multipart request.
- Pasted text: 100,000 characters; normalized knowledge: 1,000,000 characters per meeting.
- UTF-8 TXT/Markdown; PDFs require embedded text (300 pages maximum). Scanned/encrypted PDFs need external conversion.
- DOCX expansion: 50 MiB / 2,000 ZIP entries; extraction: 10 seconds / 500,000 characters.
- Chunks: 2,000 characters with 200 overlap. Duplicate normalized content is skipped; invalid mixed batches save nothing.
- Discord meetings copy full briefing text and locators. Later edits/deletion do not change existing meeting copies.

Live answers send the current question, at most eight retrieved knowledge chunks and the latest 12 dialogue utterances (2,000 characters each) to Luna. The local address gate runs first. Final notes use the complete chronological transcript in sections of at most 30,000 characters and bounded synthesis. Evidence excerpts are checked before factual answers can be spoken.

Original upload bytes and Discord audio clips are discarded after processing. SQLite retains normalized knowledge, transcripts, events, minutes, cost records and bounded Recall playback audio. There is no automatic Discord history ingestion.

## Architecture

```text
Next.js server components/actions -> authenticated FastAPI -> SQLite
Meet: Recall captions -----------+
Discord: supervised Node worker -+-> MeetingService -> knowledge + Luna -> PlaybackRouter
  Opus -> FFmpeg -> WAV -> GPT-Transcribe                    |-> Recall MP3 outbox
                                                          |-> Discord audio player
Unknown -> speaker-bound urgency -> Discord REST question/thread -> owner reply -> shared voice
Complete transcript + Q&A/questions/replies/gaps -> cached MinutesService -> website
All OpenAI / ElevenLabs requests -> durable reservation/usage ledger
```

Python/FastAPI/Pydantic/HTTPX/SQLite; Next.js 16/React 19/TypeScript/CSS modules. Discord voice uses locked discord.js 14.27.0, @discordjs/voice 0.19.2, opusscript and its DAVE dependency. Node receives only the Discord token. It is the sole Gateway owner when voice is enabled; otherwise discord.py supports Meet escalation replies. Controlled Discord REST notifications remain in Python. ElevenLabs v4 Turbo uses the dialogue WebSocket.

## Verification

```powershell
uv sync --locked
uv run --locked pytest -q --basetemp data/pytest-verification
npm ci --prefix apps/discord-voice
npm test --prefix apps/discord-voice
npm ci --prefix apps/web
npm test --prefix apps/web
npm run typecheck --prefix apps/web
npm run build --prefix apps/web
```

Tests use fake providers/Gateway transports, real SQLite, local document extraction and a real local Opus fixture/FFmpeg conversion. The dedicated pytest directory avoids Windows temp ACL problems; pytest owns and replaces only that directory.

See [verification evidence](docs/IMPLEMENTATION_VERIFICATION.md), [backend handoff](docs/BACKEND_HANDOFF.md), [Discord voice setup](docs/DISCORD_VOICE_SETUP.md), and [Meet/notification setup](docs/DISCORD_SETUP.md). The [foundation assessment](docs/PROJECT_ASSESSMENT.md) and [original hackathon design](docs/HACKATHON_DESIGN.md) describe earlier states.
