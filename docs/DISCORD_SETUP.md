# Discord escalation setup and recovery

This optional bot receives urgent questions and owner answers for Google Meet sessions. **It does not join Discord voice channels or implement `/join`.** Meet notes work when Discord is not configured.

## Configure

1. Create a bot in the Discord Developer Portal and install it in your server using the `bot` scope. Enable **Message Content Intent** under Bot → Privileged Gateway Intents. The Gateway client uses guilds, guild messages and message content; it does not request member, presence or voice intents.
2. In a dedicated text channel, grant View Channel, Send Messages, Read Message History, Create Public Threads and Send Messages in Threads. Ensure the configured owner can view and reply in that channel/its threads. No Administrator or Mention Everyone permission is needed.
3. Enable Discord Developer Mode to copy the server, text channel and your user IDs. Set these backend-only variables in root `.env`, then restart the backend:

```dotenv
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ESCALATION_CHANNEL_ID=
DISCORD_OWNER_USER_ID=
```

Never put the bot token in a `NEXT_PUBLIC_*` setting, URL, screenshot or commit. GET `/discord/status` returns missing variable names, Gateway state and `voice_attendance_available: false`; it never returns the values. A connected Gateway is needed for live owner replies; presence of configuration alone does not prove permissions work.

The backend validates that the escalation destination is a text channel in the configured server. Targets and the sole allowed owner mention come from these settings, never from a document, transcript or model output.

## Question and reply behavior

An addressed unknown question is stored and receives the fixed spoken “I don't know…” prompt. The requesting speaker has 60 seconds to confirm urgency. Another identifiable speaker must explicitly address the agent and refer to that question. Ambiguous confirmations ask which question; negative or uncertain wording does not notify. Muted, preview, self and unknown-participant input cannot escalate.

Confirmed urgency creates a durable outbox entry before sending. The parent message includes only the owner mention, meeting title, requesting speaker and exact question. It requests a reply in the associated thread. Questions longer than one message are segmented into at most 1,800 question characters per message; every message is at most 2,000 characters. Only the first message allows the configured owner mention; roles, everyone and other user mentions are suppressed throughout.

Only **new plain-text messages by the configured owner** in a mapped question thread, or direct replies to its parent in the configured channel, are accepted. Other users, bots, webhooks, edits, attachments and duplicate message IDs are ignored. Owner answers do not require a slash command: the approved policy relays them automatically as “[owner] says: …”. Keep each answer within 2,000 characters. Longer replies receive a request to shorten them and are not spoken. Additional new messages can correct earlier answers; editing an old message is ignored.

Accepted text becomes knowledge for that meeting and is recorded with its Discord message ID. Live replies wait durably when the audio queue is full or speech is muted. After call end they are saved into notes with a “not spoken” acknowledgement; they never cause rejoining. The first accepted answer resolves the tracked question. Playback failure remains visible even when the text was saved successfully.

## Inspect and recover

GET `/sessions/{id}/questions` and the dashboard show `awaiting_urgency`, `not_urgent`, `urgency_expired`, `escalation_queued`, `awaiting_owner`, `delivery_failed` and `answered`, plus delivery/playback errors. The SQLite `escalation_outbox` and `owner_replies` tables hold the detailed work state. Authenticated session events include question changes, owner replies, relay failures and acknowledgement failures.

Rate-limited requests respect Discord's `retry_after` and are retried with a bounded attempt count. Persisted parent/thread IDs let a known thread failure resume without creating another parent ping. Stable nonces use Discord's recent-message deduplication; they are not an unconditional exactly-once network guarantee.

A timeout, server error or crash during an external write has an uncertain result. Such work becomes `needs_attention` (the question shows `delivery_failed`) and is **not automatically replayed**. Check the configured channel and thread before doing anything else:

- If delivery happened, stop the backend, back up SQLite, and reconcile the verified parent/thread IDs in `unanswered_questions` and `escalation_outbox`; mark the outbox sent and question awaiting owner. Do not reset it to a fresh queued ping.
- If you have verified no message exists, an operator can reset that specific outbox entry after backing up the DB. There is no automatic retry button for uncertain Discord writes in this phase.
- If an owner reply's speech is uncertain, inspect the call before using explicit manual speech. Do not reset an interrupted reply for automatic replay. The text remains in notes.
- Failed post-call acknowledgements are recorded as `discord.ack_failed`; they do not erase the answer or trigger repeated acknowledgements.

Missing intent, authentication or permissions can leave Gateway state failed or question delivery failed. Correct configuration and restart; inspect pending work before any manual retry. Keep one backend process to avoid multiple Gateway/outbox workers.

## Operator acceptance test

Use a private consenting Google Meet and fictional data. Confirm one urgent question creates one parent/thread, a non-owner cannot relay, an owner reply is heard once, and a post-call reply is saved without audio. Routine automated tests use fake Discord/Recall/model transports and never post real messages.

Primary references: [Discord message API and nonce behavior](https://docs.discord.com/developers/resources/message), [thread creation](https://docs.discord.com/developers/resources/channel#start-thread-from-message), [rate limits](https://docs.discord.com/developers/topics/rate-limits), [discord.py intent setup](https://discordpy.readthedocs.io/en/stable/intents.html).
