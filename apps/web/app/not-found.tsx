import Link from "next/link";

export default function NotFound() {
  return (
    <main style={{ maxWidth: 640, margin: "0 auto", padding: "80px var(--gutter)" }}>
      <h1 className="condensed" style={{ fontSize: "var(--t-48)", lineHeight: 1 }}>
        That meeting isn’t here
      </h1>
      <p style={{ marginTop: 14, fontSize: "var(--t-18)", color: "var(--ink-2)" }}>
        The link may be old, or the meeting was deleted. Your other meetings are all on the <Link href="/">meetings page</Link>.
      </p>
    </main>
  );
}
