# Meeting Agent

> AI Thinkerer Hackathon — *Agents Everywhere*. Hi Aloy 👋

**An agent that attends your meetings for you.** It joins the call pre-briefed from your chat
history (Slack, the calendar invite, attached Drive docs), listens, **speaks only when somebody
actually asks it something**, and afterwards writes up proper meeting minutes.

---

## Status

| | |
|---|---|
| ✅ Working | ElevenLabs TTS hello-world (`main.py`), the shared contract (`types.py`, `protocols.py`), the caption aggregator, the speaking gate, BM25 retrieval |
| 🔨 In progress | The offline simulator, orchestrator and CLI — milestone **M1** |
| 📋 Not started | Everything behind a real integration: the Meet bot, the Claude brain, Slack/Calendar/Drive connectors, Scribe, minutes, the UI |

Commands below marked *(planned)* do not run yet.

## What it does

1. **Before the meeting** — pulls the calendar invite, the agenda, attached Drive docs and recent
   Slack messages from the relevant channels into a *context pack*.
2. **Joins the call** — a headless-ish Chromium joins Google Meet as a guest named
   *"<your name>'s AI notetaker"*, and announces itself in the chat: who it is, whose behalf it's
   on, and that it's recording for minutes.
3. **Listens** — reads Meet's live captions (already speaker-labelled) and the in-meeting chat.
4. **Answers when addressed** — if someone says *"Hey Aloy-bot, what's the status on the refunds
   migration?"* it answers out loud in ~2 s via ElevenLabs, citing where it got the answer from
   (*"per #payments on Tuesday…"*). If it doesn't know, it says so and flags the question for you.
5. **Stays quiet otherwise** — this is the whole product. See [the gate](#1-the-speaking-gate).
6. **Afterwards** — produces minutes: attendees, decisions, action items with owners, open
   questions, and an appendix of every question it answered.

## Architecture

```
meeting audio ──► PulseAudio monitor ──► WAV recording ──────────────┐
                                                                     │
Meet DOM captions ──► UtteranceAggregator ──► Gate ──► Brain ────────┤
  (speaker-labelled)   (group until pause)   (3 stages) (Claude+RAG) │
Meet DOM chat ───────────────────────────────────┘         │         │
                                                           ▼         ▼
Slack + Calendar + Drive ──► ContextPack ──► BM25 index   ElevenLabs  Minutes
                                                           TTS        (Claude)
                                                            │          │
                                                     virtual mic    Markdown/HTML
                                                       (speak)      + Slack post
```

---

## Design decisions that matter

### 1. The speaking gate

The agent is **silent by default**. It speaks only when *both* conditions hold:

- **it is addressed** — its wake name appears (fuzzy-matched, because captions mangle names), and
- **the utterance expects a response** — a question, or a statement that demands an answer.

Three stages, cheap ones first:

| Stage | Cost | Job |
|---|---|---|
| 1. Addressed? | free, local | Fuzzy wake-name match (`"hey aloy bot"`, `"aloy-bot"`, `"ai notetaker"`) |
| 2. Response expected? | free, local | Interrogatives (wh-word, aux-inversion, trailing `?`), imperatives aimed at the bot (*"tell us the status"*), hand-offs (*"…, over to you"*) |
| 3. Confirm | Claude Haiku | Only runs if stage 1 or a strong stage-2 signal fired. Classifies over the last ~8 turns |

On top of that: a cooldown, a cap on consecutive answers, never start speaking while a human is
talking, and **ignore its own voice** (its TTS goes into the meeting, so Meet captions it back —
without this guard it talks to itself).

Every decision, *including every silent one and its reason*, is emitted as an event. The UI lane
showing **why the bot stayed quiet** is the most convincing thing in the demo.

### 2. Why not ElevenLabs Agents (convai) for the voice loop

convai does its own turn-taking and answers whatever it hears — which fights the gate — and its VAD
is unreliable on mixed multi-speaker meeting audio anyway. So: **Claude** reasons (full control over
citations and defer behaviour), **ElevenLabs** does the voice. It sits behind a `Responder` protocol
so a `ConvaiResponder` can be dropped in later without touching the pipeline.

### 3. The transcript is dual-sourced, on purpose

- **Live:** Meet's own captions — free, low-latency, already carry speaker names. Drives the gate.
- **After:** the recorded WAV through **ElevenLabs Scribe** with diarisation — accurate, punctuated,
  and what the minutes are actually built from.

So ElevenLabs does both STT (batch) and TTS (realtime); Claude is the brain.

### 4. Offline-first, because the build sandbox is air-gapped

The Claude Code sandbox blocks every third-party API — `api.elevenlabs.io`, `api.slack.com`,
`graph.microsoft.com` and `meet.google.com` all 403 at the egress proxy. Only npm, PyPI and the
Anthropic API are reachable.

So the **simulator is a first-class part of the app, not a test fixture**. Every external dependency
sits behind a protocol with a working offline implementation. Consequences:

- the full pipeline runs and is testable with zero credentials,
- CI runs the whole thing,
- and on demo day it's the fallback that cannot be broken by the venue wifi.

### 5. Teams is not built — but the door is open

Only Google Meet is built. Teams/Zoom are a *second implementation of one interface*
(`MeetingPlatform`), so nothing upstream changes when someone adds them.

---

## Repo layout

```
src/meeting_agent/
  types.py          shared dataclasses — the vocabulary everything speaks
  protocols.py      the seams between tracks (MeetingPlatform, Responder, TTS, …)
  platforms/
    meet/           Playwright + PulseAudio Google Meet bot        [Track A]
    sim.py          scripted offline meeting                       [Track C]
  agent/
    aggregator.py   caption fragments → finalised utterances       [Track B]
    gate.py         the speaking gate                              [Track B]
    brain.py        Claude responder + citations                   [Track B]
    session.py      orchestrator                                   [Track B]
  context/
    slack.py calendar.py drive.py    connectors                    [Track C]
    pack.py bm25.py                  normalise + retrieve          [Track C]
  voice/
    sink.py         PCM → virtual mic / WAV                        [Track A]
    tts.py          ElevenLabs streaming TTS                       [Track D]
    scribe.py       ElevenLabs diarised STT                        [Track D]
  minutes/
    generate.py render.py deliver.py                               [Track D]
apps/
  api/              FastAPI: sessions, event WS, minutes           [Track B]
  web/              Next.js control panel                          [Track D]
fixtures/           scripted meetings + recorded Slack/Cal/Drive   [Track C]
tests/
```

## The shared contract

**This lands first, before anyone starts their track.** Everyone codes against these; that is what
makes four people working at once possible rather than four people merging conflicts.

```python
class MeetingPlatform(Protocol):            # Track A implements for Meet, Track C for sim
    async def join(self) -> None
    async def leave(self) -> None
    def captions(self) -> AsyncIterator[CaptionEvent]   # speaker, text, ts, is_final
    def chat(self) -> AsyncIterator[ChatEvent]
    async def send_chat(self, text: str) -> None
    async def speak(self, pcm: AsyncIterator[bytes]) -> None
    async def stop_speaking(self) -> None               # barge-in

class Responder(Protocol):                  # Track B
    async def respond(self, question: str, transcript: Transcript,
                      context: ContextIndex) -> Answer

class ContextIndex(Protocol):               # Track C
    def search(self, query: str, k: int = 5) -> list[ContextChunk]

class TTS(Protocol):                        # Track D
    def stream(self, text: str) -> AsyncIterator[bytes]   # PCM16 @ 16 kHz

class MinutesGenerator(Protocol):           # Track D
    async def generate(self, meeting: MeetingInfo, transcript: Transcript,
                       qa_log: list[QAEntry], context: ContextIndex) -> Minutes
```

Each protocol ships with a **real** implementation and an **offline** one. Mixing and matching is
how any single track gets tested without the other three being finished.

---

## Work split — four tracks

Each track owns its directories outright, so day-to-day there is nothing to coordinate and almost
nothing to merge-conflict over.

| Track | Mission | Owns | Riskiest part |
|---|---|---|---|
| **A** | Get into the call, hear it, speak into it | `platforms/meet/`, `voice/sink.py` | Meet's DOM + virtual audio devices |
| **B** | Decide when to speak, and what to say | `agent/`, `apps/api/` | Gate precision |
| **C** | Know things before the meeting starts | `context/`, `fixtures/`, `platforms/sim.py` | OAuth scopes |
| **D** | Voice, minutes, and the screen we demo | `voice/tts.py`, `voice/scribe.py`, `minutes/`, `apps/web/` | Latency to first spoken word |

### Track A — Presence & Audio

**Mission:** the agent is in the meeting, hears everything, and can make sound.

- PulseAudio setup script: two null sinks — `meet_out` (Chromium's output; record its `.monitor`)
  and `bot_mic` (remapped to a virtual source Chromium sees as a microphone).
- Launch Chromium with `PULSE_SINK=meet_out PULSE_SOURCE=bot_mic`,
  `--use-fake-ui-for-media-stream` (auto-grants mic/cam permission) and
  `--autoplay-policy=no-user-gesture-required`. Headed, under Xvfb — Meet is hostile to headless.
- Join flow: persistent browser context, set display name, camera off, *Ask to join*, wait for the
  host to admit.
- **Announce on join** in the meeting chat. Non-negotiable — it's how recording consent is
  established.
- Captions + chat: turn captions on, `MutationObserver` on each panel, bridged out via
  `page.expose_binding`. **All selectors in one `selectors.py`**, plus a `--dump-dom` debug mode.
  Meet's DOM is the single most likely thing to break at 3 a.m.
- Record `meet_out.monitor` to WAV via ffmpeg, for Track D's Scribe pass.
- `speak()` / `stop_speaking()`: stream PCM into `bot_mic` via a persistent `pacat`, killable
  mid-sentence for barge-in.

**Done when:** a real Meet call with a human in it produces a live stream of speaker-labelled
captions, and `speak()` plays a WAV that the human hears.

**Start on day 1, before anything else exists:** get the two virtual devices up and prove
round-trip audio manually (`parec` the monitor while `paplay`-ing into the mic). That is the part
that eats a day if it goes wrong, so it goes first.

### Track B — Gate, Brain & Orchestrator

**Mission:** the product decision — when to talk, and what to say.

- **`aggregator.py`** — Meet captions arrive as fragments and get *revised in place*. Group them per
  speaker until a ~1.2 s pause or a speaker change, then emit one finalised utterance. Gating on
  partial captions is the main source of misfires, so this is what makes the gate trustworthy. Works
  off **event timestamps, not wall clock**, so tests run instantly.
- **`gate.py`** — the three stages in the table above, plus cooldown, consecutive-answer cap,
  don't-talk-over-humans, and the ignore-own-voice guard. Emits a decision + reason for *every*
  utterance, silent ones included.
- **`brain.py`** — Claude Sonnet, given the briefing, a rolling transcript window, and a
  `search_context` tool over Track C's index. Returns
  `{action: answer|defer|stay_silent, text, citations[], confidence}`. Answers capped at ~2
  sentences — a bot that monologues in a standup is a bad bot. Speaks **as your assistant, never as
  you**: no impersonation. Below the confidence threshold it defers out loud and adds the item to
  the minutes' *needs-you* list.
- **`session.py`** — wires platform → aggregator → gate → brain → TTS → sink, maintains the QA log,
  triggers the minutes at the end.
- **`apps/api/`** — FastAPI. `POST /sessions`, WS `/sessions/{id}/stream` (captions, gate decisions,
  answers, latency), `POST /sessions/{id}/say` (manual override — genuinely useful on stage),
  `/mute`, `/leave`, `GET /sessions/{id}/minutes`. Every event persisted to SQLite so any meeting
  can be replayed.

**Done when:** the gate truth table passes on Track C's scripted meetings — every expected-speak
fires and, more importantly, every expected-silence stays silent.

**Start on day 1:** aggregator and gate stages 1–2 need no network and no other track. Write them
against a hand-written list of utterances and the truth table in `tests/test_gate.py`.

### Track C — Context & Simulator

**Mission:** the agent already knows what the meeting is about before it starts. Also: own the
offline world everyone else develops against.

- **Connectors** → all normalised to `ContextChunk{source, author, ts, text, url}`:
  - *Slack* — `conversations.history` over selected channels (bot token, `channels:history`).
  - *Google Calendar* — the invite, agenda from the description, attendee list.
  - *Google Drive* — attached docs, exported to text.
  - *In-meeting chat* — appended live during the call.
- **`bm25.py`** — retrieval via `rank-bm25`, **not** embeddings, deliberately: the whole retrieval
  path then runs offline, in CI and in the air-gapped sandbox.
- **`platforms/sim.py` + `fixtures/`** — the simulator. A YAML script of timed utterances (emitted
  as realistic cumulative caption fragments), chat messages, and **expected gate outcomes**; plus
  recorded Slack/Calendar/Drive JSON. This is the backbone of everyone's tests and the demo that
  can't fail.

**Done when:** `ContextIndex.search("refunds migration")` returns the right Slack message from real
credentials *and* from fixtures, with the same interface.

**Start on day 1:** write the fixtures and the scripted meeting **first** — it unblocks B and D
immediately, before any OAuth app exists. Then chase the Slack token and Google OAuth client, which
are the slow, bureaucratic part.

### Track D — Voice & Deliverables

**Mission:** the agent sounds good, and leaves something behind.

- **`tts.py`** — ElevenLabs streaming TTS at `output_format=pcm_16000`, yielding PCM chunks for
  Track A's sink. Stream it; don't wait for the full clip. First-audible-word latency is your number
  to own: **target under 2.5 s** from finalised caption.
- **`scribe.py`** — ElevenLabs Scribe over the recorded WAV with diarisation, reconciled against the
  caption timeline to recover real speaker names.
- **`minutes/`** — Claude Opus turns transcript + context + QA log into structured minutes:
  attendees, agenda, discussion by topic, decisions, action items (owner / due / source quote), open
  questions, and an appendix of every question the bot answered with citations. Render Markdown +
  HTML; deliver to file, to Slack, and to the UI.
- **`apps/web/`** — Next.js control panel, and the thing on the projector:
  - *pre-meeting*: paste the Meet link, pick Slack channels, review the generated briefing;
  - *live*: transcript with speaker labels, **the gate lane showing why the bot stayed quiet**, the
    bot's answers with citations, a latency readout, and a big mute/kill switch;
  - *post*: the minutes, with copy / export / post-to-Slack.

**Done when:** text in → audible speech out under 2.5 s, and a finished meeting produces minutes
worth sending to a human.

**Start on day 1:** `minutes/` needs nothing but a transcript — build it against Track C's fixture
transcript. The UI can be built against a recorded event stream (a JSONL of session events) before
the API is up.

---

## Integration milestones

Four people only converge if there are forced convergence points.

| # | Milestone | Needs |
|---|---|---|
| **M0** | Shared contract + offline stubs merged; `pytest` green | everyone, hour one |
| **M1** | Scripted meeting runs end to end offline, writes minutes, WAV instead of speech | B + C + D |
| **M2** | Real ElevenLabs voice on the scripted meeting; real Claude brain | B + D |
| **M3** | Bot joins a real Meet call, captions flowing, `speak()` audible | A |
| **M4** | **Full loop on a real call**: asked → answers → minutes | all four |
| **M5** | UI on the projector, latency HUD, demo script rehearsed | D + all |

M4 is the demo. Everything after M1 is de-risking, so **get to M1 early** — it is the first point
where the thing is recognisably the product.

---

## Getting started

```bash
uv sync                          # Python 3.13, offline deps only
uv run pytest                    # whole suite: no credentials, no network

# prove your ElevenLabs key works
cp .env.example .env             # fill in ELEVENLABS_API_KEY
uv run main.py

# run a scripted meeting end to end, offline                        (planned, M1)
uv run meeting-agent sim fixtures/meetings/standup.yaml --out out/
#   → out/minutes.md, out/minutes.html, out/bot-audio.wav, out/events.jsonl

# with real voice + real brain                                      (planned, M2)
uv run meeting-agent sim fixtures/meetings/standup.yaml --live-tts --live-brain

# join a real call                                                  (planned, M3)
uv run meeting-agent meet "https://meet.google.com/xxx-yyyy-zzz"
```

Python is pinned to **3.13** (`.python-version`). `uv sync` installs only what runs
offline; `uv sync --extra live` adds Playwright and the Anthropic SDK, `--extra api`
adds FastAPI.

## Verification

**Offline, every phase, runs in the sandbox and in CI:**

- gate truth table over the scripted meetings — each case asserting a **false positive** and a
  **false negative** (the silences matter more than the answers),
- aggregator fragment-merging and revision-handling tests,
- BM25 retrieval tests against fixtures,
- a full simulated session producing minutes,
- a snapshot test on the rendered minutes.

**On a laptop, with keys:** run the scripted meeting with `--live-tts` and listen — confirm it stays
silent through the non-addressed turns.

**On a real call:** two people in a Meet, bot joins as a guest. Say *"Hey Aloy-bot, what's the
status on X?"* → answers in ~2.5 s. Ask an unaddressed question → silence, and the UI shows *why*.
Leave the call → minutes appear.

**Latency budget:** finalised caption → first audible word, **under 2.5 s**, measured and displayed.

## Risks

- **Meet's DOM changes** and captions/chat break. Selectors isolated in one file; realtime Scribe STT
  is the fallback if captions die entirely.
- **Meet is hostile to headless** and guests need host admission — headed under Xvfb, host admits on
  stage.
- **Google's ToS** don't really contemplate bot participants. Fine for a hackathon demo, but better
  said out loud than discovered during Q&A. Recording-consent law varies by jurisdiction, which is
  exactly why the join announcement is non-negotiable.
- **Nothing external is reachable from the build sandbox**, so anything live can only be validated on
  a laptop. CI runs simulator mode only.
- **A bot that interjects wrongly is the failure mode that kills the room.** Hence: silent by
  default, cooldown, kill switch, and a visible reasoning lane.
