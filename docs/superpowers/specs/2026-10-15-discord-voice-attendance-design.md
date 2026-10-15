# Discord voice attendance and monthly API budget

Date: 15 October 2026 (Asia/Kuala_Lumpur).
Status: approved by the owner on 15 October 2026, including the transcript-context clarification below. Written implementation-plan review is next. No voice attendance or budget implementation is claimed by this document.
Builds on the approved personal-meeting-agent design dated 14 October 2026 and the merged foundation in PR #3.

## Owner requirements and success

The agent attends a Discord voice channel in place of the owner, takes notes, and answers aloud only when addressed. The owner summons it with /join and a voice-channel picker. An optional briefing is selected from knowledge prepared on the website; omitting it starts a meeting with empty knowledge. Briefings accept the existing text, TXT, Markdown, PDF and DOCX inputs and retain their existing limits.

Keep the existing supported-answer evidence checks, exact unknown/urgency prompt, speaker-bound urgency confirmation, owner mention in the configured Discord escalation channel, and automatic spoken relay of the configured owner's replies from the corresponding question thread. Ordinary meeting answers remain voice only. Google Meet remains supported; Slack is outside the product.

The owner selected GPT-Transcribe (API ID gpt-transcribe; the requested "GPT-Transcript" refers to this model), GPT-6 Luna (gpt-6-luna), and ElevenLabs v4 Turbo (eleven_v4_turbo). Luna is used for both answers and minutes. Expected attendance is 4-8 hours per month. The combined OpenAI and ElevenLabs estimated spend has a USD 5 soft cap and USD 8 hard cap.

The owner will provide credentials later and explicitly authorized continuing without them. Build and verify with fake provider and Discord transports. Missing keys remain a visible readiness condition; development does not create keys, join real calls, register commands against a live guild, ping people or incur provider charges.

Success is a complete offline-tested attendance path, optional briefing snapshots, shared Meet/Discord policy, the chosen provider adapters, persistent monthly cost enforcement, and clear setup for a later real-call acceptance check. Fake transport checks cannot establish live DAVE compatibility or transcription accuracy.

## Architecture and alternatives

Recommended: add a supervised Node voice worker using discord.js and @discordjs/voice, retaining FastAPI, SQLite and the shared Python meeting pipeline. Node handles Discord Gateway interactions, DAVE voice receive/send, speaker IDs and local audio conversion. Python owns authorization, briefing selection, transcription, knowledge, answers, urgency, owner replies, minutes and the cost ledger. Node receives only the Discord token; it never receives OpenAI or ElevenLabs credentials.

The installed Python discord.py library handles Gateway messages but does not provide the needed verified receive pipeline. The independent receive extension still has unresolved DAVE work. Pinning an experimental fork risks silent listening failure. Replacing the existing Gateway library with another Python Discord distribution would introduce migration and dependency conflicts. The Node adapter adds a process but fits the existing Node runtime and keeps answer policy in one place.

Use Node 22.12 or newer, with the existing Node 24 installation suitable. Lock the supported @discordjs/voice 0.19.2 and discord.js 14.27.0 dependencies, including the DAVE implementation, and a supported Opus decoder. Use the installed FFmpeg through a configured executable path for bounded local conversion. Dependency installation belongs to implementation, after plan approval. Discord receive behavior is not a stable documented Discord contract; expose receive failures and retain a real-call acceptance step.

One backend process and one SQLite database remain the supported deployment. When voice attendance is enabled, the Node worker is the sole Discord Gateway owner and forwards owner reply events to the existing EscalationService. Disable the Python Gateway in that mode. When voice is disabled, the existing optional Python Gateway continues to support Meet escalation replies. Python's controlled Discord REST notifier remains responsible for question messages and threads.

## Briefings, attendance and commands

Add explicit session platform and purpose fields: platform is google_meet or discord; purpose is meeting or briefing. Existing rows migrate additively to google_meet/meeting. A Discord briefing has no meeting URL and never represents a connected bot. Keep briefings separately labelled and out of active-meeting counts. Historical knowledge is never offered as a briefing merely because a session exists.

Extend the website's existing creation form with Google Meet and Discord choices. Meet keeps its URL, scheduling and dispatch behavior. Discord saves a named briefing with the same knowledge inputs and configurable owner/agent display names. It does not join or schedule a voice call. Briefings can be edited and selected later; deleting one does not delete knowledge already copied into a meeting.

The guild slash command is /join channel:<standard voice channel> briefing:<optional prepared Discord briefing>. Discord renders the channel argument as a picker; the owner may select a channel mention. Briefing autocomplete lists only explicitly prepared Discord briefings, with opaque IDs as values, no document snippets and at most Discord's allowed number of choices. Validate the selected ID again at execution time.

All attendance commands require the configured guild and exact configured owner user ID. Revalidate in Python even when Node has filtered the interaction. Reject DMs, Stage channels, other guilds, other users, inaccessible channels and unknown briefings. Check View Channel, Connect and Speak permissions, dependencies, credentials, budget and worker health before attempting attendance. Declare commands only in the configured guild with a documented explicit setup command; do not register globally or on every reconnect.

A successful /join creates a new Discord meeting, snapshots the selected briefing through KnowledgeService.copy_into, preserves full source text and locators, and stores the briefing ID for provenance. No briefing means no factual knowledge, not an error. Each invocation has a durable interaction ID for deduplication. Only one Discord attendance can be active or joining in the configured guild. A same-channel repeat reports the existing session without rejoining or changing its briefing; another-channel request requires leaving first.

Provide owner-only /leave, /mute, /unmute, /stop-speaking and /status. Mute stops current and pending speech but continues transcription and notes. It suppresses spoken answers and new spoken urgency prompts. Stop-speaking clears speech without muting future answers. Control acknowledgements and errors are ephemeral; ordinary answers never become text-channel messages. /status includes the active meeting, receive health, configured model names and current budget status.

Resolve the command promptly with a deferred ephemeral acknowledgement, then update it after attendance succeeds or fails. On success include a dashboard link. Joining, active, leaving, ended, interrupted, failed and budget_stopped are persisted attendance states, distinct from minutes processing state. A Discord meeting must not create a fake Recall bot row. The website uses platform-aware status and controls.

On joining, speak an introduction identifying the bot as the owner's AI delegate and saying it transcribes and may answer aloud. Existing meeting-participant awareness remains required. A failed introduction or audio receive startup must show a degraded/failed state; a voice socket alone does not establish that note taking works.

## Audio and shared policy

Receive separate streams keyed by immutable Discord user ID; ignore all bots, webhooks and the agent's own user ID. Names are labels. A human sharing the bot's display name is still a human. Follow-up and urgency matching use participant IDs when available, retaining the existing fallback for providers without IDs.

Decode Opus locally and normalize to mono 16 kHz PCM WAV. Close utterances on a bounded silence window, and split continuous speech at 15 seconds without overlapping or charging the same samples twice. Preserve speech-start timestamps and per-speaker sequence IDs. Allow at most two transcription requests in flight and eight waiting utterances across the worker. Audio frames and buffers have explicit size limits; raw audio is discarded after success or failure and is not saved as meeting knowledge.

Call gpt-transcribe on completed utterance clips, then pass final text through MeetingService with platform=discord, stable event/participant IDs and actual speech timestamps. Do not substitute file-completion time for speech time to make old speech appear fresh. Preserve late transcripts for notes while suppressing stale answers. A transcription failure or queue overflow records a visible gap with time and speaker, rather than fabricated transcript text or silent success.

Do not send all listening audio to Luna. For live answers, send the current question, at most eight relevant briefing chunks, and only the latest 12 dialogue utterances with at most 2,000 characters each; do not attach the full meeting transcript. The existing local address gate runs on the transcript before requesting an answer. For final notes, process the complete chronological transcript in sections of at most 30,000 characters and combine section summaries, preserving the deterministic tracked-question and owner-reply appendix. These are distinct answer and minutes contexts, as clarified and approved by the owner. Answers require supplied meeting knowledge and verified excerpts; unsupported questions use the existing exact unknown prompt and urgency flow. Any necessary names or domain hints for transcription are bounded reference data, never instructions that can change recipients, permissions or answering policy.

Route both platforms through a PlaybackRouter with shared liveness, mute, queue availability, enqueue and stop contracts. Remove Recall-specific queue inspection from MeetingService. The Discord adapter checks the associated call generation before generating speech and again before playback. Voice queue depth is two. Stable speech intent IDs and playback acknowledgements update existing durable intent/owner-relay state. Acknowledgements distinguish queued, playing, completed, failed and cancelled; only confirmed playback completes delivery.

Ordinary answers, the unknown prompt and accepted owner replies all use the same voice adapter and budget guard. Owner replies remain prefixed with the owner's name and cannot play into another session. A reply that arrives after leaving is saved for notes. If budget or mute prevents relay, preserve it with an explicit unspoken reason; do not rejoin or repeatedly synthesize it. Supporting full-duplex interruption and acoustic echo cancellation is outside this milestone.

## Provider adapters

Set both OPENAI_MODEL and OPENAI_ANSWER_MODEL defaults to gpt-6-luna and add OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe. Preserve strict answer schemas, exact evidence validation and no action tools. Configure Luna reasoning explicitly: none for short answers, low for minutes. Set and account for finite maximum output tokens for every request, including reasoning; incomplete responses remain visible failures, never spoken partial JSON. Do not retain the current gpt-5-only prefix heuristic for reasoning or output limits.

Set ELEVENLABS_MODEL_ID=eleven_v4_turbo. This model uses the Text to Dialogue WebSocket, not the existing Flash text-to-speech conversion endpoint. Implement a bounded asynchronous adapter using one configured voice and the documented registration, input, finalization and audio frame protocol. Register the existing configured voice ID; preserve configurability and surface incompatibility rather than silently changing voices or models.

For each accepted speech intent open a bounded connection, register its voice, send the complete short text, close/flush the input as documented, collect MP3 audio chunks until the final marker, and close the socket. Bound total time and audio bytes and reject malformed/error/unfinished frames. MP3 remains compatible with Recall playback; the Discord worker decodes the MP3 and sends it through its Opus audio player. A disconnected TTS socket after text submission is possibly charged and cannot trigger an unreserved automatic retry. Do not synthesize speculative answers.

Keys stay server-side. Missing credentials show "not configured" without preventing briefing authoring, stored-note viewing, tests or application startup. A real attendance request fails before joining if the required providers are unconfigured. No fake success or automatic model fallback is allowed.

## Monthly budget and cost accounting

Scope: a single shared operator budget across all OpenAI transcription, answering, coaching/preview and minutes calls, and all ElevenLabs speech generated by this application for Meet or Discord. Existing direct/manual endpoints must use the same provider guards. Raw knowledge extraction and Discord control/notification calls do not consume this AI budget. Recall, hosting, subscriptions, taxes, other applications using these keys and externally changed provider rates are outside this estimated usage cap; the dashboard states that scope plainly.

Use Asia/Kuala_Lumpur calendar months. Store timestamps in UTC and calculate the billing bucket with an IANA timezone. The period rolls over at local midnight on the first day of the month. Keep old ledger entries; a request reserved before midnight settles against that original month. A rollover does not rejoin calls, automatically replay speech or retry old finalization work.

Persist a ledger containing operation ID, session ID where applicable, provider/model, operation purpose, price version, month, reserved cost, settled usage/cost, status, provider request ID and UTC timestamps. Represent money with integer microdollars and round reservations upward. Do not store keys or raw audio. Aggregate across all sessions and all callers.

Before every paid request, atomically reserve its conservative maximum estimated cost in a SQLite write transaction. Committed cost plus all open/uncertain reservations plus the proposed reservation must be no more than USD 8. Use the actual audio duration and a documented billing-rounding allowance for transcription; all submitted characters for speech; and a conservative input-token bound including instructions/schema plus the full configured output-token limit for Luna. Include a 10 percent reservation margin. Unknown model rates, unbounded input or invalid pricing configuration fail closed.

After a response, settle from provider usage where available. For duration- and character-priced APIs, use measured submitted duration/characters and the versioned rate. A successful cheaper response releases the unused reservation. Definite pre-dispatch failures can release it. Timeouts, cancellation after dispatch, process crashes and ambiguous provider failures retain a possibly-charged reservation and an attention status. Never free those reservations merely because a timeout expired. Retrying a possibly charged request is a new bounded operation with a new reservation; automatic provider retries are disabled. A known completed operation is not dispatched again because its event was redelivered.

At the USD 5 soft threshold, record a once-per-month warning, display it prominently in the website and return it in private /status. Do not ping the owner in the escalation channel for a budget warning. Continue within the remaining hard budget; do not silently replace selected models or discard notes.

When the next paid request cannot fit below USD 8, block it before dispatch. For an active Discord call, mark budget_stopped, stop receiving/clear unsubmitted audio, cancel unstarted speech and leave, then save the transcript and deterministic unresolved-question/owner-answer appendix. Do not make a new paid TTS call merely to announce the cap. Complete already reserved work only within its reservation and never play its result into a departed call. New /join requests remain blocked when the available budget cannot cover the introduction and an initial bounded transcription/answer operation. Free status, export, leave and stored-note access remain available.

Budget-blocked minutes retain an explicit pending-budget status with a manual "Generate notes" action after a new month or changed operator configuration. Never label a model summary ready when none was generated. Existing Meet audio/transcripts may continue arriving through Recall, but AI answering/speech/minutes requests still obey the same guard. Recall's separate attendance charges are not represented as covered by this cap.

Expose an authenticated budget status endpoint and a compact website panel: period and reset date, USD 5/USD 8 thresholds, settled estimate, held reservations, available budget, warning/hard-block state, provider breakdown and pricing date. Keep threshold configuration server-side, defaulting to the owner's selected limits. Do not add a one-click bypass, reset ledger endpoint, automatic top-up or purchase flow.

Published rates checked on 15 October 2026 are USD 0.0045 per audio minute for gpt-transcribe; USD 0.10 per million input and USD 0.50 per million output tokens for short-context gpt-6-luna; and USD 0.04 per thousand characters for eleven_v4_turbo. The rate table must account for Luna's long-context multipliers if such requests are allowed; prefer keeping each request below 272,000 input tokens. No automatic model switch is part of budget control.

For a planning estimate, 60 billed audio minutes, 5,000 spoken characters and 50,000 input/5,000 billed output text tokens per meeting hour cost about USD 0.4775. Four to eight hours therefore cost about USD 1.91-3.82. Allowing USD 0.05 per thousand speech characters conservatively gives about USD 2.11-4.22. This is an assumption-based estimate, not a measurement of this app. More bot speech, overlap, repeated context or retries increase it. The cap governs the application's estimated reservations, not a provider invoice guarantee.

## Worker boundaries and recovery

Use supervised, newline-framed JSON over the child process's stdin/stdout; send logs only to stderr. No new public HTTP port is needed. Validate message shapes, IDs and size before routing. Audio is bounded base64 with no arbitrary file paths. Match commands/responses with request IDs and attendance generations; reject delayed events from an earlier worker/call. Limit command wait times, outstanding requests and diagnostic output, and redact provider secrets.

Persist the joining intent before sending it to the worker. A command/connection timeout is uncertain: reconcile the worker's active connection before a second join and prevent simultaneous attendance. The worker disconnects if its Python parent/IPC pipe is lost. Worker exit or lost health marks attendance interrupted, clears unsubmitted audio and does not automatically rejoin. Python startup recovers unfinished attendance and speech intents as interrupted/attention states. Saved transcripts can still finalize through the shared minutes service subject to budget.

The worker must report Gateway, voice connection, decoder, receiver and playback health separately. Reconnection attempts within an existing live transport are bounded and visible. Permanent permission/DAVE/decoder failures stop attendance truthfully. Leave after the channel has had no human members for 60 seconds, or after a configurable four-hour maximum attendance. Ignore brief member-state churn and count only humans in the connected channel.

Always detach receive subscriptions, stop the player, destroy the voice connection, cancel bounded transcription work and reap child/converter processes on leave or shutdown. Provider charges already incurred remain in the ledger.

## Acceptance and verification

1. Additive migration preserves historical meetings and knowledge. Discord briefing creation accepts existing supported files, rejects invalid input atomically, and does not launch Recall or Discord.
2. Owner/guild/channel authorization, permission/readiness errors, optional briefing selection, fresh knowledge snapshots, no-selection empty knowledge, duplicate commands and single-call ownership are tested without a live Gateway.
3. Real local Opus/PCM fixtures exercise decode and timing boundaries. Worker protocol tests cover frame limits, invalid messages, generation fencing, process failure and cleanup. A ready socket with a failed receiver is never reported as healthy.
4. Fake transcription flows through the existing MeetingService. Duplicate IDs, same-name humans, own/bot streams, stale text, mixed speakers, audio gaps and answer/urgency/owner-relay routing retain correct behavior.
5. Mock the exact OpenAI model IDs and ElevenLabs dialogue WebSocket protocol, including short text, final marker, error, timeout, oversized audio and cancellation. Missing keys perform no external I/O.
6. Budget tests prove atomic admission across concurrent callers, USD 5 warning, pre-dispatch USD 8 refusal, all provider paths covered, output/reasoning bounds, uncertain-charge holds, restart persistence, idempotent events and local-time month rollover. Denied requests cause zero provider calls.
7. Hard-stop attendance, unspoken owner replies and blocked finalization remain visible; notes and controls stay accessible. Existing Meet workflows pass their regression checks with the platform router and new provider defaults.
8. Run the locked backend suite, worker tests, frontend checks and production build after implementation. Tests are fakes/local fixtures and incur no provider charges.
9. Document one later authorized private-call check after the owner supplies keys: slash registration, real DAVE receive, speaker mapping, intro, supported/unknown answers, urgent question/thread, owner reply spoken once, mute/leave, and observed provider usage. Mark it unverified until performed.

## Sources and review status

- [OpenAI GPT-Transcribe model](https://developers.openai.com/api/docs/models/gpt-transcribe) and [pricing](https://developers.openai.com/api/docs/pricing).
- [OpenAI GPT-6 Luna modalities and pricing](https://developers.openai.com/api/docs/models/gpt-6-luna).
- [ElevenLabs models](https://elevenlabs.io/docs/overview/models), [v4 Turbo pricing](https://elevenlabs.io/pricing/api), and [dialogue WebSocket protocol](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd).
- [Discord voice protocol and DAVE](https://docs.discord.com/developers/topics/voice-connections).
- [discord.js voice 0.19.2](https://discord.js.org/docs/packages/voice/0.19.2) and [voice package changelog](https://github.com/discordjs/discord.js/blob/main/packages/voice/CHANGELOG.md).
- [Python receive extension DAVE issue](https://github.com/imayhaveborkedit/discord-ext-voice-recv/issues/64).

Self-review: concrete model IDs, budget scope, no-key development, migration, side effects, identity, transport recovery, cap behavior and verification boundaries are specified. No product dependencies or runtime code are changed by this draft. Written-spec approval is recorded above; written implementation-plan review remains outstanding.
