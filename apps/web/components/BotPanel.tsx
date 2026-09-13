"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import type { ActionState } from "@/app/actions";
import type { Tone } from "@/lib/meeting";
import styles from "./BotPanel.module.css";
import { WhenField } from "./WhenField";

type Action = (prev: ActionState, form: FormData) => Promise<ActionState>;

interface Props {
  agent: string;
  owner: string;
  label: string;
  detail: string;
  tone: Tone;
  /** Recall's raw state, shown verbatim so unknown states are never hidden. */
  stateCode?: string;
  since?: string;
  hasBot: boolean;
  canLeave: boolean;
  canSay: boolean;
  launch: Action;
  leave: (prev: ActionState) => Promise<ActionState>;
  say: Action;
}

export function BotPanel({ agent, owner, label, detail, tone, stateCode, since, hasBot, canLeave, canSay, launch, leave, say }: Props) {
  return (
    <section className={`${styles.panel} ${styles[tone]}`} aria-labelledby="bot-state">
      <div className={styles.head}>
        <div className={styles.status}>
          <h2 id="bot-state" className={styles.label}>
            <span className={`lamp ${tone === "live" ? "" : "lamp-off"} ${styles.lamp}`} aria-hidden="true" />
            {label}
          </h2>
          <p className={styles.detail}>{detail}</p>
          {stateCode && (
            <p className={styles.code}>
              Recall state <span className="verbatim">{stateCode}</span>
              {since && <> since {since}</>}
            </p>
          )}
        </div>
        {canLeave && <LeaveButton agent={agent} leave={leave} />}
      </div>

      {!hasBot && <LaunchForm agent={agent} launch={launch} />}
      {canSay && <SayForm agent={agent} owner={owner} say={say} />}
    </section>
  );
}

function Feedback({ state }: { state: ActionState }) {
  return (
    <p className={state?.error ? styles.error : styles.ok} aria-live="polite">
      {state?.error ?? state?.ok ?? ""}
    </p>
  );
}

function LeaveButton({ agent, leave }: { agent: string; leave: Props["leave"] }) {
  const [state, action, pending] = useActionState<ActionState, FormData>((prev) => leave(prev), null);
  const [confirming, setConfirming] = useState(false);
  return (
    <form action={action} className={styles.leave}>
      {confirming ? (
        <>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending ? "Asking…" : `Yes, remove ${agent}`}
          </button>
          <button type="button" className="btn btn-quiet" onClick={() => setConfirming(false)}>
            Keep it
          </button>
        </>
      ) : (
        <button type="button" className="btn btn-quiet" onClick={() => setConfirming(true)}>
          Remove {agent} from the meeting
        </button>
      )}
      {state && <Feedback state={state} />}
    </form>
  );
}

function SayForm({ agent, owner, say }: { agent: string; owner: string; say: Action }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(say, null);
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state?.ok) formRef.current?.reset();
  }, [state]);
  return (
    <form ref={formRef} action={action} className={styles.say}>
      <label htmlFor="say-text" className={styles.sayLabel}>
        Say something in the meeting
      </label>
      <div className={styles.sayRow}>
        <input id="say-text" name="text" maxLength={5000} placeholder={`e.g. “${owner} will send the numbers by Friday.”`} autoComplete="off" />
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {pending ? "Sending…" : "Say it"}
        </button>
      </div>
      <p className={styles.hint}>Played in {agent}’s voice to everyone in the call. It doesn’t need its name to be said first.</p>
      <Feedback state={state} />
    </form>
  );
}

function LaunchForm({ agent, launch }: { agent: string; launch: Action }) {
  const [state, action, pending] = useActionState<ActionState, FormData>(launch, null);
  const [scheduled, setScheduled] = useState(false);
  return (
    <form action={action} className={styles.launch}>
      <WhenField onChange={setScheduled} />
      <label className={styles.consent}>
        <input type="checkbox" name="consent" value="yes" required />
        <span>People in this meeting know {agent} will join, transcribe it, and may answer questions out loud.</span>
      </label>
      <button type="submit" className={`btn btn-primary ${styles.go}`} disabled={pending}>
        <span className="lamp" aria-hidden="true" />
        {pending ? "Sending…" : scheduled ? `Schedule ${agent}` : `Send ${agent} now`}
      </button>
      <Feedback state={state} />
    </form>
  );
}
