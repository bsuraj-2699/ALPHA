/**
 * Consistent number/price/percent formatting across the app.
 * Anything that emits a number should go through here so we get
 * locale-aware grouping AND the right "tabular" feel everywhere.
 */

const PRICE_FMT_USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PRICE_FMT_INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PLAIN_FMT = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const COMPACT_FMT = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});

const PCT_FMT = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: "exceptZero",
});

export type Market = "IN" | "US";

export function formatPrice(
  value: number | null | undefined,
  market: Market = "US",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return market === "IN" ? PRICE_FMT_INR.format(value) : PRICE_FMT_USD.format(value);
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return PLAIN_FMT.format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return COMPACT_FMT.format(value);
}

/**
 * Accepts the raw fractional change (e.g. 0.0042 -> "+0.42%").
 * If the number looks like it's already in percentage units (|v| > 1)
 * we still treat it as a fraction — the caller is expected to normalise.
 */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return PCT_FMT.format(value);
}

/**
 * Map a numeric change to one of the brand color tokens.
 * Returns the Tailwind utility class so callers can do:
 *   <span className={signColor(change)}>...</span>
 */
export function signColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-muted-foreground";
  }
  if (value > 0) return "text-buy";
  if (value < 0) return "text-sell";
  return "text-muted-foreground";
}
