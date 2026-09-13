/**
 * Date and time formatting for backend timestamps (ISO, usually UTC).
 *
 * Everything renders on the server in one display time zone (DISPLAY_TIMEZONE,
 * default Asia/Kuala_Lumpur). Month and weekday names come from our own tables,
 * not ICU, so the output never varies between environments.
 */

const TIME_ZONE = process.env.DISPLAY_TIMEZONE || "Asia/Kuala_Lumpur";
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

const partsFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

interface Parts {
  year: number;
  month: number; // 0-11
  day: number;
  weekday: number;
  hour: number;
  minute: number;
  second: number;
}

export function toMs(iso: string): number {
  return Date.parse(iso);
}

function parts(value: string | number): Parts {
  const d = new Date(typeof value === "number" ? value : Date.parse(value));
  const p: Record<string, number> = {};
  for (const { type, value: v } of partsFormatter.formatToParts(d)) {
    if (type !== "literal") p[type] = Number(v);
  }
  const weekday = new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay();
  return { year: p.year, month: p.month - 1, day: p.day, weekday, hour: p.hour % 24, minute: p.minute, second: p.second };
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "14:32", or "14:32:05" with seconds. */
export function clock(value: string | number, withSeconds = false): string {
  const p = parts(value);
  return withSeconds ? `${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}` : `${pad(p.hour)}:${pad(p.minute)}`;
}

/** "Sunday 13 September" */
export function longDay(value: string | number): string {
  const p = parts(value);
  return `${WEEKDAYS[p.weekday]} ${p.day} ${MONTHS[p.month]}`;
}

/** "Sun 13 Sep" */
export function shortDay(value: string | number): string {
  const p = parts(value);
  return `${WEEKDAYS[p.weekday].slice(0, 3)} ${p.day} ${MONTHS[p.month].slice(0, 3)}`;
}

/** Calendar-day key in the display zone, for grouping. */
export function dayKey(value: string | number): string {
  const p = parts(value);
  return `${p.year}-${pad(p.month + 1)}-${pad(p.day)}`;
}

/** "17 min", "1 h 4 min", "40 s" */
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const totalMin = Math.round(s / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function spelled(n: number): string {
  const words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  return words[n] ?? String(n);
}

/** Relative phrase for how long ago something happened, from the server's clock. */
export function ago(value: string | number, now = Date.now()): string {
  const s = Math.round((now - (typeof value === "number" ? value : Date.parse(value))) / 1000);
  if (s < 45) return "just now";
  if (s < 90) return "a minute ago";
  if (s < 3600) return `${Math.round(s / 60)} minutes ago`;
  if (s < 5400) return "an hour ago";
  if (s < 86_400) return `${Math.round(s / 3600)} hours ago`;
  return `on ${shortDay(value)}`;
}

export const DISPLAY_TIME_ZONE = TIME_ZONE;
