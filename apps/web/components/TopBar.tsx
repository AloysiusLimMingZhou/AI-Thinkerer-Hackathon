import Link from "next/link";
import { backend } from "@/lib/backend";
import { DEFAULT_AGENT, DEFAULT_OWNER } from "@/lib/meeting";
import styles from "./TopBar.module.css";

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "")).toUpperCase();
}

export async function TopBar() {
  // The bar shouldn't take the page down with it; the page reports backend problems itself.
  const sessions = await backend.listSessions().catch(() => []);
  const live = sessions.find((s) => s.status === "active");
  const agent = live?.agent_name ?? sessions[0]?.agent_name ?? DEFAULT_AGENT;
  const owner = sessions[0]?.owner_name ?? DEFAULT_OWNER;

  return (
    <header className={styles.bar}>
      <div className={styles.inner}>
        <Link href="/" className={`${styles.wordmark} condensed`}>
          Meeting Agent
        </Link>
        <div className={styles.right}>
          {live ? (
            <Link href={`/meetings/${live.id}`} className={styles.status}>
              <span className="lamp" aria-hidden="true" />
              {agent} is in {live.title}
            </Link>
          ) : (
            <p className={styles.status} title="Not in a meeting right now">
              <span className="lamp lamp-off" aria-hidden="true" />
              {agent} is off air
            </p>
          )}
          <span className={styles.avatar} title={owner} aria-label={`Working for ${owner}`} role="img">
            {initials(owner)}
          </span>
        </div>
      </div>
    </header>
  );
}
