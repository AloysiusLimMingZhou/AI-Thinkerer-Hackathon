import { lengthSeconds, spokenTurns } from "@/lib/data";
import { duration, plural } from "@/lib/format";
import { AGENT, type Meeting } from "@/lib/types";
import styles from "./MiniStrip.module.css";

const pct = (x: number) => `${(x * 100).toFixed(3)}%`;

/**
 * A meeting in one line: grey where people spoke, red where Aloy-bot did.
 * Drawn to a shared scale (`scale` seconds = full width) so strip length is meeting length.
 */
export function MiniStrip({ meeting, scale }: { meeting: Meeting; scale: number }) {
  const len = lengthSeconds(meeting);
  const spoke = spokenTurns(meeting).length;
  const label = `${duration(len)} meeting. ${spoke ? `Aloy-bot spoke ${plural(spoke, "time")}.` : "Aloy-bot stayed quiet."}`;

  return (
    <div className={styles.strip} style={{ width: pct(Math.min(1, len / scale)) }} role="img" aria-label={label}>
      {meeting.utterances
        .filter((u) => u.channel === "voice")
        .map((u) => (
          <span
            key={u.id}
            className={u.speaker === AGENT ? styles.agent : styles.human}
            style={{ left: pct(u.t / len), width: pct(u.dur / len) }}
          />
        ))}
    </div>
  );
}
