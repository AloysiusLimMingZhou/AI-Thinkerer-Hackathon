import { dueStatus, utterance, waitingIn } from "@/lib/data";
import { clock, duration, shortDay } from "@/lib/format";
import { AGENT_NAME, OWNER, initials, person } from "@/lib/people";
import type { Meeting } from "@/lib/types";
import { Icon } from "./Icon";
import styles from "./SummaryPanel.module.css";

/** A time link that jumps to the line in the transcript tab. */
function At({ meeting, id }: { meeting: Meeting; id?: string }) {
  const u = utterance(meeting, id);
  if (!u) return null;
  const t = clock(meeting.start, u.t);
  return (
    <a href={`?view=transcript#${u.id}`} data-view="transcript" className={styles.at} aria-label={`At ${t} in the transcript`}>
      {t}
    </a>
  );
}

export function SummaryPanel({ meeting: m }: { meeting: Meeting }) {
  const mins = m.minutes;
  if (!mins) return null;
  const waiting = waitingIn(m);

  return (
    <div className={styles.summary}>
      <p className={styles.tldr}>{mins.tldr}</p>

      {waiting.length > 0 && (
        <section className={styles.waiting} aria-labelledby="summary-waiting">
          <h3 id="summary-waiting" className={styles.waitingTitle}>
            <Icon name="flag" size={17} /> Waiting on you
          </h3>
          <ul>
            {waiting.map((w) => {
              const due = w.due ? dueStatus(w.due) : undefined;
              return (
                <li key={w.turn.id} className={styles.waitItem}>
                  <p className={styles.waitSummary}>
                    <span className="highlight">{w.summary}</span>
                  </p>
                  <blockquote className={`verbatim ${styles.waitQuote}`}>“{w.question.text}”</blockquote>
                  <p className={styles.waitMeta}>
                    {w.askedBy.name} asked at <At meeting={m} id={w.question.id} />.
                    {due && <span className={due.overdue ? styles.overdue : undefined}> {due.text}.</span>}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {mins.decisions.length > 0 ? (
        <section className={styles.section} aria-labelledby="summary-decisions">
          <h3 id="summary-decisions">Decisions</h3>
          <ul className={styles.decisions}>
            {mins.decisions.map((d) => (
              <li key={d.text}>
                <span>{d.text}</span>
                <At meeting={m} id={d.source} />
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <section className={styles.section}>
          <h3>Decisions</h3>
          <p className={styles.none}>No decisions were made. This was an update meeting.</p>
        </section>
      )}

      {mins.actions.length > 0 && (
        <section className={styles.section} aria-labelledby="summary-actions">
          <h3 id="summary-actions">Action items</h3>
          <table className={styles.actions}>
            <thead className="sr-only">
              <tr>
                <th scope="col">Owner</th>
                <th scope="col">Task</th>
                <th scope="col">Due</th>
                <th scope="col">When it came up</th>
              </tr>
            </thead>
            <tbody>
              {mins.actions.map((a) => {
                const you = a.owner === "you";
                const name = you ? "You" : person(a.owner).name;
                return (
                  <tr key={a.task} className={you ? styles.yours : undefined}>
                    <td className={styles.owner}>
                      <span className={styles.avatar} aria-hidden="true">
                        {you ? OWNER.initials : initials(name)}
                      </span>
                      {name}
                    </td>
                    <td className={styles.task}>{a.task}</td>
                    <td className={`${styles.due} tabular`}>{a.due ? shortDay(a.due) : <span className={styles.noDue}>No date</span>}</td>
                    <td className={styles.src}>
                      <At meeting={m} id={a.source} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {mins.openQuestions.length > 0 && (
        <section className={styles.section} aria-labelledby="summary-open">
          <h3 id="summary-open">Open questions</h3>
          <ul className={styles.open}>
            {mins.openQuestions.map((q) => (
              <li key={q.text}>
                <p>
                  <span>{q.text}</span> <At meeting={m} id={q.source} />
                </p>
                {(q.askedBy || q.note) && (
                  <p className={styles.openNote}>
                    {q.askedBy && `Raised by ${person(q.askedBy).name}. `}
                    {q.note}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {mins.topics.length > 0 && (
        <section className={styles.section} aria-labelledby="summary-topics">
          <h3 id="summary-topics">Discussion</h3>
          <div className={styles.topics}>
            {mins.topics.map((t) => (
              <div key={t.title} className={styles.topic}>
                <h4>{t.title}</h4>
                <ul>
                  {t.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      <p className={styles.provenance}>
        {AGENT_NAME} wrote these minutes {duration(mins.readyAfter)} after the meeting ended, from the transcript. Times link to the moment in the
        transcript.
      </p>
    </div>
  );
}
