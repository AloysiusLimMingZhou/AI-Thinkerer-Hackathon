"use client";

import { useRef, useState, type CSSProperties, type FocusEvent, type PointerEvent } from "react";
import { useGoTo } from "./MeetingRecord";
import styles from "./MeetingScore.module.css";

export interface ScoreData {
  /** ISO start; utterance times are offsets from it. */
  start: string;
  length: number;
  /** Clock labels for each axis tick, precomputed on the server. */
  ticks: { t: number; label: string }[];
  tickStep: number;
  lanes: { id: string; name: string; short: string; talk: string }[];
  voices: { id: string; lane: string; t: number; dur: number; clock: string; text: string }[];
  spoke: { id: string; turnId: string; t: number; dur: number; clock: string; text: string; heading: string }[];
  heldBack: { id: string; t: number; clock: string; text: string; heading: string; note: string }[];
  chat: { id: string; turnId: string; t: number; clock: string; text: string }[];
  agentName: string;
  /** One sentence the chart supports, e.g. "Alloy answered 4 times…". */
  summary: string;
  /** Small print about how the marks were drawn. */
  note?: string;
}

interface Tip {
  x: number;
  y: number;
  clock: string;
  heading: string;
  text: string;
  note?: string;
  agent?: boolean;
}

const pct = (x: number) => `${(x * 100).toFixed(3)}%`;

/**
 * The meeting as a score: one lane per person, Aloy-bot's lane underneath.
 * Grey is people talking; red is the few moments Aloy-bot did. Emphasis form:
 * one accent, everything else de-emphasised. The transcript is its table view.
 */
export function MeetingScore({ data }: { data: ScoreData }) {
  const goTo = useGoTo();
  const figRef = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const len = data.length;

  const place = (el: HTMLElement, t: Omit<Tip, "x" | "y">) => {
    const fig = figRef.current;
    if (!fig) return;
    const f = fig.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    // Keep the tooltip (max 360px, centred on the mark) inside the plot.
    const half = Math.min(180, f.width / 2);
    const x = Math.min(Math.max(r.left + r.width / 2 - f.left, half), f.width - half);
    setTip({ ...t, x, y: r.top - f.top });
  };

  const hide = () => setTip(null);

  const hover = (t: Omit<Tip, "x" | "y">) => ({
    onPointerEnter: (e: PointerEvent<HTMLElement>) => place(e.currentTarget, t),
    onPointerLeave: hide,
    onFocus: (e: FocusEvent<HTMLElement>) => place(e.currentTarget, t),
    onBlur: hide,
  });

  const gridStyle = { "--grid": pct(data.tickStep / len) } as CSSProperties;

  return (
    <figure className={styles.score} aria-labelledby="score-caption">
      <div className={styles.plot} ref={figRef} onPointerLeave={hide}>
        <div className={styles.axis} aria-hidden="true">
          <span />
          <div className={styles.axisTrack}>
            {data.ticks.map((tk) => (
              <span key={tk.t} className={styles.tick} style={{ left: pct(tk.t / len) }}>
                {tk.label}
              </span>
            ))}
          </div>
        </div>

        {data.lanes.map((lane) => (
          <div key={lane.id} className={styles.lane}>
            <span className={styles.name} title={`${lane.name} talked for ${lane.talk}`}>
              <span className={styles.full}>{lane.name}</span>
              <span className={styles.short}>{lane.short}</span>
            </span>
            <div className={styles.track} style={gridStyle}>
              {data.voices
                .filter((v) => v.lane === lane.id)
                .map((v) => (
                  <span
                    key={v.id}
                    className={styles.voice}
                    style={{ left: pct(v.t / len), width: `max(2px, calc(${pct(v.dur / len)} - 2px))` }}
                    onClick={() => goTo("transcript", v.id)}
                    {...hover({ clock: v.clock, heading: lane.name, text: v.text })}
                  />
                ))}
            </div>
          </div>
        ))}

        <div className={`${styles.lane} ${styles.agentLane}`}>
          <span className={styles.name}>
            <span className="lamp" aria-hidden="true" />
            <strong>{data.agentName}</strong>
          </span>
          <div className={`${styles.track} ${styles.agentTrack}`} style={gridStyle}>
            {data.chat.map((c) => (
              <button
                key={c.id}
                type="button"
                className={styles.chat}
                style={{ left: pct(c.t / len) }}
                aria-label={`${c.clock}, ${data.agentName} posted in the meeting chat`}
                onClick={() => goTo("said", `turn-${c.turnId}`)}
                {...hover({ clock: c.clock, heading: "Posted in the meeting chat", text: c.text, agent: true })}
              />
            ))}
            {data.heldBack.map((h) => (
              <button
                key={h.id}
                type="button"
                className={styles.ring}
                style={{ left: pct(h.t / len) }}
                aria-label={`${h.clock}, ${data.agentName} held back. ${h.note}`}
                onClick={() => goTo("transcript", h.id)}
                {...hover({ clock: h.clock, heading: h.heading, text: h.text, note: h.note })}
              />
            ))}
            {data.spoke.map((s, i) => (
              <button
                key={s.id}
                type="button"
                className={styles.spoke}
                style={{ left: pct(s.t / len), width: `max(6px, ${pct(s.dur / len)})`, "--i": i } as CSSProperties}
                aria-label={`${s.clock}, ${s.heading}: ${s.text}`}
                onClick={() => goTo("said", `turn-${s.turnId}`)}
                {...hover({ clock: s.clock, heading: s.heading, text: s.text, agent: true })}
              />
            ))}
          </div>
        </div>

        {tip && (
          <div className={styles.tip} style={{ left: tip.x, top: tip.y }} role="presentation">
            <p className={styles.tipHead}>
              <strong className="tabular">{tip.clock}</strong> {tip.heading}
            </p>
            <p className={`verbatim ${styles.tipText}`}>{tip.text}</p>
            {tip.note && <p className={styles.tipNote}>{tip.note}</p>}
          </div>
        )}
      </div>

      <figcaption id="score-caption" className={styles.caption}>
        <p className={styles.summary}>{data.summary}</p>
        <ul className={styles.legend} aria-label="Key">
          <li>
            <span className={styles.keyVoice} aria-hidden="true" /> People talking
          </li>
          <li>
            <span className={styles.keySpoke} aria-hidden="true" /> {data.agentName} answering
          </li>
          {data.heldBack.length > 0 && (
            <li>
              <span className={styles.keyRing} aria-hidden="true" /> Named, but not asked
            </li>
          )}
          {data.chat.length > 0 && (
            <li>
              <span className={styles.keyChat} aria-hidden="true" /> Posted in chat
            </li>
          )}
          {data.note && <li className={styles.legendNote}>{data.note}</li>}
        </ul>
      </figcaption>
    </figure>
  );
}
