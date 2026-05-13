/**
 * Market-hours helpers for the status bar.
 *
 * We deliberately keep this self-contained (no Date library) and check
 * windows in the relevant timezone using `Intl.DateTimeFormat` so we
 * don't have to import 30 KB of moment/luxon for a single read.
 *
 * Sessions:
 *   IN (NSE/BSE): 09:15 — 15:30 IST, Mon-Fri
 *   US (NYSE):    09:30 — 16:00 ET,  Mon-Fri  (DST shifts handled by Intl)
 *   FX:           Sun 17:00 ET — Fri 17:00 ET, ~24/5
 *
 * (Holiday calendars are out of scope — the API can override at runtime.)
 */

export type MarketCode = "IN" | "US" | "FX";

export interface MarketStatus {
  code: MarketCode;
  isOpen: boolean;
  /** Human label for tooltips: "Open", "Closed — opens 09:15 IST", etc. */
  label: string;
}

interface ZonedNow {
  weekday: number; // 0 = Sun ... 6 = Sat
  hour: number;
  minute: number;
}

/**
 * Read wall-clock time in a given IANA timezone — works in modern browsers
 * and Node 18+. We use `formatToParts` because the locale defaults are
 * stable and machine-readable.
 */
function nowInZone(timeZone: string, when: Date = new Date()): ZonedNow {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = fmt.formatToParts(when);
  const get = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((p) => p.type === type)?.value ?? "";

  const weekdayMap: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6,
  };

  return {
    weekday: weekdayMap[get("weekday")] ?? 0,
    hour: Number.parseInt(get("hour"), 10) || 0,
    minute: Number.parseInt(get("minute"), 10) || 0,
  };
}

function inWindow(
  z: ZonedNow,
  startH: number,
  startM: number,
  endH: number,
  endM: number,
): boolean {
  if (z.weekday === 0 || z.weekday === 6) return false;
  const cur = z.hour * 60 + z.minute;
  const start = startH * 60 + startM;
  const end = endH * 60 + endM;
  return cur >= start && cur < end;
}

export function getIndiaStatus(when?: Date): MarketStatus {
  const z = nowInZone("Asia/Kolkata", when);
  const open = inWindow(z, 9, 15, 15, 30);
  return {
    code: "IN",
    isOpen: open,
    label: open ? "NSE/BSE — Open" : "NSE/BSE — Closed",
  };
}

export function getUSStatus(when?: Date): MarketStatus {
  const z = nowInZone("America/New_York", when);
  const open = inWindow(z, 9, 30, 16, 0);
  return {
    code: "US",
    isOpen: open,
    label: open ? "NYSE — Open" : "NYSE — Closed",
  };
}

/**
 * FX runs effectively 24h Mon–Fri (and a slice of Sun/Fri). For the
 * purposes of a status indicator we treat any weekday as "open".
 */
export function getFXStatus(when?: Date): MarketStatus {
  const z = nowInZone("UTC", when);
  const open = z.weekday >= 1 && z.weekday <= 5;
  return {
    code: "FX",
    isOpen: open,
    label: open ? "FX — Open" : "FX — Closed",
  };
}

export function getAllMarketStatus(when?: Date): {
  india: MarketStatus;
  us: MarketStatus;
  fx: MarketStatus;
  anyOpen: boolean;
} {
  const india = getIndiaStatus(when);
  const us = getUSStatus(when);
  const fx = getFXStatus(when);
  return {
    india,
    us,
    fx,
    anyOpen: india.isOpen || us.isOpen,
  };
}
