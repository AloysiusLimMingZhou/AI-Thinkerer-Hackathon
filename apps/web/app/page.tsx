import Link from "next/link";
import { Icon } from "@/components/Icon";
import { LogSearch } from "@/components/LogSearch";
import { MiniStrip } from "@/components/MiniStrip";
import { dueStatus, lengthSeconds, listMeetings, spokenTurns, waitingIn, waitingOnYou, weekSummary } from "@/lib/data";
import { clock, dayKey, duration, durationLong, longDay, plural, shortDay, spelled } from "@/lib/format";
import { AGENT_NAME, person } from "@/lib/people";
import type { Meeting } from "@/lib/types";
import styles from "./home.module.css";

const LOG_ID = "meeting-log";

function groupByDay(meetings: Meeting[]) {
  const groups: { key: string; label: string; meetings: Meeting[] }[] = [];
  for (const m of meetings) {
    const key = dayKey(m.start);
    const last = groups[groups.length - 1];
    if (last?.key === key) last.meetings.push(m);
    else groups.push({ key, label: longDay(m.start), meetings: [m] });
  }
  return groups;
}

/** Ruler length for the strips: the longest meeting, rounded up to 10 minutes. */
function stripScale(meetings: Meeting[]): number {
  const longest = Math.max(...meetings.filter((m) => m.status === "attended").map(lengthSeconds));
  return Math.ceil(longest / 600) * 600;
}

function firstSentence(text: string): string {
  const m = text.match(/^.*?[.!?](\s|$)/);
  return (m ? m[0] : text).trim();
}

function searchText(m: Meeting): string {
  return [m.title, ...m.attendees.map((id) => person(id).name), m.minutes?.tldr ?? "", ...(m.minutes?.topics.map((t) => t.title) ?? [])]
    .join(" ")
    .toLowerCase();
}

export default function HomePage() {
  const meetings = listMeetings();
  const week = weekSummary();
  const waiting = waitingOnYou();
  const scale = stripScale(meetings);
  const ticks = Array.from({ length: scale / 600 + 1 }, (_, i) => i * 10);

  return (
    <main className={styles.page}>
      <section className={styles.intro}>
        <h1 className="condensed">
          {AGENT_NAME} went to {spelled(week.sent)} meetings for you this week.
        </h1>
        <p>
          It got into {spelled(week.attended)} of them, {durationLong(week.seconds)} in all. It spoke {plural(week.spoke, "time")} and passed{" "}
          {spelled(week.deferred)} questions back to you.
        </p>
      </section>

      <div className={styles.columns}>
        <section className={styles.log} aria-labelledby="log-title">
          <div className={styles.logHead}>
            <h2 id="log-title">Past meetings</h2>
            <LogSearch targetId={LOG_ID} />
          </div>

          <div className={`sheet ${styles.logSheet}`} id={LOG_ID}>
            <div className={styles.ruler} aria-hidden="true">
              <span className={styles.rulerLabel}>Drawn to scale</span>
              <div className={styles.rulerTrack}>
                {ticks.map((t) => (
                  <span key={t} className={styles.tick} style={{ left: `${(t * 60 * 100) / scale}%` }}>
                    {t === ticks[ticks.length - 1] ? `${t} min` : t}
                  </span>
                ))}
              </div>
            </div>

            {groupByDay(meetings).map((g) => (
              <section key={g.key} data-day className={styles.day} aria-label={g.label}>
                <h3 className={styles.dayLabel}>{g.label}</h3>
                <ol>
                  {g.meetings.map((m) => (
                    <MeetingRow key={m.id} meeting={m} scale={scale} />
                  ))}
                </ol>
              </section>
            ))}

            <p className={styles.empty} data-empty hidden>
              Nothing matches “<span data-query />”. Try a person’s name or a topic like “refunds”.
            </p>
          </div>
        </section>

        <aside className={styles.waiting} aria-labelledby="waiting-title">
          <div className={styles.waitingHead}>
            <h2 id="waiting-title">
              <Icon name="flag" size={18} /> Waiting on you
            </h2>
            <span className={styles.count} aria-label={`${waiting.length} items`}>
              {waiting.length}
            </span>
          </div>
          <p className={styles.waitingIntro}>Questions {AGENT_NAME} passed back to you instead of guessing. Someone is waiting on each one.</p>

          {waiting.length === 0 ? (
            <p className={styles.waitingEmpty}>You’re all caught up. When {AGENT_NAME} can’t answer something for you, it lands here.</p>
          ) : (
            <ol className={styles.waitList}>
              {waiting.map((w) => {
                const status = w.due ? dueStatus(w.due) : undefined;
                return (
                  <li key={w.turn.id} className={styles.waitItem}>
                    {status && <p className={status.overdue ? `${styles.due} ${styles.overdue}` : styles.due}>{status.text}</p>}
                    <h3>
                      <span className="highlight">{w.summary}</span>
                    </h3>
                    <blockquote className={`verbatim ${styles.waitQuote}`}>“{w.question.text}”</blockquote>
                    <p className={styles.waitMeta}>
                      {w.askedBy.name} asked in{" "}
                      <Link href={`/meetings/${w.meeting.id}?view=said#turn-${w.turn.id}`}>{w.meeting.title}</Link>, {shortDay(w.meeting.start)} at{" "}
                      {clock(w.meeting.start, w.question.t)}.
                    </p>
                  </li>
                );
              })}
            </ol>
          )}
        </aside>
      </div>
    </main>
  );
}

function MeetingRow({ meeting: m, scale }: { meeting: Meeting; scale: number }) {
  const attended = m.status === "attended";
  const spoke = spokenTurns(m).length;
  const forYou = waitingIn(m).length;

  return (
    <li className={styles.row} data-search={searchText(m)}>
      <div className={styles.when}>
        <span className={`${styles.time} tabular`}>{clock(m.start)}</span>
        <span className={styles.len}>{attended ? duration(lengthSeconds(m)) : "No notes"}</span>
      </div>
      <div className={styles.what}>
        <h4 className={styles.title}>
          <Link href={`/meetings/${m.id}`} className={styles.rowLink}>
            {m.title}
          </Link>
        </h4>
        <p className={styles.summary}>
          {m.minutes ? firstSentence(m.minutes.tldr) : `Nobody let ${AGENT_NAME} in from the waiting room, so there are no notes.`}
        </p>
      </div>
      <div className={styles.trace}>
        {attended ? (
          <MiniStrip meeting={m} scale={scale} />
        ) : (
          <p className={styles.notIn}>
            <Icon name="door" size={16} /> Waited {duration(m.lobbyWait ?? 0)}, then left
          </p>
        )}
        {attended && (
          <p className={styles.outcome}>
            {spoke > 0 ? (
              <span className={styles.spoke}>
                <span className="lamp" aria-hidden="true" /> Spoke {plural(spoke, "time")}
              </span>
            ) : (
              <span className={styles.quiet}>
                <span className="lamp lamp-off" aria-hidden="true" /> Stayed quiet
              </span>
            )}
            {forYou > 0 && (
              <span className={styles.forYou}>
                <Icon name="flag" size={14} /> {forYou} for you
              </span>
            )}
          </p>
        )}
      </div>
    </li>
  );
}
