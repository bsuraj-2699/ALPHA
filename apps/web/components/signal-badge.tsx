import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Signal } from "@/types/api";

interface SignalBadgeProps {
  signal: Signal | "PENDING" | null | undefined;
  /** Optional confidence percentage (0-100) appended in parentheses. */
  confidence?: number | null;
  className?: string;
}

const TONE: Record<string, "buy" | "sell" | "warn" | "muted"> = {
  STRONG_BUY: "buy",
  BUY: "buy",
  HOLD: "warn",
  SELL: "sell",
  STRONG_SELL: "sell",
  PENDING: "muted",
};

const LABEL: Record<string, string> = {
  STRONG_BUY: "STRONG BUY",
  BUY: "BUY",
  HOLD: "HOLD",
  SELL: "SELL",
  STRONG_SELL: "STRONG SELL",
  PENDING: "PENDING",
};

/**
 * Standardized signal pill.
 *
 *   BUY  -> green (`buy` tone)
 *   SELL -> red   (`sell` tone)
 *   HOLD -> amber (`warn` tone)
 *
 * Renders a neutral "PENDING" pill for in-flight or unanalyzed tickers.
 */
export function SignalBadge({ signal, confidence, className }: SignalBadgeProps) {
  const key = signal ?? "PENDING";
  const tone = TONE[key] ?? "muted";
  const label = LABEL[key] ?? key;
  const showConf =
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    key !== "PENDING";

  return (
    <Badge variant={tone} className={cn("font-mono", className)}>
      {label}
      {showConf && (
        <span className="ml-1 opacity-70">
          {confidence!.toFixed(0)}%
        </span>
      )}
    </Badge>
  );
}
