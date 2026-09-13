"use client";

import { useState } from "react";
import styles from "./SendForm.module.css";

/**
 * "Join now" or "Schedule". The backend wants a timezone-aware time at least 10
 * minutes ahead, so the browser converts its local pick to ISO with the offset.
 */
export function WhenField({ onChange }: { onChange?: (scheduled: boolean) => void }) {
  const [when, setWhen] = useState<"now" | "later">("now");
  const [local, setLocal] = useState("");
  const iso = local ? new Date(local).toISOString() : "";

  const pick = (value: "now" | "later") => {
    setWhen(value);
    onChange?.(value === "later");
  };

  return (
    <fieldset className={styles.when}>
      <legend className={styles.label}>When</legend>
      <div className={styles.segmented}>
        <label>
          <input type="radio" name="when" value="now" checked={when === "now"} onChange={() => pick("now")} />
          <span>Join now</span>
        </label>
        <label>
          <input type="radio" name="when" value="later" checked={when === "later"} onChange={() => pick("later")} />
          <span>Schedule</span>
        </label>
      </div>
      {when === "later" && (
        <div className={styles.schedule}>
          <input type="datetime-local" value={local} onChange={(e) => setLocal(e.target.value)} required aria-label="Join at" />
          <span className={styles.hint}>At least 10 minutes from now, within 28 days.</span>
        </div>
      )}
      <input type="hidden" name="join_at" value={iso} />
    </fieldset>
  );
}
