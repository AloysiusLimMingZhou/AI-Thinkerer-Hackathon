/** The tabs of a meeting record. Shared by the server page and the client tabs. */
export const VIEWS = ["summary", "said", "transcript"] as const;
export type View = (typeof VIEWS)[number];

export function isView(v: unknown): v is View {
  return typeof v === "string" && (VIEWS as readonly string[]).includes(v);
}
