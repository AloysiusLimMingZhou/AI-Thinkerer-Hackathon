# Discord voice setup and acceptance

Implementation date: 15 October 2026. Offline behavior is tested; live DAVE reception, model access, transcription accuracy, voice compatibility and audible delivery are unverified.

## Install locally

Use one Python 3.13 backend, Node 22.12+ and FFmpeg with libopus. Node 24.18.0 and FFmpeg 8.1.2 were used for local fixture tests.

```powershell
uv sync --locked
npm ci --prefix apps/discord-voice
node --input-type=module -e "import {generateDependencyReport} from './apps/discord-voice/node_modules/@discordjs/voice/dist/index.mjs'; console.log(generateDependencyReport())"
ffmpeg -version
```

The dependency report must show @discordjs/voice 0.19.2, an Opus implementation and @snazzah/davey. The lock resolves opusscript 0.0.8 and davey 0.1.12. If the report command is unavailable for a future package layout, run it from `apps/discord-voice` and import `@discordjs/voice` directly.

Configure backend root `.env` locally; never paste secrets into chat:

- `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_OWNER_USER_ID`, `DISCORD_ESCALATION_CHANNEL_ID`.
- `OPENAI_API_KEY`, `OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe`, `OPENAI_MODEL=gpt-6-luna`, `OPENAI_ANSWER_MODEL=gpt-6-luna`.
- `ELEVENLABS_API_KEY`, compatible `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID=eleven_v4_turbo`.
- `BACKEND_API_TOKEN`, `WEB_BASE_URL` (actual website origin).
- `DISCORD_NODE_EXECUTABLE=node`, `DISCORD_FFMPEG_EXECUTABLE=ffmpeg`; use full paths if needed.
- `AI_MONTHLY_SOFT_LIMIT_USD=5`, `AI_MONTHLY_HARD_LIMIT_USD=8`, `AI_BUDGET_TIMEZONE=Asia/Kuala_Lumpur`.

Missing keys do not prevent application startup, briefings or viewing saved notes. An attendance request fails readiness before joining.

## Discord application

In the Developer Portal enable **Message Content intent**. The worker requests Guilds, GuildVoiceStates, GuildMessages and MessageContent, without privileged GuildMembers intent.

Invite the bot with `bot` and `applications.commands` scopes. In the voice channel allow **View Channel, Connect, Speak**. In the configured escalation text channel allow View Channel, Send Messages, Create Public Threads, Send Messages in Threads and Read Message History. Avoid Administrator. Thread access must remain available for the configured owner's new replies.

Commands are registered explicitly in the configured guild only:

```powershell
uv run --locked python -m meeting_agent.discord_setup
```

This command performs Discord REST writes. Run it when ready to register commands; importing the module and starting the backend never register commands. Configuration must include a numeric guild ID. No global commands are created.

Set `DISCORD_VOICE_ENABLED=true` and restart the backend after installation/configuration. Node then owns the single Gateway connection and forwards owner messages to Python. With the flag false, the optional Python Gateway remains responsible for Meet escalation replies.

## Attend a meeting

Prepare a Discord briefing on the website with text and/or supported files, then:

```text
/join channel:#voice-channel briefing:<choose prepared briefing>
/status
/mute
/unmute
/stop-speaking
/leave
```

The channel picker accepts standard voice channels, not Stage channels. Briefing autocomplete returns only prepared templates, never source excerpts. Leaving briefing empty intentionally starts without factual knowledge. Default empty-briefing names are Owner and Alloy; choose a website briefing to customize names.

Only the exact configured owner in the exact configured guild can control attendance. Python rechecks authorization. Replies to controls are ephemeral. Repeat interactions and same-channel joins reuse the existing attendance; another channel requires leaving first.

The introduction identifies the agent and transcription. The website distinguishes a connected call, receiver readiness and completed introduction playback. A connected socket alone does not establish healthy note taking. There are at most two STT requests in flight, eight waiting clips, 15-second clips, eight active capture buffers, 700 ms end silence and two speech intents. Bots and own-user streams are excluded by stable IDs. Capture failures/overflow appear as gaps.

Normal addressed answers remain voice only. For an unknown question, a clear speaker-bound urgency confirmation creates one question thread in the configured escalation channel and mentions only the configured owner. New plain-text replies by that owner in the question thread are saved and relayed as "[owner] says: ...". Edits, bot/webhook/attachment replies and unrelated threads cannot authorize speech. Replies after departure are saved; muted Discord replies are saved without automatic replay.

## Budget and recovery

The USD 5 soft warning is visible on the website and private /status; it does not ping the escalation channel. Every paid request shares the USD 8 estimated hard cap, including Meet, preview and minutes. Held/uncertain reservations consume availability across restart. Do not delete the ledger to free a hold without reconciling provider usage.

Budget refusal in a live Discord pipeline clears pending work, cancels speech and leaves without paid TTS notice. Transcript, deterministic appendix and any successful summary stages remain. Budget-blocked notes require an explicit Generate notes action after reset/configuration; polling and rollover do not retry.

Budget estimates exclude Recall attendance, hosting, subscriptions, taxes, other applications and price changes. They are not a provider invoice guarantee.

No automatic rejoin occurs after worker/parent loss. Unfinished attendance becomes interrupted, uncertain speech needs attention, and generation IDs reject delayed events. An uncertain join/leave must be reconciled through worker status before a new connection is attempted. The worker disconnects when its parent pipe closes. Empty channels have a 60-second grace; maximum attendance defaults to four hours (`DISCORD_MAX_ATTENDANCE_SECONDS=14400`, allowed 60-14400).

Before upgrades, stop the backend and back up SQLite/WAL/SHM. Keep one backend process. Do not expose the unauthenticated local website publicly.

## Later private-call acceptance (not performed)

After credentials are supplied and the operator authorizes a private test:

1. Register guild commands explicitly; verify unauthorized users and Stage channels are refused.
2. Join with a prepared briefing. Hear the disclosure introduction; verify Gateway/connection/decoder/receiver/player and introduction state.
3. Speak from two accounts (including identical display names). Verify separate speakers, timestamps and a continuous speech split beyond 15 seconds.
4. Ask a supported question, then an unsupported one. Confirm urgency and verify one owner mention/thread. Reply from that thread and hear it once in the associated call.
5. Check mute/unmute, stop-speaking, owner reply while muted, leave, empty-channel grace and parent shutdown.
6. Compare STT text with what was actually said, especially accent, names, crosstalk and noisy speech. Measure billed audio/characters/tokens against the ledger.
7. Review whole-call minutes, source evidence, unanswered questions and saved late replies. Simulate cap refusal with fake transports, not by deliberately buying usage.

Official references: [Discord voice/DAVE](https://docs.discord.com/developers/topics/voice-connections), [voice 0.19.2](https://discord.js.org/docs/packages/voice/0.19.2), [OpenAI speech-to-text](https://developers.openai.com/api/docs/guides/speech-to-text), [ElevenLabs dialogue WebSocket](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd).
