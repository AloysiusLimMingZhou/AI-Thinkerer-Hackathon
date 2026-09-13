import { BackendError, backendUrl } from "@/lib/backend";

/** Full-page explanation when the dashboard can't use the backend. */
export function BackendDown({ error }: { error: unknown }) {
  const unauthorized = error instanceof BackendError && error.status === 401;
  const noToken = error instanceof BackendError && error.status === 503 && /BACKEND_API_TOKEN/.test(error.message);
  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "64px var(--gutter) 96px" }}>
      <h1 className="condensed" style={{ fontSize: "var(--t-48)", lineHeight: 1, fontWeight: 740 }}>
        {unauthorized ? "The backend didn’t accept the token" : noToken ? "The dashboard needs the backend token" : "Can’t reach the backend"}
      </h1>
      <p style={{ marginTop: 16, fontSize: "var(--t-18)", color: "var(--ink-2)", lineHeight: 1.5 }}>
        {unauthorized
          ? "BACKEND_API_TOKEN in apps/web/.env.local doesn’t match the one in the backend’s .env."
          : noToken
            ? "Add BACKEND_API_TOKEN to apps/web/.env.local, using the same value as the backend’s .env, then restart the dashboard."
            : `Nothing answered at ${backendUrl()}. Start the backend from the repository root, or point ALLOY_BACKEND_URL at the right address.`}
      </p>
      <pre className="sheet verbatim" style={{ marginTop: 24, padding: "16px 18px", overflowX: "auto", fontSize: "var(--t-14)", lineHeight: 1.6 }}>
        {`# repository root: the backend
uv sync
uv run python main.py

# apps/web/.env.local: the dashboard
ALLOY_BACKEND_URL=http://127.0.0.1:8000
BACKEND_API_TOKEN=<same value as the backend's .env>`}
      </pre>
    </main>
  );
}
