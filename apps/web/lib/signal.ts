import type { Signal } from "@/types/api";

export interface SignalTheme {
  label: string;
  tone: "buy" | "sell" | "warn";
  color: string; // css var reference
  text: string; // tailwind text class
  bg: string; // tailwind bg tint class
  glow: string; // glass glow utility
  dir: 1 | -1 | 0;
}

const BUY = "var(--buy)";
const SELL = "var(--sell)";
const WARN = "var(--neutral)";

export const SIGNAL_THEME: Record<Signal, SignalTheme> = {
  STRONG_BUY: {
    label: "Strong Buy",
    tone: "buy",
    color: BUY,
    text: "text-buy",
    bg: "bg-buy/10",
    glow: "glow-buy",
    dir: 1,
  },
  BUY: {
    label: "Buy",
    tone: "buy",
    color: BUY,
    text: "text-buy",
    bg: "bg-buy/10",
    glow: "glow-buy",
    dir: 1,
  },
  HOLD: {
    label: "Hold",
    tone: "warn",
    color: WARN,
    text: "text-warn",
    bg: "bg-warn/10",
    glow: "glow-warn",
    dir: 0,
  },
  SELL: {
    label: "Sell",
    tone: "sell",
    color: SELL,
    text: "text-sell",
    bg: "bg-sell/10",
    glow: "glow-sell",
    dir: -1,
  },
  STRONG_SELL: {
    label: "Strong Sell",
    tone: "sell",
    color: SELL,
    text: "text-sell",
    bg: "bg-sell/10",
    glow: "glow-sell",
    dir: -1,
  },
};

export function signalTheme(signal: Signal | null | undefined): SignalTheme {
  return (signal && SIGNAL_THEME[signal]) || SIGNAL_THEME.HOLD;
}

/** 0-100 score -> stop color for gauges/bars. */
export function scoreColor(score: number): string {
  if (score >= 66) return BUY;
  if (score >= 45) return WARN;
  return SELL;
}

export const PILLAR_LABELS: Record<string, string> = {
  fundamentals: "Fundamentals",
  balance_sheet: "Balance Sheet",
  trend: "Trend",
  momentum: "Momentum",
  sentiment: "Sentiment",
  valuation: "Valuation",
  macro: "Macro",
  risk: "Risk",
  technicals: "Technicals",
};

export function pillarLabel(key: string): string {
  return (
    PILLAR_LABELS[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}
