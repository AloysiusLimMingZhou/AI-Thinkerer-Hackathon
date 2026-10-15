# Personal meeting agent: knowledge, urgency and shared pipeline

Date: 14 October 2026 (Asia/Kuala_Lumpur). Status: approved by the owner on 14 October 2026; implementation plan review is next.

## Intent and scope

Turn the hackathon prototype into the owner's personal meeting assistant. The website already asks what the assistant should know before dispatching it; extend that exact workflow with text and file knowledge. When an addressed factual question cannot be answered from the supplied knowledge, the assistant says it does not know and asks whether it is urgent. A confirmed urgent question tags the owner in a configured Discord channel. The owner has explicitly selected automatic spoken relay of their replies from that question's Discord thread.

Supported product platforms become Google Meet and Discord. Remove Slack integration and stop offering Zoom/Teams. Keep existing stored meeting records readable. Existing session-level delegate/owner names remain configurable; use “Meeting Agent” as the neutral product name until the owner supplies a new brand name.

This design covers the previously proposed steps 2 and 3. Step 1 establishes the runtime, checks and truthful documentation. This phase implements Google Meet attendance plus Discord escalation and reply relay. Full Discord voice attendance with `/join` remains the following transport milestone (steps 4 and 5); the common interfaces must support it, without claiming that it is already available.

Success means: a meeting created with pasted text and supported files can answer with traceable knowledge; unsupported questions follow the urgency flow; only confirmed urgency causes an owner mention; only the configured owner's thread replies are relayed, once, into the associated live meeting; both API/manual captions and Recall ingestion use the same decision pipeline.

## Approach

Recommended: retain FastAPI, SQLite, Recall for Meet, OpenAI and ElevenLabs; introduce focused knowledge, meeting-pipeline and Discord-escalation services. Keep knowledge explicitly attached to the meeting. This fits the existing form and avoids silently making private material available to every future meeting.

Alternatives considered:

- Put all new behavior directly into `RecallService`: less initial movement, but repeats the current mismatch with manual ingestion and makes the future Discord voice adapter duplicate logic.
- Build a separate Discord application with its own knowledge and decision pipeline: separates processes, but splits meeting state and requires duplicate urgency/answer rules.

The recommended design adds one optional Discord Gateway connection to the existing single-operator backend for receiving owner thread replies. It does not introduce another database, vector service, or multi-user account system.

## Knowledge input

Keep the existing textarea in “Send to a meeting” and the meeting's Briefing panel. Add a multiple-file selector in both places. Supported first-version file types: UTF-8 `.txt`, `.md`, text-containing `.pdf`, and `.docx`. PDF extraction uses `pypdf`; DOCX extraction uses `python-docx`. Do not fetch linked documents or execute active content. Image/scanned-only PDFs, password-protected files, old `.doc`, spreadsheets and presentations return a clear unsupported/extraction error rather than an empty success.

Limits: five files per submission; 10 MiB per file; 20 MiB combined file bytes; 100,000 characters of pasted text per submission; 500,000 extracted characters per file; 1,000,000 total knowledge characters per meeting. Enforce these in the backend as well as providing helpful frontend checks. The upload request limit is 22 MiB including multipart overhead, matched by Next.js Server Actions. Extraction must fail visibly rather than truncate silently. PDFs are limited to 300 pages; DOCX archives to 2,000 entries and 50 MiB total expanded content. Extraction has a 10-second per-file timeout in a terminable worker process. Unsupported or malformed files do not mutate existing knowledge.

Normalize text and create deterministic chunks up to 2,000 characters with a 200-character overlap, preserving file identity and page/paragraph/line locators. Store original display filename, content hash, normalized extracted text and chunks in SQLite. Preserve filenames for display only, never as filesystem paths. Original upload bytes are discarded after successful extraction; extracted content follows meeting retention. Duplicate file content within the same meeting is reported as already present rather than indexed twice.

File extraction and validation complete before a bot launch is submitted. A failed upload leaves the meeting unsent and shows which file failed; successfully stored knowledge is visible and reusable without creating a second meeting. An existing session can receive more knowledge during the call. An empty submission remains valid for note taking, but cannot support factual knowledge answers.

Add authenticated endpoints for listing meeting knowledge and ingesting multipart text/files; retain the existing JSON `/context` route for backward compatibility. Update the frontend backend client to forward `FormData` without forcing a JSON content type. Render the knowledge list from the knowledge endpoint instead of reconstructing it only from historical events, so calendar-copied knowledge is visible too.

## Supported answers and citations

Replace `Brain.answer -> str` with a structured result: `kind` (`supported`, `unknown`, `social`), `text`, and `evidence[]`. Evidence identifies a retrieved knowledge chunk and an exact supporting excerpt. A normal factual answer requires valid evidence from this meeting's supplied knowledge. Recent transcript and previous assistant replies help interpret a follow-up, but are not substitutes for owner-supplied facts or approvals.

Retrieval no longer falls back to arbitrary first notes. Search chunk text/title with local token scoring and return only positive matches. Explicit owner-profile notes may accompany results to guide style but do not automatically substantiate factual answers. Select at most eight evidence chunks. For short follow-ups, include the immediately preceding addressed question in the retrieval query so “What about its deadline?” can find the relevant topic.

Validate every evidence ID against selected chunks and every excerpt against stored text. Reject invalid structured output, missing required evidence and empty answers as unsupported; never attach all retrieved notes as citations. The model is still responsible for whether excerpts semantically support its wording; exact excerpt validation is provenance checking, not a mathematical guarantee of truth. Keep answers concise and prompts explicit about this responsibility.

Greetings, identity questions and ordinary conversational acknowledgements can use the social result without citations. Document contents and participant speech cannot choose tools, notification destinations, recipients or permissions. The orchestrator alone owns escalation.

Store source filename/page/paragraph/excerpt in the Q&A record and event payload for dashboard inspection. Answers remain spoken; do not post ordinary meeting answers to Discord text channels. Extend decision events with a distinct unknown/defer outcome so the UI can show uncertainty accurately.

## Unknown-answer and urgency state machine

For an unsupported addressed factual question, persist a question record associated with the session, source utterance and requesting speaker. Speak exactly: “I don't know based on the knowledge I have. Is this urgent?” Do not claim that the owner has been notified.

Open a 60-second urgency response window when the unknown-answer prompt is queued; cancel it if playback fails. This allows natural replies that arrive before a playback-completion acknowledgement. Use utterance-processing time for the manual rehearsal path. The same speaker can answer naturally without repeating the wake name. A clearly addressed response from another participant may also confirm the referenced question. Generic “yes” from another speaker, unknown identity, overlapping questions, or ambiguous urgency must not trigger a notification.

Interpret negative forms such as “not urgent”, “no rush” and “don't contact them” before positive forms. For one unambiguous pending question, “yes”, “it's urgent” or equivalent clear confirmation escalates; “no” records it for the minutes without notifying. If the urgency reference is ambiguous, ask which question is urgent. A timeout leaves it as an unanswered, non-escalated question in the notes. A rephrased repeat by the same speaker reuses the pending record during its window.

Persist states covering `awaiting_urgency`, `not_urgent`, `urgency_expired`, `escalation_queued`, `awaiting_owner`, `delivery_failed`, and `answered`. An explicit owner reply is eligible even if the urgency window has expired after escalation. Store urgent and nonurgent unanswered questions in final minutes; do not rely on the model to infer which questions were unresolved.

When escalation is configured and accepted into its durable outbox, say “I'll ask [owner name] in Discord.” Say “[owner name] has been notified” only after Discord confirms delivery. If Discord is unavailable or missing configuration, say “I couldn't reach [owner name] in Discord. I've kept the question in the meeting notes.” Preserve the question and an actionable delivery status in the dashboard.

## Discord escalation and owner reply relay

Configuration is server-only: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_ESCALATION_CHANNEL_ID`, `DISCORD_OWNER_USER_ID`. IDs are explicit operator configuration, never model-generated or guessed from display names. Provide readiness/status output containing configuration names and connection state, never secret values. A missing Discord configuration does not prevent Google Meet note taking.

Use a bot Gateway client for reply events and a REST client for message/thread operations. Grant only the channel permissions needed to view/send messages, read history and create/send in threads. Reading ordinary owner text replies requires Discord's Message Content intent; document its Developer Portal setup. Process events only from the configured guild and mapped question threads.

Create one parent message in the configured text channel containing only the configured owner mention, meeting title, requesting speaker, unresolved question and a request to reply in the associated thread. Omit unrelated transcript and document contents. Keep each Discord message at most 2,000 characters; if the exact question does not fit, place a labelled first segment in the parent and the remaining segments in the thread, with at most 1,800 question characters per segment. Mention the owner only once. Suppress all other user, role and everyone mentions using explicit `allowed_mentions`. Create a question-specific thread and persist both message and thread IDs. An owner reply to the tagged parent message can also map to the same question while the thread is being established, preventing a race during creation.

Persist an escalation outbox before sending. Use a stable request nonce and retain provider IDs; transient failures respect Discord rate limits. Duplicate urgency confirmations reuse the same escalation. An ambiguous message-creation timeout becomes `needs_attention` instead of blindly sending another owner ping; expose it for reconciliation. Do not claim unconditional exactly-once network delivery.

Accept new plain-text messages only from `DISCORD_OWNER_USER_ID` in a mapped thread (or direct reply to its mapped parent). Ignore bot/webhook messages, other users, unrelated channels, duplicate message IDs, edits and attachments. The reply explicitly provided in this question thread is authorized for relay into that meeting. Queue the owner's text through TTS and the session's playback adapter, introduced as “[owner name] says: …”. Record its Discord message ID as the deduplication key and knowledge provenance. It is supplied knowledge for this meeting, not a global knowledge update.

The first accepted owner reply resolves the question; additional owner replies in the same thread can provide corrections while the meeting is live. Limit each relay to 2,000 text characters; longer replies remain in Discord with a request to shorten them, rather than silent truncation. Recheck meeting liveness before playback. Replies after meeting end are saved with the question and reflected in notes, with an acknowledgement that they were not spoken. Do not reopen or rejoin meetings. Playback uncertainty after a crash requires attention rather than automatic replay.

## Shared meeting pipeline

Introduce `MeetingService` as the sole owner of transcript ingestion, gate decisions, knowledge retrieval, structured answers, urgency state, Q&A/events, and meeting finalization. Introduce a platform-neutral playback interface for queueing speech, liveness and mute/stop operations. Define input utterances with provider event ID, participant ID, display name, UTC speech timestamp, final/partial flag and own-agent flag.

Recall normalizes its webhook payload into that input; it continues to own Meet launch/admission, webhook verification, transport jobs and its browser media/audio queue. Use provider speech timestamps when available and a documented receive-time fallback. Manual API ingestion uses the same service with a preview/no-playback mode; it cannot trigger real Discord notifications from the rehearsal form. Force-answer bypasses address detection, not evidence requirements or notification authorization.

Deduplicate ingest by session/platform/provider event ID before side effects. Preserve the current stale-caption and bounded-audio protections. Exclude the agent's own speech before opening follow-up/urgency windows. Serialize decision state per session while preventing a slow model request in one meeting from blocking another meeting's notifications or finalization. Single-worker SQLite remains the deployment assumption for this phase.

Use a common finalization service for final transcripts, unresolved questions, owner answers and minutes. Keep a `processing` phase distinct from `ended`/`ready` so the UI continues polling until final transcript and minutes are ready or a visible failure occurs. Generate minutes over the whole transcript through bounded chronological segments plus a final synthesis; preserve early decisions and combine every unresolved question and owner relay. Never silently take only the last 500 entries.

The future Discord voice adapter must supply the same normalized inputs, liveness and playback acknowledgements. It needs a separately verified audio receive/send and DAVE-compatible transport before `/join` is marked available. No Discord voice SDK is selected by this phase.

## Platform reduction and compatibility

Remove Slack, Microsoft and Zoom OAuth setup/import paths, settings and active capability advertisements. Only Google OAuth remains for Calendar/Meet context. Replace Slack-specific tests with Google import tests and explicit rejection tests for removed providers. Historical stored notes whose source is Slack or another removed provider remain readable, and no migration deletes their text or credentials automatically. Removed credentials are no longer used; document how the operator can revoke/delete legacy connections.

For new meeting dispatch, accept Google Meet URLs only. Update both frontend and backend validation, calendar eligibility, labels, error copy, examples and setup documentation consistently. Preserve historical Zoom/Teams records for viewing/export; they cannot be relaunched through the new create flow. Represent Discord's notification capabilities separately from the future voice attendance capability so `/platforms` and the website do not overstate availability.

Keep existing HTTP endpoint paths where possible. Add optional fields to event/Q&A responses, update TypeScript types and event rendering, and migrate SQLite additively. Back up a real database before upgrading; tests cover opening a database with the current schema. No destructive data reset.

## Security and operational boundary

Continue the current trusted single-operator deployment. Keep provider/Discord credentials in backend environment variables and the backend token in Next.js server-only configuration. Do not expose the frontend publicly without its own authentication; full multi-user login remains outside this phase. Allowlist Discord IDs and keep notifications tied to explicit urgency confirmation. Do not read arbitrary Discord history into knowledge.

Uploaded text is untrusted reference material. A document saying “tag everyone”, an urgent transcript without a tracked question, or a non-owner thread reply cannot trigger a message or spoken owner answer. Fake transports cover side effects in automated tests; no live call, bot ping or provider billing occurs during routine verification.

## Files and responsibilities

- `knowledge.py` and dedicated knowledge routes/store: extraction, limits, chunking, provenance and retrieval.
- `meeting_service.py` and shared models: normalized input, gate/answer state and platform-neutral orchestration.
- `escalations.py` and dedicated store: persisted question lifecycle, outbox and owner reply deduplication.
- `discord_client.py`: Discord transport/Gateway behavior and readiness; no meeting-answer policy.
- `services.py`: structured OpenAI answers and TTS; `minutes.py`: bounded full-transcript finalization.
- Existing Recall modules: Meet transport integration with the new common services.
- Existing Next.js form/actions/backend client: text/file submission, knowledge visibility, question status and finalization polling.
- Configuration, Google integration module, manifests/lockfiles, tests and README/handoff: reduced platform scope and reproducible setup.

## Acceptance checks

1. Locked installation, backend suite, frontend typecheck and production build pass; a new clone can reproduce the documented commands.
2. Pasted text plus a UTF-8 text/Markdown file, a text PDF and a DOCX can be added from the meeting form; extracted sources/locators appear in the briefing. Invalid, oversized, encrypted, empty and malformed files show actionable errors and do not launch a bot.
3. A supported question produces a concise spoken answer with only verified source references. Unrelated or absent knowledge produces the exact unknown/urgency prompt, without fabricated citations.
4. Negative, ambiguous, expired, duplicate and other-speaker urgency responses do not ping the owner. A confirmed urgent question creates one durable escalation and a mapped Discord thread.
5. An authorized owner reply in that thread is recorded and queued once into the associated live meeting. Other senders, duplicate messages, edits and replies to another session cannot be relayed.
6. Missing Discord setup, rate limits, ambiguous sends, thread-creation failure, process restart and meeting end leave truthful statuses and no duplicate notification or stale speech.
7. API preview and Recall paths produce consistent decisions; preview never sends notifications. Provider IDs/timestamps, self-voice exclusion and the existing queue/stale protections remain covered.
8. Minutes retain an early decision from a transcript longer than 500 entries, unanswered questions and later owner replies. The UI updates through final processing rather than stopping at call end.
9. Slack/Zoom/Teams are absent from new platform flows and credentials/setup. Google import still works; historical records still open/export; old databases migrate without losing data.

References checked during design: [Discord message API](https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx), [Gateway intents](https://github.com/discord/discord-api-docs/blob/main/developers/events/gateway.mdx), [Next.js Server Action upload limits](https://nextjs.org/docs/app/api-reference/config/next-config-js/serverActions), [Discord voice requirements for the later adapter](https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx).
