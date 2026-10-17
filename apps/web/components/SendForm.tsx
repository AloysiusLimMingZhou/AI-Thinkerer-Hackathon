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
  const [platform, setPlatform] = useState<'google_meet'|'discord'>('google_meet');
  const router = useRouter();
  const [state, action, pending] = useActionState<ActionState, FormData>(sendToMeeting, null);
  const [agent, setAgent] = useState(DEFAULT_AGENT);
  const [scheduled, setScheduled] = useState(false);
  const [values, setValues] = useState({ meeting_url: "", title: "", notes: "", owner_name: DEFAULT_OWNER });
  const update = (name: keyof typeof values, value: string) => setValues((old) => ({ ...old, [name]: value }));

  useEffect(() => {
    if (state?.ok && state.sessionId) router.push(`/meetings/${state.sessionId}`);
  }, [state, router]);

  const name = agent.trim() || DEFAULT_AGENT;

  return (
    <form action={action} className={styles.form}>
      <label className={styles.field}><span className={styles.label}>Platform</span><select name="platform" value={platform} onChange={e=>setPlatform(e.target.value as 'google_meet'|'discord')} disabled={pending||!!state?.sessionId}><option value="google_meet">Google Meet</option><option value="discord">Discord briefing</option></select>{state?.sessionId&&<input type="hidden" name="platform" value={platform}/>}</label>
      {platform === 'discord' && <p className={styles.hint}>Save knowledge here, then summon your delegate with /join in Discord. Choose the briefing from the optional picker.</p>}
      {platform === 'google_meet' && <label className={styles.field}>
        <span className={styles.label}>Meeting link</span>
        <input name="meeting_url" value={values.meeting_url} onChange={(e) => update("meeting_url", e.target.value)} type="url" required inputMode="url" placeholder="https://meet.google.com/abc-defg-hij" autoComplete="off" />
      </label>}

      <label className={styles.field}>
        <span className={styles.label}>{platform === 'discord' ? 'Briefing name' : 'Meeting name'}</span>
        <input name="title" value={values.title} onChange={(e) => update("title", e.target.value)} required maxLength={200} placeholder="Weekly payments sync" />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>
          What should {name} know? <span className={styles.optional}>Optional</span>
        </span>
        <textarea
          name="notes"
          value={values.notes}
          onChange={(e) => update("notes", e.target.value)}
          rows={5}
          maxLength={100000}
          placeholder="Your update, decisions already made, facts people might ask about. Factual answers use the knowledge you supply for this meeting."
        />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>Knowledge files <span className={styles.optional}>Optional</span></span>
        <input name="files" type="file" multiple accept=".txt,.md,.pdf,.docx" />
        <span className={styles.hint}>Text, Markdown, text PDFs or Word documents. Up to 5 files, 10 MiB each and 20 MiB combined.</span>
      </label>

      <div className={styles.pair}>
        <label className={styles.field}>
          <span className={styles.label}>Delegate’s name</span>
          <input name="agent_name" value={agent} onChange={(e) => setAgent(e.target.value)} maxLength={100} required />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Attending for</span>
          <input name="owner_name" value={values.owner_name} onChange={(e) => update("owner_name", e.target.value)} maxLength={100} required />
        </label>
      </div>
      <p className={styles.hint}>
        People say “{name}” to ask it something, e.g. “{name}, what’s the latest on the budget?” It joins as “{name} (AI delegate)”.
      </p>

      {platform === 'google_meet' && <WhenField onChange={setScheduled} />}

      {platform === 'google_meet' && <label className={styles.consent}>
        <input type="checkbox" name="consent" value="yes" required />
        <span>People in this meeting know {name} will join, transcribe it, and may answer questions out loud.</span>
      </label>}

      <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={pending}>
        <span className="lamp" aria-hidden="true" />
        {pending ? 'Saving…' : platform === 'discord' ? 'Save Discord briefing' : scheduled ? `Schedule ${name}` : `Send ${name} now`}
      </button>

      {platform === 'google_meet' && !ready && <p className={styles.note}>The backend is missing some settings (see below), so the launch will fail until they’re added.</p>}

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
