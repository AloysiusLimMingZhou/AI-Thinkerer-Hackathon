import Link from "next/link";
import { BackendDown } from "@/components/BackendDown";
import { Icon } from "@/components/Icon";
import { LiveRefresh } from "@/components/LiveRefresh";
import { LogSearch } from "@/components/LogSearch";
import { MiniStrip } from "@/components/MiniStrip";
import { Readiness } from "@/components/Readiness";
import { SendForm } from "@/components/SendForm";
import type { BackendEvent, Bot, Health, RecallStatus, Session, TranscriptEntry } from "@/lib/api-types";
import { backend } from "@/lib/backend";
import { clock, dayKey, duration, longDay, plural, shortDay, spelled } from "@/lib/format";
import { answersFrom, botState, DEFAULT_AGENT, inCall, isLive, platformOf, silencesFrom } from "@/lib/meeting";
import { timeline, type Timeline } from "@/lib/score";
import styles from "./home.module.css";

export const dynamic = "force-dynamic";

const LOG_ID = "meeting-log";
const RECENT = 30;

interface Row {
  session: Session;
  bot: Bot | null;
  tl: Timeline | null;
  lines: number;
  answers: number;
}

async function loadRow(session: Session): Promise<Row> {
  const [bot, transcript, events] = await Promise.all([
    backend.bot(session.id).catch(() => null),
    backend.transcript(session.id).catch((): TranscriptEntry[] => []),
    backend.events(session.id).catch((): BackendEvent[] => []),
  ]);
  const answers = answersFrom(events);
  return {
    session,
    bot,
    tl: timeline(transcript, answers, silencesFrom(events)),
    lines: transcript.filter((t) => t.is_final).length,
    answers: answers.length,
  };
}

function groupByDay(rows: Row[]) {
  const groups: { key: string; label: string; rows: Row[] }[] = [];
  for (const r of rows) {
    const key = dayKey(r.session.created_at);
    const last = groups[groups.length - 1];
    if (last?.key === key) last.rows.push(r);
    else groups.push({ key, label: longDay(r.session.created_at), rows: [r] });
  }
  return groups;
}

export default async function HomePage() {
  let sessions: Session[];
  let status: RecallStatus;
  let health: Health | null;
  try {
    [sessions, status, health] = await Promise.all([backend.listSessions(), backend.recallStatus(), backend.health().catch(() => null)]);
  } catch (e) {
    return <BackendDown error={e} />;
  }

  const rows = await Promise.all(sessions.slice(0, RECENT).map(loadRow));
  const live = rows.find((r) => inCall(r.bot) || r.session.status === "active");
  const pending = rows.some((r) => isLive(r.session, r.bot));
  const agent = live?.session.agent_name ?? sessions[0]?.agent_name ?? DEFAULT_AGENT;
  const attended = rows.filter((r) => r.lines > 0).length;
  const answered = rows.reduce((n, r) => n + r.answers, 0);
  const longest = Math.max(60, ...rows.map((r) => r.tl?.span ?? 0));
  const scale = longest <= 600 ? Math.ceil(longest / 60) * 60 : Math.ceil(longest / 600) * 600;
  const tickEvery = scale <= 600 ? Math.max(60, Math.ceil(scale / 5 / 60) * 60) : 600;
  const ticks = Array.from({ length: Math.floor(scale / tickEvery) + 1 }, (_, i) => i * tickEvery);

  return (
    <main className={styles.page}>
      {pending && <LiveRefresh every={5000} />}
      <section className={styles.intro}>
        <h1 className="condensed">
          {live
            ? `${agent} is in ${live.session.title} right now.`
            : attended > 0
              ? `${agent} has sat in on ${spelled(attended)} ${attended === 1 ? "meeting" : "meetings"} for you.`
              : sessions.length > 0
                ? `${agent} hasn’t made it into a meeting yet.`
                : `Send ${agent} to your first meeting.`}
        </h1>
        <p>
          {live ? (
            <>
              <Link href={`/meetings/${live.session.id}`}>Follow along</Link>, have it say something, or ask it to leave.
            </>
          ) : attended > 0 ? (
            `It answered ${plural(answered, "question")} across them, and stayed quiet the rest of the time.`
          ) : (
            `Paste a meeting link and a few notes. ${agent} joins as a guest, transcribes, and answers only when someone says its name and asks.`
          )}
        </p>
      </section>

      <div className={styles.columns}>
        <section className={styles.log} aria-labelledby="log-title">
          <div className={styles.logHead}>
            <h2 id="log-title">Meetings</h2>
            {rows.length > 0 && <LogSearch targetId={LOG_ID} />}
          </div>

          <div className={`sheet ${styles.logSheet}`} id={LOG_ID}>
            {rows.length === 0 ? (
              <p className={styles.empty}>No meetings yet. Use the form to send {agent} to one.</p>
            ) : (
              <>
                <div className={styles.ruler} aria-hidden="true">
                  <span className={styles.rulerLabel}>Drawn to scale</span>
                  <div className={styles.rulerTrack}>
                    {ticks.map((t) => (
                      <span key={t} className={styles.tick} style={{ left: `${(t * 100) / scale}%` }}>
                        {t === ticks[ticks.length - 1] ? duration(t) : t / 60}
                      </span>
                    ))}
                  </div>
                </div>

                {groupByDay(rows).map((g) => (
                  <section key={g.key} data-day className={styles.day} aria-label={g.label}>
                    <h3 className={styles.dayLabel}>{g.label}</h3>
                    <ol>
                      {g.rows.map((r) => (
                        <MeetingRow key={r.session.id} row={r} scale={scale} />
                      ))}
                    </ol>
                  </section>
                ))}

                <p className={styles.empty} data-empty hidden>
                  Nothing matches “<span data-query />”. Try a meeting name or a person.
                </p>
              </>
            )}
          </div>
          {sessions.length > RECENT && <p className={styles.more}>Showing the {RECENT} most recent of {sessions.length} meetings.</p>}
        </section>

        <aside className={styles.side}>
          <section className={`sheet ${styles.sendSheet}`} aria-labelledby="send-title">
            <h2 id="send-title" className={styles.sendTitle}>
              Send {agent} to a meeting
            </h2>
            <SendForm ready={status.configured} />
          </section>
          <Readiness status={status} health={health} />
        </aside>
      </div>
    </main>
  );
}

function MeetingRow({ row, scale }: { row: Row; scale: number }) {
  const { session: s, bot, tl } = row;
  const state = botState(bot, s.agent_name, bot?.join_at ? `${clock(bot.join_at)} on ${shortDay(bot.join_at)}` : undefined);
  const platform = platformOf(s.meeting_url);
  const onAir = inCall(bot);

  return (
    <li className={styles.row} data-search={[s.title, s.owner_name, s.agent_name, platform?.name ?? ""].join(" ").toLowerCase()}>
      <div className={styles.when}>
        <span className={`${styles.time} tabular`}>{clock(s.created_at)}</span>
        {tl && <span className={styles.len}>{duration(tl.span)}</span>}
      </div>
      <div className={styles.what}>
        <h4 className={styles.title}>
          <Link href={`/meetings/${s.id}`} className={styles.rowLink}>
            {s.title}
          </Link>
        </h4>
        <p className={styles.summary}>
          <span className={`${styles.state} ${styles[`tone_${state.tone}`]}`}>
            <span className={onAir ? "lamp" : "lamp lamp-off"} aria-hidden="true" />
            {state.label}
          </span>
          {platform && <span className={styles.platform}>{platform.name}</span>}
        </p>
      </div>
      <div className={styles.trace}>
        {tl ? (
          <MiniStrip
            tl={tl}
            scale={scale}
            label={`${duration(tl.span)} of conversation. ${s.agent_name} answered ${plural(row.answers, "time")}.`}
          />
        ) : (
          <p className={styles.notIn}>
            <Icon name="door" size={16} /> No transcript yet
          </p>
        )}
        {tl && (
          <p className={styles.outcome}>
            <span className={row.answers > 0 ? styles.spoke : styles.quiet}>
              <span className={row.answers > 0 ? "lamp" : "lamp lamp-off"} aria-hidden="true" />
              {row.answers > 0 ? `Answered ${plural(row.answers, "time")}` : "Stayed quiet"}
            </span>
            <span className={styles.quiet}>{plural(row.lines, "line")}</span>
          </p>
        )}
      </div>
    </li>
  );
}
