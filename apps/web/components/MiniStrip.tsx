import type { Timeline } from "@/lib/score";
import styles from "./MiniStrip.module.css";

const pct = (x: number) => `${(x * 100).toFixed(3)}%`;

/**
 * A meeting in one line: grey where people spoke, red where the delegate answered.
 * Drawn to a shared scale (`scale` seconds = full width) so strip length is meeting length.
 */
export function MiniStrip({ tl, scale, label }: { tl: Timeline; scale: number; label: string }) {
  const len = tl.span;
  return (
    <div className={styles.strip} style={{ width: pct(Math.min(1, Math.max(0.04, len / scale))) }} role="img" aria-label={label}>
      {tl.human.map((h) => (
        <span key={h.id} className={styles.human} style={{ left: pct(h.t / len), width: pct(h.dur / len) }} />
      ))}
      {tl.agent.map((a) => (
        <span key={a.sequence} className={styles.agent} style={{ left: pct(a.t / len), width: pct(a.dur / len) }} />
      ))}
    </div>
  );
}
