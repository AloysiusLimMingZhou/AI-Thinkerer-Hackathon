/**
 * Date and time formatting in each meeting's own UTC offset.
 *
 * Done by hand rather than with Intl so the server and every browser produce the same
 * strings (ICU versions disagree on things like "Sep" vs "Sept"), which keeps
 * hydration clean.
 */

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

interface WallClock {
  year: number;
  month: number; // 0-11
  day: number;
  weekday: number; // 0-6
  hour: number;
  minute: number;
  second: number;
}

function offsetMinutes(iso: string): number {
  const m = iso.match(/([+-])(\d{2}):(\d{2})$/);
  if (!m) return 0;
  return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3]));
}

/** Wall-clock time `addSeconds` after `iso`, in iso's own offset. Date-only strings are read as local midnight. */
export function wallClock(iso: string, addSeconds = 0): WallClock {
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const base = isDateOnly ? Date.parse(`${iso}T00:00:00Z`) : Date.parse(iso) + offsetMinutes(iso) * 60_000;
  const d = new Date(base + addSeconds * 1000);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth(),
    day: d.getUTCDate(),
    weekday: d.getUTCDay(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    second: d.getUTCSeconds(),
  };
}

const pad = (n: number) => String(n).padStart(2, "0");

/** "10:04", or "10:04:12" with seconds. */
export function clock(iso: string, addSeconds = 0, withSeconds = false): string {
  const w = wallClock(iso, addSeconds);
  return withSeconds ? `${pad(w.hour)}:${pad(w.minute)}:${pad(w.second)}` : `${pad(w.hour)}:${pad(w.minute)}`;
}

/** "Friday 11 September" */
export function longDay(iso: string): string {
  const w = wallClock(iso);
  return `${WEEKDAYS[w.weekday]} ${w.day} ${MONTHS[w.month]}`;
}

/** "Fri 11 Sep" */
export function shortDay(iso: string): string {
  const w = wallClock(iso);
  return `${WEEKDAYS[w.weekday].slice(0, 3)} ${w.day} ${MONTHS[w.month].slice(0, 3)}`;
}

/** "11 September" */
export function dayMonth(iso: string): string {
  const w = wallClock(iso);
  return `${w.day} ${MONTHS[w.month]}`;
}

/** Stable key for grouping by calendar day. */
export function dayKey(iso: string): string {
  const w = wallClock(iso);
  return `${w.year}-${pad(w.month + 1)}-${pad(w.day)}`;
}

/** "17 min", "1 h 4 min", "40 s" */
export function duration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const totalMin = Math.round(s / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** "1 hour 52 minutes", for running prose. */
export function durationLong(seconds: number): string {
  const totalMin = Math.round(seconds / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const mins = `${m} ${m === 1 ? "minute" : "minutes"}`;
  if (h === 0) return mins;
  const hours = `${h} ${h === 1 ? "hour" : "hours"}`;
  return m === 0 ? hours : `${hours} ${mins}`;
}

/** "2.1 s" */
export function seconds1(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

/** "HH:MM:SS.mmm" offset, for WebVTT. */
export function vttTime(seconds: number): string {
  const ms = Math.round(seconds * 1000);
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${pad(h)}:${pad(m)}:${pad(s)}.${String(ms % 1000).padStart(3, "0")}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "one", "two" ... for small counts in running prose. */
export function spelled(n: number): string {
  const words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  return words[n] ?? String(n);
}

export function percent(x: number): string {
  return `${Math.round(x * 100)}%`;
}
