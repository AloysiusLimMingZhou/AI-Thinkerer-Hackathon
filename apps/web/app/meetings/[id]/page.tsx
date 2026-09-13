import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AgentPanel } from "@/components/AgentPanel";
import { CopyButton } from "@/components/CopyButton";
import { DownloadMenu, type DownloadOption } from "@/components/DownloadMenu";
import { Icon, SourceIcon } from "@/components/Icon";
import { MeetingRecord } from "@/components/MeetingRecord";
import { MeetingScore, type ScoreData } from "@/components/MeetingScore";
import { SummaryPanel } from "@/components/SummaryPanel";
import { TranscriptPanel, type TranscriptLine } from "@/components/TranscriptPanel";
import { gateTally, getMeeting, lengthSeconds, listMeetings, neighbours, onAirSeconds, speakerName, speakers, spokenTurns, utterance } from "@/lib/data";
import { exportFilename, minutesMarkdown, TRANSCRIPT_FORMATS, type TranscriptFormat } from "@/lib/export";
import { clock, duration, durationLong, longDay, plural, shortDay } from "@/lib/format";
import { AGENT_NAME, initials, person, shortName } from "@/lib/people";
import { AGENT, type Meeting } from "@/lib/types";
import { isView } from "@/lib/views";
import styles from "./meeting.module.css";

type Params = { params: Promise<{ id: string }>; searchParams: Promise<{ view?: string }> };

export function generateStaticParams() {
  return listMeetings().map((m) => ({ id: m.id }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const m = getMeeting(id);
  return { title: m ? `${m.title}, ${shortDay(m.start)}` : "Meeting not found" };
}

const SOURCE_NOTES = {
  scribe: "Transcribed from the recording by ElevenLabs Scribe. Speaker names are matched to Meet’s live captions.",
  captions: "From Meet’s live captions. The recording is still being transcribed, so some words may change.",
  none: "",
} as const;

function tickStep(length: number): number {
  if (length <= 6 * 60) return 60;
  if (length <= 16 * 60) return 120;
  if (length <= 40 * 60) return 300;
  return 600;
}

function scoreData(m: Meeting): ScoreData {
  const len = lengthSeconds(m);
  const step = tickStep(len);
  const ticks = Array.from({ length: Math.floor(len / step) + 1 }, (_, i) => ({ t: i * step, label: clock(m.start, i * step) }));
  const turnsByUtterance = new Map(m.turns.map((t) => [t.utteranceId, t]));
  const tally = gateTally(m);
  const spoken = spokenTurns(m);

  const onAir = onAirSeconds(m);
  const onAirText = onAir < 60 ? `${Math.round(onAir)} seconds` : durationLong(onAir);
  const summary =
    spoken.length > 0
      ? `${AGENT_NAME} spoke ${plural(spoken.length, "time")}, ${onAirText} in all, and stayed quiet through the other ${tally.quiet} turns.`
      : `${AGENT_NAME} stayed quiet through all ${tally.heard} turns. Nobody asked it anything.`;

  return {
    start: m.start,
    length: len,
    ticks,
    tickStep: step,
    lanes: speakers(m).map((s) => ({ id: s.person.id, name: s.person.name, short: shortName(s.person), talk: duration(s.seconds) })),
    voices: m.utterances
      .filter((u) => u.speaker !== AGENT && u.channel === "voice")
      .map((u) => ({ id: u.id, lane: u.speaker, t: u.t, dur: u.dur, clock: clock(m.start, u.t), text: u.text })),
    spoke: m.utterances
      .filter((u) => u.speaker === AGENT && u.channel === "voice")
      .map((u) => {
        const turn = turnsByUtterance.get(u.id);
        const q = utterance(m, turn?.trigger);
        const asker = q ? person(q.speaker) : undefined;
        const heading = !asker
          ? `${AGENT_NAME} spoke`
          : turn?.kind === "defer"
            ? `${AGENT_NAME} passed ${shortName(asker)}’s question to you`
            : `${AGENT_NAME} answered ${asker.name}`;
        return { id: u.id, turnId: turn?.id ?? "", t: u.t, dur: u.dur, clock: clock(m.start, u.t), text: u.text, heading };
      }),
    heldBack: m.notableSilences.flatMap((s) => {
      const u = utterance(m, s.utteranceId);
      return u ? [{ id: u.id, t: u.t, clock: clock(m.start, u.t), text: u.text, heading: `${speakerName(u.speaker)}. ${AGENT_NAME} held back`, note: s.note }] : [];
    }),
    chat: m.utterances
      .filter((u) => u.speaker === AGENT && u.channel === "chat")
      .map((u) => ({ id: u.id, turnId: turnsByUtterance.get(u.id)?.id ?? "", t: u.t, clock: clock(m.start, u.t), text: u.text })),
    agentName: AGENT_NAME,
    summary,
  };
}

function transcriptLines(m: Meeting): TranscriptLine[] {
  const triggers = new Set(m.turns.map((t) => t.trigger).filter(Boolean));
  const held = new Map(m.notableSilences.map((s) => [s.utteranceId, s.note]));
  return m.utterances.map((u) => ({
    id: u.id,
    clock: clock(m.start, u.t, true),
    speaker: speakerName(u.speaker),
    agent: u.speaker === AGENT,
    chat: u.channel === "chat",
    text: u.text,
    role: triggers.has(u.id) ? "question" : held.has(u.id) ? "heldBack" : undefined,
    note: held.get(u.id),
  }));
}

function downloads(m: Meeting): { options: DownloadOption[]; minutes: DownloadOption } {
  const options = (Object.keys(TRANSCRIPT_FORMATS) as TranscriptFormat[]).map((f) => ({
    label: TRANSCRIPT_FORMATS[f].label,
    hint: `.${TRANSCRIPT_FORMATS[f].ext}`,
    href: `/meetings/${m.id}/transcript?format=${f}`,
    filename: exportFilename(m, "transcript", TRANSCRIPT_FORMATS[f].ext),
  }));
  return {
    options,
    minutes: { label: "Minutes", hint: ".md", href: `/meetings/${m.id}/minutes`, filename: exportFilename(m, "minutes", "md") },
  };
}

export default async function MeetingPage({ params, searchParams }: Params) {
  const { id } = await params;
  const { view } = await searchParams;
  const m = getMeeting(id);
  if (!m) notFound();

  const { earlier, later } = neighbours(m.id);
  const host = person(m.host);
  const others = m.attendees.length - 1;
  const attended = m.status === "attended";
  const dl = downloads(m);

  return (
    <main className={styles.page}>
      <nav className={styles.crumbs} aria-label="Meetings">
        <Link href="/" className={styles.back}>
          <Icon name="chevronLeft" size={16} /> All meetings
        </Link>
        <div className={styles.step}>
          {earlier ? (
            <Link href={`/meetings/${earlier.id}`} title={earlier.title}>
              <Icon name="chevronLeft" size={16} /> Earlier
            </Link>
          ) : (
            <span aria-disabled="true">
              <Icon name="chevronLeft" size={16} /> Earlier
            </span>
          )}
          {later ? (
            <Link href={`/meetings/${later.id}`} title={later.title}>
              Later <Icon name="chevronRight" size={16} />
            </Link>
          ) : (
            <span aria-disabled="true">
              Later <Icon name="chevronRight" size={16} />
            </span>
          )}
        </div>
      </nav>

      <header className={styles.header}>
        <div className={styles.heading}>
          <h1 className="condensed">{m.title}</h1>
          <p className={styles.meta}>
            {longDay(m.start)}, {attended ? `${clock(m.start)}–${clock(m.end)}` : `scheduled for ${clock(m.start)}`} on {m.platform}. Hosted by {host.name}
            {others > 0 && `, with ${m.audienceSize ? `${m.audienceSize - 1} others` : plural(others, "other")}`}.
          </p>
        </div>
        {attended && (
          <div className={styles.actions}>
            <CopyButton text={minutesMarkdown(m)} label="Copy minutes" done="Minutes copied" />
            <DownloadMenu options={dl.options} extra={dl.minutes} />
          </div>
        )}
      </header>

      <div className={styles.layout}>
        <div className={`sheet ${styles.record}`}>
          {attended ? (
            <MeetingRecord
              initialView={isView(view) ? view : "summary"}
              labels={{
                summary: { label: "Summary" },
                said: { label: `What ${AGENT_NAME} said`, count: spokenTurns(m).length },
                transcript: { label: "Transcript" },
              }}
              score={<MeetingScore key="score" data={scoreData(m)} />}
              panels={{
                summary: <SummaryPanel key="summary" meeting={m} />,
                said: <AgentPanel key="said" meeting={m} />,
                transcript: (
                  <TranscriptPanel
                    key="transcript"
                    lines={transcriptLines(m)}
                    source={SOURCE_NOTES[m.transcriptSource]}
                    agentName={AGENT_NAME}
                    download={<DownloadMenu key="download" options={dl.options} variant="quiet" />}
                  />
                ),
              }}
            />
          ) : (
            <NotAdmitted meeting={m} />
          )}
        </div>

        <aside className={styles.aside}>
          {attended && m.agentJoinedAt !== undefined && m.agentLeftAt !== undefined && (
            <section aria-labelledby="visit-title">
              <h2 id="visit-title">{AGENT_NAME}’s visit</h2>
              <dl className={styles.visit}>
                <div>
                  <dt>Joined</dt>
                  <dd className="tabular">{clock(m.start, m.agentJoinedAt)}</dd>
                </div>
                <div>
                  <dt>Left</dt>
                  <dd className="tabular">{clock(m.start, m.agentLeftAt)}</dd>
                </div>
                <div>
                  <dt>On air</dt>
                  <dd>{onAirSeconds(m) > 0 ? duration(onAirSeconds(m)) : "Never"}</dd>
                </div>
              </dl>
            </section>
          )}

          <section aria-labelledby="people-title">
            <h2 id="people-title">{attended ? "People" : "On the invite"}</h2>
            <ul className={styles.people}>
              {m.attendees.map((pid) => {
                const p = person(pid);
                return (
                  <li key={pid}>
                    <span className={styles.avatar} aria-hidden="true">
                      {initials(p.name)}
                    </span>
                    <span className={styles.personText}>
                      <span className={styles.personName}>
                        {p.name}
                        {pid === m.host && <span className={styles.tag}>Host</span>}
                      </span>
                      <span className={styles.role}>
                        {p.role}
                        {p.org && `, ${p.org}`}
                      </span>
                    </span>
                  </li>
                );
              })}
              {m.audienceSize && m.audienceSize > m.attendees.length && (
                <li className={styles.more}>and {m.audienceSize - m.attendees.length} more listening</li>
              )}
            </ul>
          </section>

          <section aria-labelledby="context-title">
            <h2 id="context-title">What it read beforehand</h2>
            <p className={styles.asideNote}>{AGENT_NAME} answers from these, and says when it can’t.</p>
            <ul className={styles.context}>
              {m.context.map((c) => (
                <li key={c.label}>
                  <span className={styles.contextIcon}>
                    <SourceIcon kind={c.kind} size={15} />
                  </span>
                  <span>
                    <span className={styles.contextLabel}>{c.label}</span>
                    <span className={styles.contextDetail}>{c.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </main>
  );
}

function NotAdmitted({ meeting: m }: { meeting: Meeting }) {
  const host = person(m.host);
  return (
    <div className={styles.notIn}>
      <span className={styles.notInIcon}>
        <Icon name="door" size={28} />
      </span>
      <h2>{AGENT_NAME} didn’t get in</h2>
      <p>
        It asked to join at {clock(m.start)} and waited {durationLong(m.lobbyWait ?? 0)} in the waiting room, but nobody admitted it. It left at {clock(m.end)}, so there’s no
        recording, transcript or minutes from this meeting.
      </p>
      <p>
        Google Meet asks the host to let guests in. If you need to know what happened, ask {host.name} or {m.attendees.length > 1 ? "another attendee" : "the host"} for their
        notes.
      </p>
    </div>
  );
}
