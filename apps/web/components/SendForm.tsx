"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";
import { sendToMeeting, type ActionState } from "@/app/actions";
import { DEFAULT_AGENT, DEFAULT_OWNER } from "@/lib/meeting";
import styles from "./SendForm.module.css";
import { WhenField } from "./WhenField";

/** Create a session, save the briefing, and launch the bot, in one step. */
export function SendForm({ ready }: { ready: boolean }) {
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionState, FormData>(sendToMeeting, null);
  const [agent, setAgent] = useState(DEFAULT_AGENT);
  const [scheduled, setScheduled] = useState(false);

  useEffect(() => {
    if (state?.ok && state.sessionId) router.push(`/meetings/${state.sessionId}`);
  }, [state, router]);

  const name = agent.trim() || DEFAULT_AGENT;

  return (
    <form action={action} className={styles.form}>
      <label className={styles.field}>
        <span className={styles.label}>Meeting link</span>
        <input name="meeting_url" type="url" required inputMode="url" placeholder="https://meet.google.com/abc-defg-hij" autoComplete="off" />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>What’s the meeting?</span>
        <input name="title" required maxLength={200} placeholder="Weekly payments sync" />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>
          What should {name} know? <span className={styles.optional}>Optional</span>
        </span>
        <textarea
          name="notes"
          rows={5}
          maxLength={100000}
          placeholder="Your update, decisions already made, facts people might ask about. It answers only from these notes and what’s said in the call."
        />
      </label>

      <div className={styles.pair}>
        <label className={styles.field}>
          <span className={styles.label}>Delegate’s name</span>
          <input name="agent_name" value={agent} onChange={(e) => setAgent(e.target.value)} maxLength={100} required />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Attending for</span>
          <input name="owner_name" defaultValue={DEFAULT_OWNER} maxLength={100} required />
        </label>
      </div>
      <p className={styles.hint}>
        People say “{name}” to ask it something, e.g. “{name}, what’s the latest on the budget?” It joins as “{name} (AI delegate)”.
      </p>

      <WhenField onChange={setScheduled} />

      <label className={styles.consent}>
        <input type="checkbox" name="consent" value="yes" required />
        <span>People in this meeting know {name} will join, transcribe it, and may answer questions out loud.</span>
      </label>

      <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={pending}>
        <span className="lamp" aria-hidden="true" />
        {pending ? "Sending…" : scheduled ? `Schedule ${name}` : `Send ${name} now`}
      </button>

      {!ready && <p className={styles.note}>The backend is missing some settings (see below), so the launch will fail until they’re added.</p>}

      <div aria-live="polite">
        {state?.error && (
          <p className={styles.error}>
            {state.error}
            {state.sessionId && (
              <>
                {" "}
                <Link href={`/meetings/${state.sessionId}`}>Open the meeting</Link> to try again.
              </>
            )}
          </p>
        )}
        {state?.ok && <p className={styles.ok}>{state.ok} Opening the meeting…</p>}
      </div>
    </form>
  );
}
