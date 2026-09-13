"use client";

import { useMemo, useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import styles from "./TranscriptPanel.module.css";

export interface TranscriptLine {
  id: string;
  clock: string;
  speaker: string;
  agent: boolean;
  chat: boolean;
  text: string;
  /** "question": it made Aloy-bot answer. "heldBack": Aloy-bot considered it and stayed quiet. */
  role?: "question" | "heldBack";
  note?: string;
}

function highlight(text: string, query: string): ReactNode {
  if (!query) return text;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const parts: ReactNode[] = [];
  let from = 0;
  let at = lower.indexOf(q);
  while (at !== -1) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at}>{text.slice(at, at + q.length)}</mark>);
    from = at + q.length;
    at = lower.indexOf(q, from);
  }
  parts.push(text.slice(from));
  return parts;
}

export function TranscriptPanel({ lines, source, agentName, download }: { lines: TranscriptLine[]; source: string; agentName: string; download: ReactNode }) {
  const [query, setQuery] = useState("");
  const [onlyAgent, setOnlyAgent] = useState(false);
  const q = query.trim();

  const shown = useMemo(
    () =>
      lines.filter(
        (l) => (!onlyAgent || l.agent || l.role) && (!q || l.text.toLowerCase().includes(q.toLowerCase()) || l.speaker.toLowerCase().includes(q.toLowerCase())),
      ),
    [lines, onlyAgent, q],
  );

  const filtered = onlyAgent || q;

  return (
    <div>
      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Icon name="search" size={17} />
          <span className="sr-only">Search the transcript</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the transcript" />
        </label>
        <button type="button" className={styles.toggle} aria-pressed={onlyAgent} onClick={() => setOnlyAgent((v) => !v)}>
          <span className={styles.switch} aria-hidden="true" />
          Only {agentName}’s moments
        </button>
        <p className={styles.count} aria-live="polite">
          {filtered ? `${shown.length} of ${lines.length} lines` : `${lines.length} lines`}
        </p>
        <div className={styles.download}>{download}</div>
      </div>
      <p className={styles.source}>{source}</p>

      {shown.length === 0 ? (
        <div className={styles.empty}>
          <p>No lines match “{q}”.</p>
          <button type="button" className="btn btn-quiet" onClick={() => setQuery("")}>
            Clear search
          </button>
        </div>
      ) : (
        <ol className={styles.lines}>
          {shown.map((l, i) => {
            const prev = shown[i - 1];
            const repeat = prev && prev.speaker === l.speaker && prev.chat === l.chat && !filtered;
            const cls = [styles.line, l.agent && styles.agent, l.chat && styles.chat, repeat && styles.repeat].filter(Boolean).join(" ");
            return (
              <li key={l.id} id={l.id} className={cls}>
                <span className={`${styles.time} tabular`}>{l.clock}</span>
                <span className={styles.who}>
                  {repeat ? (
                    <span className="sr-only">{l.speaker}</span>
                  ) : (
                    <>
                      {l.agent && <span className="lamp" aria-hidden="true" />}
                      {l.speaker}
                      {l.chat && (
                        <span className={styles.chatTag}>
                          <Icon name="chat" size={13} /> in chat
                        </span>
                      )}
                    </>
                  )}
                </span>
                <div className={styles.body}>
                  <p className={`verbatim ${styles.text}`}>{highlight(l.text, q)}</p>
                  {l.role === "heldBack" && l.note && (
                    <p className={styles.note}>
                      <Icon name="ring" size={14} />
                      <span>
                        <strong>{agentName} held back.</strong> {l.note}
                      </span>
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
