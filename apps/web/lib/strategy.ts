/**
 * Strategy / time-horizon mode constants.
 *
 * Three values are mirrored on the FastAPI side as
 * ``packages.shared.config.Mode``: ``intraday | short_term | long_term``.
 * Keep names in sync — the URL query string and the API request body
 * both use these literal values.
 */

export type StrategyMode = "intraday" | "short_term" | "long_term";

export const STRATEGY_MODES: ReadonlyArray<StrategyMode> = [
  "intraday",
  "short_term",
  "long_term",
];

export interface StrategyMeta {
  mode: StrategyMode;
  label: string;
  description: string;
  /**
   * TanStack Query refetch cadence (ms) for the run-detail card. The
   * server-side schedulers (`apps/api/scheduler.py`) are what actually
   * trigger fresh runs — this is purely the UI's "check the cached
   * detail again" cadence. Intraday is fast (5 min) so the card
   * smoothly follows the scheduler; the daily modes only need to
   * repaint after the 10:00 IST batch, so a 30-minute cadence keeps
   * traffic minimal while still catching the bucket flip-over within
   * the hour.
   */
  refreshIntervalMs: number;
}

/** Display + behavior metadata for each strategy bucket. */
export const STRATEGY_META: Record<StrategyMode, StrategyMeta> = {
  intraday: {
    mode: "intraday",
    label: "Intraday",
    description:
      "Same-session trades. Technical / sentiment / risk analysts; skips fundamentals. Auto-refreshed every 5 minutes during NSE hours.",
    refreshIntervalMs: 5 * 60_000,
  },
  short_term: {
    mode: "short_term",
    label: "Short term",
    description:
      "Days-to-weeks horizon. Adds the macro analyst on top of the intraday lineup. Auto-refreshed once per business day at 10:00 IST.",
    refreshIntervalMs: 30 * 60_000,
  },
  long_term: {
    mode: "long_term",
    label: "Long term",
    description:
      "Multi-month horizon. Runs all five analysts with the framework's default pillar weighting. Auto-refreshed once per business day at 10:00 IST.",
    refreshIntervalMs: 30 * 60_000,
  },
};

/** Parse `?mode=...` query strings, falling back when the value is bad. */
export function parseStrategyMode(
  raw: string | null | undefined,
  fallback: StrategyMode = "long_term",
): StrategyMode {
  if (!raw) return fallback;
  const cleaned = raw.toLowerCase().replace(/[-\s]+/g, "_");
  // Accept the user-friendly URL aliases the dashboard buttons emit.
  if (cleaned === "shortterm" || cleaned === "short_term") return "short_term";
  if (cleaned === "longterm" || cleaned === "long_term") return "long_term";
  if (cleaned === "intraday") return "intraday";
  return fallback;
}
