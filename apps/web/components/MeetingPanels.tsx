import Markdown from "react-markdown";
import type { ActionState } from "@/app/actions";
import type { ContextNote, Minutes } from "@/lib/api-types";
import { clock, plural, shortDay } from "@/lib/format";
import { reasonText, type ActivityItem, type AnswerItem, type SilenceItem, type VoiceOutcome } from "@/lib/meeting";
import { AddNoteForm, RehearseForm, WriteMinutesButton } from "./Forms";
import { Icon } from "./Icon";
import styles from "./MeetingPanels.module.css";

type Action = (prev: ActionState, form: FormData) => Promise<ActionState>;

/* Summary: the backend's minutes, as Markdown ------------------------------------- */

export function MinutesPanel({
  minutes,
  agent,
  hasTranscript,
  write,
}: {
  minutes: Minutes | null;
  agent: string;
  hasTranscript: boolean;
  write: (prev: ActionState) => Promise<ActionState>;
}) {
  if (!minutes) {
    return (
      <div className={styles.empty}>
        <h3>No minutes yet</h3>
        <p>
          {agent} writes them automatically once Recall finishes the transcript after the call.
          {hasTranscript ? " You can also write them now from what’s been transcribed so far." : " Nothing has been transcribed yet."}
        </p>
        {hasTranscript && <WriteMinutesButton action={write} label="Write minutes now" />}
      </div>
    );
  }
  return (
    <div>
      <div className={styles.minutes}>
        <Markdown>{minutes.content}</Markdown>
      </div>
      <div className={styles.provenance}>
        <p>
          Written by {agent} at {clock(minutes.updated_at)} on {shortDay(minutes.updated_at)}, from the transcript and its answers.
        </p>
        <WriteMinutesButton action={write} label="Rewrite from the latest transcript" />
      </div>
    </div>
  );
}

/* What the delegate said ------------------------------------------------------------ */

const VOICE: Record<VoiceOutcome, string> = {
  played: "Played in the meeting",
  queued: "Waiting to play",
  failed: "Couldn’t play",
  none: "Not spoken aloud",
};

export function AnswersPanel({
  answers,
  silences,
  playbacks,
  agent,
}: {
  answers: AnswerItem[];
  silences: SilenceItem[];
  playbacks: { sequence: number; at: string; outcome: "played" | "failed" }[];
  agent: string;
}) {
  // "Nobody said its name" is the norm, so only the closer calls are listed one by one.
  const routine = new Set(["wake name not detected", "waiting for final caption"]);
  const notable = silences.filter((s) => !routine.has(s.reason));
  const unnamed = silences.length - notable.length;
  return (
    <div className={styles.said}>
      <p className={styles.lede}>
        {answers.length > 0 ? `${agent} answered ${plural(answers.length, "question")}.` : `${agent} hasn’t answered anything yet.`} It speaks
        only when someone says “{agent}” and asks it something, and only from its briefing notes and the conversation.
      </p>

      {answers.length > 0 && (
        <ol className={styles.turns}>
          {answers.map((a) => (
            <li key={a.sequence} id={`turn-${a.sequence}`} className={styles.turn}>
              <span className={`${styles.when} tabular`}>{clock(a.question?.at ?? a.at)}</span>
              <div className={styles.exchange}>
                {a.question && (
                  <div>
                    <p className={styles.asker}>
                      <strong>{a.question.speaker}</strong> asked
                    </p>
                    <blockquote className={`verbatim ${styles.question}`}>{a.question.text}</blockquote>
                  </div>
                )}
                <div className={styles.answer}>
                  <p className={styles.answerHead}>
                    <span className={styles.answerWho}>
                      <span className="lamp" aria-hidden="true" />
                      <strong>{agent}</strong> answered at {clock(a.at, true)}
                    </span>
                    <span className={`${styles.voice} ${styles[`voice_${a.voice}`]}`}>{VOICE[a.voice]}</span>
                  </p>
                  <blockquote className={`verbatim ${styles.answerText}`}>{a.answer}</blockquote>
                  {a.citations.length > 0 && (
                    <div className={styles.sources}>
                      <h4>From its notes</h4>
                      <ul>
                        {a.citations.map((c) => (
                          <li key={c.id}>
                            <Icon name="doc" size={14} />
                            <span>{c.title}</span>
                            <span className={styles.sourceKind}>{c.source}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className={styles.why}>
                    <strong>Why it spoke up.</strong> {reasonText(a.reason, agent)}
                  </p>
                  <a href={`?view=transcript#a-${a.sequence}`} data-view="transcript" className={styles.jump}>
                    See it in the transcript
                  </a>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}

      {playbacks.length > 0 && (
        <section className={styles.block} aria-labelledby="sent-title">
          <h3 id="sent-title">Messages you sent from here</h3>
          <p className={styles.blockNote}>The backend records when these played, not their text.</p>
          <ul className={styles.plain}>
            {playbacks.map((p) => (
              <li key={p.sequence}>
                <span className="tabular">{clock(p.at, true)}</span> {p.outcome === "played" ? "Played in the meeting" : "Couldn’t play"}
              </li>
            ))}
          </ul>
        </section>
      )}

      {silences.length > 0 && (
        <section className={styles.block} aria-labelledby="quiet-title">
          <h3 id="quiet-title">When it stayed quiet</h3>
          <p className={styles.blockNote}>
            {unnamed > 0 && `It stayed quiet through ${plural(unnamed, "line")} because nobody said its name. `}
            {notable.length > 0 ? "These came closer:" : ""}
            {" "}These are logged for lines tried from this dashboard; in live meetings the backend records answers only.
          </p>
          <ol className={styles.quietList}>
            {notable.map((s) => (
              <li key={s.sequence}>
                <span className={`${styles.when} tabular`}>{clock(s.at)}</span>
                <div>
                  <p className={styles.asker}>
                    <strong>{s.speaker}</strong>
                  </p>
                  <blockquote className={`verbatim ${styles.question}`}>“{s.text}”</blockquote>
                  <p className={styles.why}>{reasonText(s.reason, agent)}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

/* Briefing ------------------------------------------------------------------------------ */

export function BriefingPanel({ notes, agent, add }: { notes: ContextNote[]; agent: string; add: Action }) {
  return (
    <div className={styles.briefing}>
      <p className={styles.lede}>
        {agent} answers only from these notes and what’s said in the meeting. If it can’t find something here, it says it doesn’t know.
      </p>
      {notes.length === 0 ? (
        <p className={styles.none}>No notes yet. Add what people are likely to ask about.</p>
      ) : (
        <ol className={styles.notes}>
          {notes.map((n) => (
            <li key={n.id} className={styles.note}>
              <h3>{n.title}</h3>
              <p className={styles.noteMeta}>
                Added at {clock(n.created_at)} on {shortDay(n.created_at)}
                {n.source !== "briefing" && `, from ${n.source}`}
              </p>
              <p className={styles.noteText}>{n.content}</p>
            </li>
          ))}
        </ol>
      )}
      <section className={styles.block} aria-labelledby="add-note">
        <h3 id="add-note">Add a note</h3>
        <AddNoteForm action={add} agent={agent} />
      </section>
    </div>
  );
}

/* Activity --------------------------------------------------------------------------- */

export function ActivityPanel({ items, agent, rehearse }: { items: ActivityItem[]; agent: string; rehearse: Action }) {
  const newestFirst = [...items].reverse();
  return (
    <div className={styles.activity}>
      <div className={styles.columns}>
        <section aria-labelledby="log-title">
          <h3 id="log-title" className={styles.colTitle}>
            What happened, newest first
          </h3>
          {newestFirst.length === 0 ? (
            <p className={styles.none}>Nothing yet.</p>
          ) : (
            <ol className={styles.log}>
              {newestFirst.map((i) => (
                <li key={i.sequence} className={styles[`tone_${i.tone}`]}>
                  <span className={`${styles.when} tabular`}>{clock(i.at, true)}</span>
                  <div>
                    <p className={styles.logTitle}>{i.title}</p>
                    {i.detail && <p className={styles.logDetail}>{i.detail}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </section>
        <section aria-labelledby="try-title" className={styles.try}>
          <h3 id="try-title" className={styles.colTitle}>
            Try it without a call
          </h3>
          <p className={styles.blockNote}>
            Type a line as if someone said it. It goes through the same speaking rules and, with OpenAI set up, gets a real answer. The line is
            added to this meeting’s transcript.
          </p>
          <RehearseForm action={rehearse} agent={agent} />
        </section>
      </div>
    </div>
  );
}
