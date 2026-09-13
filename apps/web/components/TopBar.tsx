import Link from "next/link";
import { AGENT_NAME, OWNER } from "@/lib/people";
import styles from "./TopBar.module.css";

export function TopBar() {
  return (
    <header className={styles.bar}>
      <div className={styles.inner}>
        <Link href="/" className={`${styles.wordmark} condensed`}>
          Meeting Agent
        </Link>
        <div className={styles.right}>
          <p className={styles.status} title="Not in a meeting right now">
            <span className="lamp lamp-off" aria-hidden="true" />
            {AGENT_NAME} is off air
          </p>
          <span className={styles.avatar} title={OWNER.name} aria-label={`Signed in as ${OWNER.name}`} role="img">
            {OWNER.initials}
          </span>
        </div>
      </div>
    </header>
  );
}
