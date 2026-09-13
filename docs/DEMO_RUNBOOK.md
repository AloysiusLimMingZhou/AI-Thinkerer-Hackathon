# Alloy: a briefed delegate, inside the meeting

## Honest demo claim

When Aloy is busy, Alloy joins a meeting as a visibly identified AI delegate, listens
to the conversation, answers from the briefing Aloy supplied, and preserves the
transcript and minutes. The value is shared, timely participation in the place the
team is already making decisions—not asking someone to copy the meeting into a chatbot.

Do not describe Alloy as Aloy himself, a voice clone, or a system that can secretly
approve spending or contact people. Its conversational role is explanation and
discussion, not unrestricted execution.

## Before presenting

- Pull the backend changes; use `docs/BACKEND_HANDOFF.md` for the unchanged HTTP API.
- Verify the frontend uses actual session IDs and endpoints, not fixture data.
  The backend changes do not implement that frontend wiring.
- Keep the backend and both tunnel processes alive. Check public `/health` and
  authenticated `/recall/status`. Configuration presence alone is not a live test.
- Run `uv run pytest -q`. Optionally run `uv run python scripts/eval_conversation.py`
  to exercise real providers with fictional data; it costs API credits but joins no call.
- Use a private test meeting. Tell participants an AI delegate will transcribe and
  speak. Be ready to admit it and confirm actual audible playback.
- Wait for `in_call_recording`; never label a queued launch as joined.

## A 90-second end-to-end demonstration

1. **Prepare, in the frontend.** Create a new session: owner `Aloy`, delegate `Alloy`,
   title `Launch planning`, and the actual meeting URL. Add these explicitly fictional notes:
   - `source: owner-profile`: Aloy uses he/him, prefers concise conversational English,
     and wants the team to know approved facts without inventing commitments.
   - `source: briefing`: The demo launch is Friday. Jamie owns the checklist.
     The budget is undecided. No spending has been approved.
2. **Enter the environment.** Confirm consent and launch. Show the bot's visible
   AI label and the status progressing from waiting room to live transcription.
3. **Prove context, not just chat.** Ask: “Alloy, when is the launch?” Expected fact:
   Friday. Follow immediately with “Who owns the checklist?” Expected fact: Jamie,
   without repeating the wake name.
4. **Prove restraint.** Ask: “Alloy, what is the budget?” Expected: undecided, not an
   invented number. Ask: “Can you approve ten thousand?” Expected: cannot approve;
   approval belongs to Aloy. No promise to notify, flag or send anything.
5. **Prove natural participation.** “Alloy, how are you?” should get a short social
   reply, not a report about Aloy's feelings. Speech about someone else should not
   routinely interrupt the call. Allow the reply to finish before the next test.
6. **Close the loop.** Leave through the frontend. Show the persisted transcript;
   wait for final transcript/minutes events and show decisions, action items and
   open questions. Do not claim minutes are ready before they exist.

## Evidence for the rubric

| Criterion | What to show, not merely claim |
| --- | --- |
| Core functionality | Real briefing → actual Meet bot → heard question → audible answer → saved transcript/minutes |
| Theme alignment | Teammates get the absent person's approved context without leaving the shared meeting |
| Technical execution | Signed webhooks, idempotent launch, persisted jobs/audio, bounded reply queue, explicit failures and measured latency |
| Usefulness and control | Same-speaker follow-ups, briefing-grounded answers, honest limits, visible AI identity, operator launch/leave controls |

## Known limits and recovery

- Live validation so far is Google Meet. Do not imply Zoom/Teams/calendar have all
  been live-tested. Calendar onboarding remains out of the demo scope.
- This is a single-operator prototype, with a shared backend bearer token. Keep it
  server-side; authenticate a public frontend proxy. Never commit `.env` or keys.
- Turn-taking is bounded heuristics, not perfect conversational diarization.
  One reply may wait behind current speech; additional requests log `reply queue full`.
  There is no interruption/barge-in or streaming speech generation.
- Generation timings exclude transcription, transport and playback. Report observed
  measurements; never advertise subsecond total response time based on TTS alone.
- If speech fails, inspect `voice.failed` and job status; do not claim a queued reply
  was heard. Avoid blindly replaying a failed/ambiguous request.
- New test, new session. Do not launch a duplicate bot into a meeting to fix a UI bug.
- Notes are text supplied by the frontend; parsing uploaded PDFs/docs is not added
  by these backend changes. Citations are candidate reference notes, not verified
  per-sentence source attribution.

## Model choices

Spoken replies use GPT-4.1 mini, selected for brief non-reasoning responses; minutes
retain GPT-5 mini. Charlie uses ElevenLabs Flash v2.5. These choices trade some depth
and speech richness for faster turn-taking, and were checked with live API tests.
Sources: [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
and [ElevenLabs model guidance](https://elevenlabs.io/docs/eleven-api/choosing-the-right-model).

Scores depend on the final working demonstration; this checklist does not guarantee them.
