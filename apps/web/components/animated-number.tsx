"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { useCountUp } from "@/lib/use-count-up";

interface AnimatedNumberProps {
  value: number | null | undefined;
  /** Decimal places when the value is a finite number. Defaults to 2. */
  decimals?: number;
  /** Fallback display when the value is null / undefined. */
  fallback?: string;
  /** Optional prefix (e.g. "$") and suffix (e.g. "%"). */
  prefix?: string;
  suffix?: string;
  /** Use compact notation (e.g. 1.2K) for very large numbers. */
  compact?: boolean;
  className?: string;
}

const FORMATTERS = new Map<string, Intl.NumberFormat>();

function formatter(decimals: number, compact: boolean): Intl.NumberFormat {
  const key = `${decimals}-${compact ? "c" : "p"}`;
  let f = FORMATTERS.get(key);
  if (f) return f;
  f = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: compact ? 0 : decimals,
    maximumFractionDigits: decimals,
    notation: compact ? "compact" : "standard",
  });
  FORMATTERS.set(key, f);
  return f;
}

export function AnimatedNumber({
  value,
  decimals = 2,
  fallback = "—",
  prefix,
  suffix,
  compact = false,
  className,
}: AnimatedNumberProps) {
  // We have to call the hook unconditionally; pass 0 when the real value
  // is missing and render the fallback string in that case.
  const target = typeof value === "number" && !Number.isNaN(value) ? value : 0;
  const animated = useCountUp(target, 700);

  if (typeof value !== "number" || Number.isNaN(value)) {
    return (
      <span className={cn("font-mono tabular-nums text-muted-foreground", className)}>
        {fallback}
      </span>
    );
  }

  return (
    <span className={cn("font-mono tabular-nums", className)}>
      {prefix}
      {formatter(decimals, compact).format(animated)}
      {suffix}
    </span>
  );
}
