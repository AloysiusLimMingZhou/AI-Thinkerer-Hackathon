import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { addNote, launchBot, leaveMeeting, sayInMeeting, tryLine, writeMinutes } from "@/app/actions";
import { BackendDown } from "@/components/BackendDown";
import { BotPanel } from "@/components/BotPanel";
import { CopyButton } from "@/components/CopyButton";
import { DownloadMenu, type DownloadOption } from "@/components/DownloadMenu";
import { Icon } from "@/components/Icon";
import { LiveRefresh } from "@/components/LiveRefresh";
import { ActivityPanel, AnswersPanel, BriefingPanel, MinutesPanel } from "@/components/MeetingPanels";
import { MeetingRecord } from "@/components/MeetingRecord";
import { MeetingScore } from "@/components/MeetingScore";
import { TranscriptPanel, type TranscriptLine } from "@/components/TranscriptPanel";
import type { BackendEvent, Bot, Minutes, Session, TranscriptEntry } from "@/lib/api-types";
import { backend } from "@/lib/backend";
import { exportFilename, TRANSCRIPT_FORMATS, type TranscriptFormat } from "@/lib/export";
import { ago, clock, longDay, shortDay } from "@/lib/format";
import {
  activityFrom,
  answersFrom,
  botState,
  briefingFrom,
  inCall,
  isFinal,
  isLive,
  manualPlaybacks,
  mergedTranscript,
  platformOf,
  reasonText,
  silencesFrom,
} from "@/lib/meeting";
import { scoreData, timeline } from "@/lib/score";
import { isView } from "@/lib/views";
import styles from "./meeting.module.css";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }>; searchParams: Promise<{ view?: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const session = await backend.getSession(id).catch(() => null);
  return { title: session ? `${session.title}, ${shortDay(session.created_at)}` : "Meeting" };
}

interface Loaded {
  session: Session;
  bot: Bot | null;
  transcript: TranscriptEntry[];
  events: BackendEvent[];
  minutes: Minutes | null;
}

async function load(id: string): Promise<Loaded | null> {
  const session = await backend.getSession(id);
  if (!session) return null;
  const [bot, transcript, events, minutes] = await Promise.all([backend.bot(id), backend.transcript(id), backend.events(id), backend.minutes(id)]);
  return { session, bot, transcript, events, minutes };
}

export default async function MeetingPage({ params, searchParams }: Params) {
  const { id } = await params;
  const { view } = await searchParams;

  let data: Loaded | null;
  try {
    data = await load(id);
  } catch (e) {
    return <BackendDown error={e} />;
  }
  if (!data) notFound();

  const { session, bot, transcript, events, minutes } = data;
  const agent = session.agent_name;
  const answers = answersFrom(events);
  const silences = silencesFrom(events);
  const notes = briefingFrom(events);
  const lines = mergedTranscript(transcript, answers, agent);
  const tl = timeline(transcript, answers, silences);
  const live = isLive(session, bot);
  const platform = platformOf(session.meeting_url);
  const when = bot?.join_at ? `${clock(bot.join_at)} on ${shortDay(bot.join_at)}` : undefined;
  const state = botState(bot, agent, when);
  const stateLabel = (code: string) => botState(bot ? { ...bot, state: code } : null, agent).label;
  const finishedTranscript = events.some((e) => e.type === "transcript.saved");

  // Mark, in the transcript, which lines got an answer and which named it without asking.
  const questionIds = new Set(answers.map((a) => a.question?.id).filter(Boolean).map((qid) => `t-${qid}`));
  const heldBack = new Map(
    silences.filter((s) => s.reason === "addressed, but no response was requested" && s.utteranceId).map((s) => [`t-${s.utteranceId}`, reasonText(s.reason, agent)]),
  );
  const transcriptLines: TranscriptLine[] = lines.map((l) => ({
    id: l.id,
    clock: clock(l.at, true),
    speaker: l.speaker,
    agent: l.agent,
    chat: false,
    text: l.text,
    role: questionIds.has(l.id) ? "question" : heldBack.has(l.id) ? "heldBack" : undefined,
    note: heldBack.get(l.id),
  }));

  const downloads: DownloadOption[] = (Object.keys(TRANSCRIPT_FORMATS) as TranscriptFormat[]).map((f) => ({
    label: TRANSCRIPT_FORMATS[f].label,
    hint: `.${TRANSCRIPT_FORMATS[f].ext}`,
    href: `/meetings/${session.id}/transcript?format=${f}`,
    filename: exportFilename(session, "transcript", TRANSCRIPT_FORMATS[f].ext),
  }));
  const minutesDownload: DownloadOption | undefined = minutes
    ? { label: "Minutes", hint: ".md", href: `/meetings/${session.id}/minutes`, filename: exportFilename(session, "minutes", "md") }
    : undefined;

  const sourceNote = finishedTranscript
    ? `Recall’s final transcript, saved after the call. ${agent}’s answers are merged in from its answer log.`
    : bot
      ? `Live captions from Recall as they arrive. After the call they’re replaced by Recall’s final transcript. ${agent}’s answers are merged in.`
      : `Lines tried from this dashboard. ${agent}’s answers are merged in.`;

  const initialView = isView(view) ? view : minutes ? "summary" : lines.length > 0 ? "said" : "briefing";

  return (
    <main className={styles.page}>
      {live && <LiveRefresh every={3000} />}
      <nav className={styles.crumbs} aria-label="Meetings">
        <Link href="/" className={styles.back}>
          <Icon name="chevronLeft" size={16} /> All meetings
        </Link>
        {live && <span className={styles.liveTag}>Updating live</span>}
      </nav>

      <header className={styles.header}>
        <div className={styles.heading}>
          <h1 className="condensed">{session.title}</h1>
          <p className={styles.meta}>
            Created {longDay(session.created_at)} at {clock(session.created_at)}.{" "}
            {platform && session.meeting_url && (
              <>
                <a href={session.meeting_url} target="_blank" rel="noreferrer">
                  {platform.name} link
                </a>
                .{" "}
              </>
            )}
            {agent} is attending for {session.owner_name}.
          </p>
        </div>
        <div className={styles.actions}>
          {minutes && <CopyButton text={minutes.content} label="Copy minutes" done="Minutes copied" />}
          {lines.length > 0 && <DownloadMenu options={downloads} extra={minutesDownload} />}
        </div>
      </header>

      <div className={styles.layout}>
        <div className={`sheet ${styles.record}`}>
          <BotPanel
            agent={agent}
            owner={session.owner_name}
            label={state.label}
            detail={state.detail}
            tone={state.tone}
            stateCode={bot?.state}
            since={bot?.last_status_at ? ago(bot.last_status_at) : undefined}
            hasBot={!!bot}
            canLeave={!!bot && !isFinal(bot)}
            canSay={inCall(bot)}
            launch={launchBot.bind(null, session.id)}
            leave={leaveMeeting.bind(null, session.id)}
            say={sayInMeeting.bind(null, session.id)}
          />
          <MeetingRecord
            initialView={initialView}
            labels={{
              summary: { label: "Summary" },
              said: { label: `What ${agent} said`, count: answers.length },
              transcript: { label: "Transcript", count: lines.length },
              briefing: { label: "Briefing", count: notes.length },
              activity: { label: "Activity" },
            }}
            score={tl ? <MeetingScore key="score" data={scoreData(tl, agent)} /> : null}
            panels={{
              summary: <MinutesPanel key="summary" minutes={minutes} agent={agent} hasTranscript={transcript.length > 0} write={writeMinutes.bind(null, session.id)} />,
              said: <AnswersPanel key="said" answers={answers} silences={silences} playbacks={manualPlaybacks(events)} agent={agent} />,
              transcript: (
                <TranscriptPanel
                  key="transcript"
                  lines={transcriptLines}
                  source={sourceNote}
                  agentName={agent}
                  download={lines.length > 0 ? <DownloadMenu options={downloads} variant="quiet" /> : null}
                />
              ),
              briefing: <BriefingPanel key="briefing" notes={notes} agent={agent} add={addNote.bind(null, session.id)} />,
              activity: <ActivityPanel key="activity" items={activityFrom(events, agent, stateLabel)} agent={agent} rehearse={tryLine.bind(null, session.id)} />,
            }}
          />
        </div>

        <aside className={styles.aside}>
          <section aria-labelledby="delegate-title">
            <h2 id="delegate-title">The delegate</h2>
            <dl className={styles.facts}>
              <div>
                <dt>Joins as</dt>
                <dd>{agent} (AI delegate)</dd>
              </div>
              <div>
                <dt>Attending for</dt>
                <dd>{session.owner_name}</dd>
              </div>
              <div>
                <dt>Wakes when someone says</dt>
                <dd className="verbatim">“{agent}, …?”</dd>
              </div>
            </dl>
          </section>

          {session.meeting_url && (
            <section aria-labelledby="link-title">
              <h2 id="link-title">Meeting link</h2>
              <p className={styles.link}>
                <a href={session.meeting_url} target="_blank" rel="noreferrer">
                  {session.meeting_url}
                </a>
              </p>
            </section>
          )}

          {bot && (
            <section aria-labelledby="bot-title">
              <h2 id="bot-title">Recall bot</h2>
              <dl className={styles.facts}>
                <div>
                  <dt>State</dt>
                  <dd className="verbatim">{bot.state}</dd>
                </div>
                {bot.join_at && (
                  <div>
                    <dt>Join time</dt>
                    <dd>
                      {clock(bot.join_at)} on {shortDay(bot.join_at)}
                    </dd>
                  </div>
                )}
                {bot.last_status_at && (
                  <div>
                    <dt>Last update</dt>
                    <dd>{ago(bot.last_status_at)}</dd>
                  </div>
                )}
                {bot.bot_id && (
                  <div>
                    <dt>Bot ID</dt>
                    <dd className={`verbatim ${styles.id}`}>{bot.bot_id}</dd>
                  </div>
                )}
              </dl>
              {bot.error && <p className={styles.error}>{bot.error}</p>}
            </section>
          )}

          <p className={styles.asideNote}>
            A meeting supports one launch. To send {agent} again, even to the same link, <Link href="/">start a new meeting</Link>.
          </p>
        </aside>
      </div>
    </main>
  );
}
