"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { AnimatedNumber } from "@/components/animated-number";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { CopyButton } from "@/components/copy-button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Decision, Signal } from "@/types/api";

interface DecisionCardProps {
  decision: Decision | null;
  /** Whether we've kicked off a run but haven't received the decision yet */
  pending: boolean;
}

const SIGNAL_TONE: Record<Signal, "buy" | "sell" | "warn" | "gold" | "muted"> = {
  STRONG_BUY: "buy",
  BUY: "buy",
  HOLD: "warn",
  SELL: "sell",
  STRONG_SELL: "sell",
};

const SIGNAL_LABEL: Record<Signal, string> = {
  STRONG_BUY: "Strong Buy",
  BUY: "Buy",
  HOLD: "Hold",
  SELL: "Sell",
  STRONG_SELL: "Strong Sell",
};

const PROGRESS_TONE: Record<Signal, "buy" | "sell" | "warn" | "gold"> = {
  STRONG_BUY: "buy",
  BUY: "buy",
  HOLD: "warn",
  SELL: "sell",
  STRONG_SELL: "sell",
};

function PriceRow({
  label,
  value,
  tone,
  showCopy,
}: {
  label: string;
  value: number | null;
  tone?: "buy" | "sell" | "neutral";
  showCopy?: boolean;
}) {
  const colorClass =
    tone === "buy"
      ? "text-buy"
      : tone === "sell"
        ? "text-sell"
        : "text-foreground";

  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </span>
      <div className="flex items-center gap-1">
        <AnimatedNumber
          value={value}
          decimals={2}
          prefix="$"
          className={cn("text-sm", colorClass)}
        />
        {showCopy && value !== null && <CopyButton value={value} label={`Copy ${label}`} />}
      </div>
    </div>
  );
}

export function DecisionCard({ decision, pending }: DecisionCardProps) {
  if (!decision && pending) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex items-start justify-between">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-7 w-32" />
            </div>
            <Skeleton className="h-7 w-16" />
          </div>
          <Skeleton className="h-1.5 w-full" />
          <div className="flex flex-col gap-2 pt-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!decision) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-2 p-5">
          <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Decision
          </span>
          <p className="font-display text-lg text-muted-foreground">
            Awaiting analysis
          </p>
          <p className="text-xs text-muted-foreground">
            Pick a ticker on the left and click Analyze.
          </p>
        </CardContent>
      </Card>
    );
  }

  const signal = decision.signal;
  const tone = SIGNAL_TONE[signal];
  const isStrong = signal === "STRONG_BUY" || signal === "STRONG_SELL";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <Card
        className={cn(
          "relative overflow-hidden",
          tone === "buy" && "border-buy/30",
          tone === "sell" && "border-sell/30",
          tone === "warn" && "border-warn/30",
        )}
      >
        {/* Accent bar */}
        <div
          className={cn(
            "absolute inset-x-0 top-0 h-[2px]",
            tone === "buy" && "bg-buy",
            tone === "sell" && "bg-sell",
            tone === "warn" && "bg-warn",
            tone === "gold" && "bg-gold",
            tone === "muted" && "bg-muted",
          )}
        />

        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                Decision
              </span>
              <h2 className="font-display text-2xl font-semibold leading-tight">
                {SIGNAL_LABEL[signal]}
              </h2>
            </div>
            <div className="flex flex-col items-end gap-1">
              <Badge variant={tone}>{signal}</Badge>
              {isStrong && decision.requires_human_review && (
                <Badge variant="gold" className="text-[9px]">
                  needs review
                </Badge>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                Confidence
              </span>
              <AnimatedNumber
                value={decision.confidence}
                decimals={1}
                suffix="%"
                className="text-xs"
              />
            </div>
            <Progress value={decision.confidence} tone={PROGRESS_TONE[signal]} />
          </div>

          <div className="flex items-center justify-between rounded-md bg-muted/30 px-3 py-2 ring-1 ring-inset ring-border">
            <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              Position size
            </span>
            <AnimatedNumber
              value={decision.position_size_pct}
              decimals={1}
              suffix="%"
              className="text-sm text-gold"
            />
          </div>

          <div className="flex flex-col divide-y divide-border">
            <PriceRow
              label="Entry"
              value={decision.entry_price}
              tone="neutral"
              showCopy
            />
            <PriceRow
              label="Stop"
              value={decision.stop_loss}
              tone="sell"
              showCopy
            />
            <PriceRow
              label="Target"
              value={decision.target_price}
              tone="buy"
              showCopy
            />
          </div>

          {decision.rationale && (
            <p className="text-xs leading-relaxed text-muted-foreground line-clamp-3">
              {decision.rationale}
            </p>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
