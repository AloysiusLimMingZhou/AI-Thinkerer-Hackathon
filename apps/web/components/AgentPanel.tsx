import { dueStatus, gateTally, SILENCE_LABELS, speakerName, spokenTurns, utterance } from "@/lib/data";
import { clock, duration, percent, plural, seconds1, shortDay, spelled } from "@/lib/format";
import { AGENT_NAME } from "@/lib/people";
import type { AgentTurn, Meeting, SilenceReason } from "@/lib/types";
import { Icon, SourceIcon } from "./Icon";
import styles from "./AgentPanel.module.css";

function intro(m: Meeting): string {
  const spoken = spokenTurns(m);
  const answered = spoken.filter((t) => t.kind === "answer").length;
  const deferred = spoken.length - answered;
  const posted = m.turns.some((t) => t.kind === "announcement") ? " It also introduced itself in the chat when it joined." : "";
  if (spoken.length === 0) return `${AGENT_NAME} didn’t speak in this meeting. Nobody asked it anything, so it listened and took notes.${posted}`;
  const parts = [answered && `answered ${plural(answered, "question")}`, deferred && `passed ${spelled(deferred)} back to you`].filter(Boolean);
  return `${AGENT_NAME} spoke ${plural(spoken.length, "time")}: it ${parts.join(" and ")}.${posted}`;
}

export function AgentPanel({ meeting: m }: { meeting: Meeting }) {
  const tally = gateTally(m);
  const reasons = Object.entries(tally.reasons) as [SilenceReason, number][];
  const maxReason = Math.max(1, ...reasons.map(([, n]) => n));

  return (
    <div className={styles.panel}>
      <p className={styles.lede}>{intro(m)}</p>

      <ol className={styles.turns}>
        {m.turns.map((t) => (
          <Turn key={t.id} meeting={m} turn={t} />
        ))}
      </ol>

      <section className={styles.quiet} aria-labelledby="quiet-title">
        <h3 id="quiet-title">When it stayed quiet</h3>
        <p className={styles.quietLede}>
          It heard {plural(tally.heard, "turn")} from people and stayed quiet through {tally.quiet === tally.heard ? `all ${tally.quiet}` : tally.quiet} of them.
          {tally.spoke > 0 && " It only spoke when someone said its name and asked it something."}
        </p>

        <ul className={styles.reasons} aria-label="Why it stayed quiet">
          {reasons.map(([reason, n]) => (
            <li key={reason} className={n === 0 ? styles.zero : undefined}>
              <span className={styles.reasonLabel}>{SILENCE_LABELS[reason]}</span>
              <span className={styles.reasonBar}>
                {n > 0 && <span style={{ width: `${(n / maxReason) * 100}%` }} />}
                <span className={`${styles.reasonCount} tabular`}>{n}</span>
              </span>
            </li>
          ))}
        </ul>

        {m.notableSilences.length > 0 && (
          <>
            <h4 className={styles.heldTitle}>Moments it held back</h4>
            <ol className={styles.held}>
              {m.notableSilences.map((s) => {
                const u = utterance(m, s.utteranceId);
                if (!u) return null;
                return (
                  <li key={s.utteranceId}>
                    <span className={`${styles.when} tabular`}>{clock(m.start, u.t)}</span>
                    <div>
                      <p className={styles.heldWho}>{speakerName(u.speaker)}</p>
                      <blockquote className={`verbatim ${styles.heldQuote}`}>“{u.text}”</blockquote>
                      <p className={styles.heldNote}>
                        <Icon name="ring" size={14} />
                        {s.note}
                      </p>
                      <a href={`?view=transcript#${u.id}`} data-view="transcript" className={styles.jump}>
                        See it in the transcript
                      </a>
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </section>
    </div>
  );
}

function Turn({ meeting: m, turn: t }: { meeting: Meeting; turn: AgentTurn }) {
  const own = utterance(m, t.utteranceId);
  if (!own) return null;
  const q = utterance(m, t.trigger);

  if (t.kind === "announcement") {
    return (
      <li id={`turn-${t.id}`} className={`${styles.turn} ${styles.announce}`}>
        <span className={`${styles.when} tabular`}>{clock(m.start, own.t)}</span>
        <div>
          <p className={styles.kind}>
            <Icon name="chat" size={16} /> Posted in the meeting chat when it joined
          </p>
          <blockquote className={`verbatim ${styles.chatText}`}>{own.text}</blockquote>
        </div>
      </li>
    );
  }

  const deferred = t.kind === "defer";
  const due = t.flag?.due ? dueStatus(t.flag.due) : undefined;

  return (
    <li id={`turn-${t.id}`} className={styles.turn}>
      <span className={`${styles.when} tabular`}>{clock(m.start, (q ?? own).t)}</span>
      <div className={styles.exchange}>
        {q && (
          <div className={styles.question}>
            <p className={styles.asker}>
              <strong>{speakerName(q.speaker)}</strong> asked
            </p>
            <blockquote className={`verbatim ${styles.questionText}`}>{q.text}</blockquote>
          </div>
        )}

        <div className={styles.answer}>
          <p className={styles.answerHead}>
            <span className={styles.answerWho}>
              <span className="lamp" aria-hidden="true" />
              <strong>{AGENT_NAME}</strong> {deferred ? "passed it back to you" : "answered"}
            </span>
            {t.latencyMs !== undefined && (
              <span className={styles.timing}>
                First word after {seconds1(t.latencyMs)}, spoke for {duration(own.dur)}
              </span>
            )}
          </p>
          <blockquote className={`verbatim ${styles.answerText}`}>{own.text}</blockquote>

          {deferred && t.flag && (
            <p className={styles.flagged}>
              <Icon name="flag" size={16} />
              <span>
                Added to your list: <span className="highlight">{t.flag.summary}</span>.{due && ` ${due.text}.`}
              </span>
            </p>
          )}

          {t.citations.length > 0 && (
            <div className={styles.sources}>
              <h4>{deferred ? "What it found" : "Where it got this"}</h4>
              <ul>
                {t.citations.map((c) => (
                  <li key={c.text}>
                    <span className={styles.sourceIcon}>
                      <SourceIcon kind={c.kind} />
                    </span>
                    <div>
                      <p className={styles.sourceHead}>
                        <strong>{c.source}</strong>
                        {c.author && (
                          <span>
                            {c.author}
                            {c.ts && `, ${shortDay(c.ts)} at ${clock(c.ts)}`}
                          </span>
                        )}
                      </p>
                      <blockquote className={`verbatim ${styles.sourceText}`}>“{c.text}”</blockquote>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {t.searched && (
            <p className={styles.searched}>
              <strong>Where it looked.</strong> {t.searched}
            </p>
          )}

          {t.gate && (
            <div className={styles.why}>
              <h4>Why it spoke up</h4>
              <ol className={styles.gate}>
                <li>
                  <Icon name="check" size={15} /> Heard its name, “{t.gate.heard}”
                </li>
                <li>
                  <Icon name="check" size={15} /> Recognised a {t.gate.signal.toLowerCase()}
                </li>
                <li>
                  <Icon name="check" size={15} /> Double-checked it was being asked ({percent(t.gate.confirmed)} sure)
                </li>
              </ol>
              {t.confidence !== undefined && (
                <p className={styles.confidence}>
                  {deferred
                    ? `Only ${percent(t.confidence)} confident in any answer, so it deferred instead of guessing.`
                    : `${percent(t.confidence)} confident in the answer.`}
                </p>
              )}
            </div>
          )}

          <a href={`?view=transcript#${own.id}`} data-view="transcript" className={styles.jump}>
            See it in the transcript
          </a>
        </div>
      </div>
    </li>
  );
}
