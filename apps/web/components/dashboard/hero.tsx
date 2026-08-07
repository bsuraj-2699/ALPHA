import Link from "next/link";
import { ArrowRight, ListTree } from "lucide-react";

import { MarketClock } from "@/components/dashboard/market-clock";

/** Headline numbers that describe the deterministic engine, not a portfolio. */
const FACTS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "36", label: "scoring rules" },
  { value: "8", label: "pillars" },
  { value: "5", label: "analysts" },
  { value: "<30s", label: "to decision" },
];

/**
 * Dashboard hero. Sits on the app's aurora field: a glass slab with two
 * drifting accent orbs behind it, the value proposition, and the two
 * routes that actually matter (run something / see what ran).
 */
export function DashboardHero() {
  return (
    <section className="relative overflow-hidden rounded-3xl glass-strong ring-gradient">
      {/* Accent orbs — decorative, never intercept clicks. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-24 -top-32 h-72 w-72 rounded-full bg-accent1/20 blur-[90px] animate-float"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 right-0 h-80 w-80 rounded-full bg-accent2/20 blur-[100px] animate-float"
        style={{ animationDelay: "2s" }}
      />

      <div className="relative flex flex-col gap-8 p-8 md:p-12">
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            India equities
          </span>
          <MarketClock />
        </div>

        <div className="flex flex-col gap-4">
          <h1 className="max-w-3xl font-display text-4xl font-semibold leading-[1.08] tracking-tight md:text-6xl">
            Deterministic calls.
            <br />
            <span className="text-gradient">Narrated by AI.</span>
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted-foreground md:text-base">
            Signal, size, stop and target come from a pure-Python rule engine —
            the same inputs always give the same answer. The models only write
            the explanation.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/analyze"
            className="group inline-flex h-11 items-center gap-2 rounded-xl bg-gradient-to-r from-accent1 to-accent2 px-6 text-sm font-semibold text-[#05060a] transition-transform duration-200 hover:-translate-y-0.5 glow-accent focus-visible:outline-none"
          >
            New analysis
            <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
          </Link>
          <Link
            href="/runs"
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-5 text-sm font-medium text-foreground transition-colors duration-200 hover:border-white/20 hover:bg-white/[0.06] focus-visible:outline-none"
          >
            <ListTree className="h-4 w-4 text-muted-foreground" />
            Recent runs
          </Link>
        </div>

        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-white/[0.07] bg-white/[0.06] sm:grid-cols-4">
          {FACTS.map((fact) => (
            <div
              key={fact.label}
              className="flex flex-col gap-1 bg-[#0d1017]/80 px-5 py-4 backdrop-blur-sm"
            >
              <dt className="sr-only">{fact.label}</dt>
              <dd className="font-mono text-2xl font-semibold tabular-nums text-foreground">
                {fact.value}
              </dd>
              <span className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                {fact.label}
              </span>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
