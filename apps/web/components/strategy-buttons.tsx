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

import { Card, CardContent } from "@/components/ui/card";
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

const MODE_ORDER: ReadonlyArray<StrategyMode> = [
  "intraday",
  "short_term",
  "long_term",
];

/**
 * Three premium CTAs that route the user to the Runs page with a
 * pre-selected strategy bucket. Reused on the Dashboard; can be
 * dropped anywhere else later.
 */
export function StrategyButtons({ className }: StrategyButtonsProps) {
  return (
    <div
      className={cn(
        "grid gap-4 md:grid-cols-3",
        className,
      )}
    >
      {MODE_ORDER.map((mode) => {
        const meta = STRATEGY_META[mode];
        const Icon = ICONS[mode];
        return (
          <Link
            key={mode}
            href={`/runs?mode=${mode}`}
            className="group focus:outline-none"
          >
            <Card
              className={cn(
                "relative h-full overflow-hidden rounded-xl border-border bg-card/60 transition-all duration-200",
                "ring-1 ring-inset ring-transparent",
                "hover:border-gold/40 hover:bg-card hover:ring-gold/30 hover:shadow-[0_0_28px_-12px_rgba(201,168,76,0.55)]",
                "group-focus-visible:border-gold/60 group-focus-visible:ring-gold/50",
              )}
            >
              <span className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-gold/40 to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100" />
              <CardContent className="flex flex-col gap-3 p-5">
                <div className="flex items-center justify-between">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gold/10 ring-1 ring-inset ring-gold/30 transition-colors group-hover:bg-gold/20">
                    <Icon className="h-4 w-4 text-gold" />
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground transition-all duration-200 group-hover:translate-x-0.5 group-hover:text-gold" />
                </div>
                <div className="flex flex-col gap-1">
                  <p className="font-display text-lg font-semibold leading-tight text-foreground">
                    {meta.label}
                  </p>
                  <p className="text-xs leading-relaxed text-muted-foreground line-clamp-2">
                    {meta.description}
                  </p>
                </div>
              </CardContent>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
