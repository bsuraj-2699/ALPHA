"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";

interface ProgressProps {
  /** 0 — 100 */
  value: number;
  /** Track + indicator color tone */
  tone?: "buy" | "sell" | "warn" | "gold" | "neutral";
  className?: string;
  showValue?: boolean;
}

const TONE_COLOR: Record<NonNullable<ProgressProps["tone"]>, string> = {
  buy: "bg-buy",
  sell: "bg-sell",
  warn: "bg-warn",
  gold: "bg-gold",
  neutral: "bg-foreground/70",
};

export function Progress({
  value,
  tone = "gold",
  className,
  showValue,
}: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("relative w-full", className)}>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted/60">
        <motion.div
          className={cn("h-full rounded-full", TONE_COLOR[tone])}
          initial={{ width: 0 }}
          animate={{ width: `${clamped}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
      {showValue && (
        <span className="mt-1 block text-right font-mono text-[11px] tabular-nums text-muted-foreground">
          {clamped.toFixed(1)}
        </span>
      )}
    </div>
  );
}
