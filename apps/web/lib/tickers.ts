/**
 * Indian-equity ticker helpers.
 *
 * UI-side rule: we display tickers WITHOUT the exchange suffix
 * (`RELIANCE`, not `RELIANCE.NS`). The backend's market-data providers
 * still require the suffix though, so every cross-network call must
 * round-trip through `toApiTicker` first.
 *
 * For the rare US ticker (`AAPL`) the helpers are pass-throughs.
 */

import type { Market } from "@/types/api";

export interface TickerOption {
  /** Display symbol — what we render in the UI (`RELIANCE`). */
  symbol: string;
  /** Human-readable company name, used in pickers / tooltips. */
  name: string;
  market: Market;
}

/**
 * Curated NSE shortlist used by Dashboard quick-analyze, Analyze
 * quick-picks and the run-queue ticker picker. Single source of truth
 * — extend here, never inline new arrays in components.
 */
export const INDIAN_TICKERS: ReadonlyArray<TickerOption> = [
  { symbol: "RELIANCE", name: "Reliance Industries", market: "IN" },
  { symbol: "TCS", name: "Tata Consultancy Services", market: "IN" },
  { symbol: "INFY", name: "Infosys", market: "IN" },
  { symbol: "HDFCBANK", name: "HDFC Bank", market: "IN" },
  { symbol: "ICICIBANK", name: "ICICI Bank", market: "IN" },
  { symbol: "SBIN", name: "State Bank of India", market: "IN" },
  { symbol: "ITC", name: "ITC Limited", market: "IN" },
  { symbol: "LT", name: "Larsen & Toubro", market: "IN" },
  { symbol: "AXISBANK", name: "Axis Bank", market: "IN" },
  { symbol: "MARUTI", name: "Maruti Suzuki", market: "IN" },
];

/** Symbols only — handy when callers don't need the company name. */
export const INDIAN_TICKER_SYMBOLS: ReadonlyArray<string> = INDIAN_TICKERS.map(
  (t) => t.symbol,
);

const NSE_SUFFIX = ".NS";
const BSE_SUFFIX = ".BO";

/**
 * Strip an exchange suffix so the symbol is safe to render in the UI.
 *
 *   toDisplayTicker("RELIANCE.NS") -> "RELIANCE"
 *   toDisplayTicker("RELIANCE")    -> "RELIANCE"
 *   toDisplayTicker("AAPL")        -> "AAPL"
 */
export function toDisplayTicker(symbol: string | null | undefined): string {
  if (!symbol) return "";
  const upper = symbol.trim().toUpperCase();
  if (upper.endsWith(NSE_SUFFIX)) {
    return upper.slice(0, -NSE_SUFFIX.length);
  }
  if (upper.endsWith(BSE_SUFFIX)) {
    return upper.slice(0, -BSE_SUFFIX.length);
  }
  return upper;
}

/**
 * Append the right exchange suffix so the symbol matches what the
 * backend's data providers expect.
 *
 *   toApiTicker("RELIANCE", "IN") -> "RELIANCE.NS"
 *   toApiTicker("RELIANCE.NS", "IN") -> "RELIANCE.NS" (idempotent)
 *   toApiTicker("AAPL", "US") -> "AAPL"
 */
export function toApiTicker(
  symbol: string,
  market: Market = "IN",
): string {
  const upper = symbol.trim().toUpperCase();
  if (market !== "IN") return upper;
  if (upper.endsWith(NSE_SUFFIX) || upper.endsWith(BSE_SUFFIX)) return upper;
  return `${upper}${NSE_SUFFIX}`;
}

/** True iff `symbol` is one of the curated names. Case-insensitive. */
export function isKnownIndianTicker(symbol: string): boolean {
  const display = toDisplayTicker(symbol);
  return INDIAN_TICKER_SYMBOLS.includes(display);
}

/** Friendly company name for `symbol`, falling back to the symbol itself. */
export function lookupTickerName(symbol: string): string {
  const display = toDisplayTicker(symbol);
  return INDIAN_TICKERS.find((t) => t.symbol === display)?.name ?? display;
}
