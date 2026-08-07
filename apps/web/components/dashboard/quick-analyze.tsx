import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { INDIAN_TICKERS } from "@/lib/tickers";

const QUICK_ANALYZE_LIMIT = 8;

/**
 * One-tap entry points into the analyzer. `?auto=1` starts the run on
 * arrival, so these are a decision away rather than a form away.
 */
export function QuickAnalyze() {
  const picks = INDIAN_TICKERS.slice(0, QUICK_ANALYZE_LIMIT);

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {picks.map((ticker) => (
        <Link
          key={ticker.symbol}
          href={`/analyze/${ticker.symbol}?auto=1`}
          className="group relative flex items-center justify-between gap-3 overflow-hidden rounded-xl glass ring-gradient px-4 py-3.5 transition-transform duration-200 hover:-translate-y-0.5 focus-visible:outline-none"
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-mono text-sm font-semibold tracking-tight text-foreground">
              {ticker.symbol}
            </span>
            <span className="truncate text-[11px] text-muted-foreground">
              {ticker.name}
            </span>
          </div>
          <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all duration-200 group-hover:text-accent1 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
        </Link>
      ))}
    </div>
  );
}
