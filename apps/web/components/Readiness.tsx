import type { Health, RecallStatus } from "@/lib/api-types";
import { Icon } from "./Icon";
import styles from "./Readiness.module.css";

const SETTINGS: { key: string; label: string }[] = [
  { key: "RECALL_API_KEY", label: "Recall key, to join meetings" },
  { key: "RECALL_WEBHOOK_VERIFICATION_SECRET", label: "Recall webhook secret, to receive transcripts" },
  { key: "PUBLIC_API_BASE_URL", label: "Public backend address Recall can reach" },
  { key: "BACKEND_API_TOKEN", label: "Backend operator token" },
  { key: "OPENAI_API_KEY", label: "OpenAI key, for answers and minutes" },
  { key: "ELEVENLABS_API_KEY", label: "ElevenLabs key, for the voice" },
];

/** What GET /recall/status says is configured. Presence isn't proof a live meeting works. */
export function Readiness({ status, health }: { status: RecallStatus; health: Health | null }) {
  const missing = new Set(status.missing);
  return (
    <section className={styles.panel} aria-labelledby="ready-title">
      <h2 id="ready-title" className={styles.title}>
        {status.configured ? "Ready to join meetings" : `${missing.size} backend ${missing.size === 1 ? "setting is" : "settings are"} missing`}
      </h2>
      <ul className={styles.list}>
        {SETTINGS.map((s) => {
          const ok = !missing.has(s.key);
          return (
            <li key={s.key} className={ok ? styles.ok : styles.missing}>
              <span className={styles.mark} aria-hidden="true">
                {ok ? <Icon name="check" size={14} /> : <Icon name="x" size={14} />}
              </span>
              <span>
                {s.label}
                {!ok && <code className={styles.code}>{s.key}</code>}
              </span>
              <span className="sr-only">{ok ? "set" : "missing"}</span>
            </li>
          );
        })}
      </ul>
      <p className={styles.note}>
        Set these in the backend’s <code>.env</code> and restart it. Being set isn’t the same as working: run a private test call before the demo.
        {health && !health.openai_configured && " Without OpenAI, it can’t answer or write minutes."}
      </p>
    </section>
  );
}
