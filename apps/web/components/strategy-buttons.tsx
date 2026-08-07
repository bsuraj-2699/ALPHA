"use client";

import * as React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Clock,
  type LucideIcon,
  Sunrise,
  TrendingUp,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { STRATEGY_META, type StrategyMode } from "@/lib/strategy";

interface StrategyButtonsProps {
  className?: string;
}

const ICONS: Record<StrategyMode, LucideIcon> = {
  intraday: Clock,
  short_term: Sunrise,
  long_term: TrendingUp,
};

/** One accent stop per bucket, so the three cards read as a spectrum. */
const TINTS: Record<StrategyMode, { icon: string; wash: string }> = {
  intraday: { icon: "text-accent1", wash: "from-accent1/18" },
  short_term: { icon: "text-accent2", wash: "from-accent2/18" },
  long_term: { icon: "text-accent3", wash: "from-accent3/18" },
};

const MODE_ORDER: ReadonlyArray<StrategyMode> = [
  "intraday",
  "short_term",
  "long_term",
];

/**
 * Three CTAs that route the user to the Runs page with a pre-selected
 * strategy bucket. Reused on the Dashboard; can be dropped anywhere else.
 */
export function StrategyButtons({ className }: StrategyButtonsProps) {
  return (
    <div className={cn("grid gap-4 md:grid-cols-3", className)}>
      {MODE_ORDER.map((mode) => {
        const meta = STRATEGY_META[mode];
        const Icon = ICONS[mode];
        const tint = TINTS[mode];

        return (
          <Link
            key={mode}
            href={`/runs?mode=${mode}`}
            className={cn(
              "group relative flex h-full flex-col gap-4 overflow-hidden rounded-2xl glass ring-gradient p-5",
              "transition-transform duration-200 hover:-translate-y-1 focus-visible:outline-none",
            )}
          >
            {/* Corner wash that warms up on hover. */}
            <div
              aria-hidden
              className={cn(
                "pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-gradient-to-br to-transparent blur-2xl",
                "opacity-0 transition-opacity duration-300 group-hover:opacity-100",
                tint.wash,
              )}
            />

            <div className="relative flex items-start justify-between">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04]">
                <Icon className={cn("h-[18px] w-[18px]", tint.icon)} />
              </span>
              <ArrowRight className="h-4 w-4 translate-x-0 text-muted-foreground opacity-0 transition-all duration-200 group-hover:translate-x-1 group-hover:opacity-100" />
            </div>

            <div className="relative flex flex-col gap-1.5">
              <p className="font-display text-lg font-semibold leading-tight text-foreground">
                {meta.label}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground line-clamp-3">
                {meta.description}
              </p>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
