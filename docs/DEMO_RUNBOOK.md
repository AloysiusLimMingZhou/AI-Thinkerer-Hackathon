# Meeting Agent demo runbook

Use a private Google Meet with participants aware that an AI delegate transcribes and speaks. See README for setup and DISCORD_SETUP.md for optional Discord configuration. The dashboard is wired to the backend; it does not use fixture meeting data.

## Before presenting

- Run the locked backend suite, frontend typecheck and build.
- Keep one backend process, Next.js and the required public Recall origin running. Check authenticated `/recall/status` and `/discord/status`.
- Verify actual meeting admission and audible output separately; configured settings do not prove live readiness.
- Use a new session for each fresh bot launch. Confirm recording/AI consent and wait for `in_call_recording`.

## Demonstration

1. In the existing send form, use a Google Meet URL and your chosen owner/delegate names. Paste “Jamie owns the launch checklist.” and attach a TXT/Markdown file containing the fictional fact “The demo launch is Friday.”
2. Optionally try an invalid PDF with the valid file. The upload must fail atomically, keep form values, and submit no bot launch. Reselect the valid file and reuse the saved session.
3. Launch with consent. Ask “Alloy, when is the demo launch?” Show the answer's file/locator/excerpt in What Alloy said. Allow each reply to finish.
4. Ask “Alloy, what is the approved catering budget?” No source should supply that fact. Expected speech: “I don't know based on the knowledge I have. Is this urgent?”
5. First try “No rush.” It stays in notes with no Discord message. Ask a different unknown question, then clearly confirm urgency. Only that question tags the configured owner and gets its own Discord thread.
6. As the configured owner, send a short text answer in that thread. Expected meeting speech: “Aloy says: …”. Another person's reply must not be relayed. Ordinary answers never appear as Discord chat replies.
7. Leave/end the meeting. The dashboard keeps processing until the final transcript and minutes arrive, or shows a failure. The notes retain early decisions, unanswered questions and accepted owner replies. Reply again after the call: it is saved to notes with a “not spoken” acknowledgement; no rejoin occurs.

Missing Discord configuration must leave Meet usable and show that the owner could not be reached. Test rate limits and uncertain outcomes with the automated fakes, not repeated live pings.

## Claims and boundaries

This phase implements the knowledge and escalation foundation on Google Meet. Discord voice `/join`, receiving/sending Discord voice audio, production user auth, Drive import, token renewal, retention, full-duplex audio and a 2.5-second audible-response goal are pending.

The neutral product name is Meeting Agent. Alloy/Aloy are configurable session names, not a voice clone or claim to be the owner. A supplied fact does not grant authority to spend, approve commitments or invoke arbitrary tools.

Routine tests consume no provider credits. The opt-in live scripts use fictional data and real provider credits but never create a meeting bot. Use the backend handoff for recovery; ambiguous sends and interrupted speech require checking before retrying.
