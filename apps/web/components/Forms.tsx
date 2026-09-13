"use client";

import { useActionState, useEffect, useRef } from "react";
import type { ActionState } from "@/app/actions";
import styles from "./Forms.module.css";

type Action = (prev: ActionState, form: FormData) => Promise<ActionState>;

function Feedback({ state }: { state: ActionState }) {
  if (!state) return null;
  return (
    <p className={state.error ? styles.error : styles.ok} aria-live="polite">
      {state.error ?? state.ok}
    </p>
  );
}

/** POST /sessions/{id}/minutes: write (or rewrite) the minutes from what's stored. */
export function WriteMinutesButton({ action, label }: { action: (prev: ActionState) => Promise<ActionState>; label: string }) {
  const [state, run, pending] = useActionState<ActionState, FormData>((prev) => action(prev), null);
  return (
    <form action={run} className={styles.inline}>
      <button type="submit" className="btn btn-quiet" disabled={pending}>
        {pending ? "Writing… this can take a minute" : label}
      </button>
      <Feedback state={state} />
    </form>
  );
}

/** POST /sessions/{id}/context: add a briefing note. */
export function AddNoteForm({ action, agent }: { action: Action; agent: string }) {
  const [state, run, pending] = useActionState<ActionState, FormData>(action, null);
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state?.ok) ref.current?.reset();
  }, [state]);
  return (
    <form ref={ref} action={run} className={styles.stack}>
      <label className={styles.field}>
        <span>Title</span>
        <input name="title" maxLength={300} placeholder="Project status" />
      </label>
      <label className={styles.field}>
        <span>Note</span>
        <textarea name="content" rows={4} maxLength={100000} required placeholder={`Facts ${agent} can use when someone asks. It won’t go beyond what’s written here.`} />
      </label>
      <button type="submit" className="btn btn-quiet" disabled={pending}>
        {pending ? "Saving…" : "Add note"}
      </button>
      <Feedback state={state} />
    </form>
  );
}

/** POST /sessions/{id}/utterances: rehearse the speaking rules without a call. */
export function RehearseForm({ action, agent }: { action: Action; agent: string }) {
  const [state, run, pending] = useActionState<ActionState, FormData>(action, null);
  const ref = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (state?.ok) ref.current?.querySelector<HTMLInputElement>("input[name=text]")?.select();
  }, [state]);
  return (
    <form ref={ref} action={run} className={styles.stack}>
      <input type="hidden" name="agent" value={agent} />
      <label className={styles.field}>
        <span>Who’s speaking</span>
        <input name="speaker" defaultValue="Guest" maxLength={100} />
      </label>
      <label className={styles.field}>
        <span>What they say</span>
        <input name="text" required maxLength={10000} placeholder={`${agent}, what’s the latest on the budget?`} autoComplete="off" />
      </label>
      <button type="submit" className="btn btn-quiet" disabled={pending}>
        {pending ? "Checking…" : "Try it"}
      </button>
      {state?.answer ? (
        <div className={styles.answer} aria-live="polite">
          <span className="lamp" aria-hidden="true" />
          <p className="verbatim">{state.answer}</p>
        </div>
      ) : (
        <Feedback state={state} />
      )}
    </form>
  );
}
