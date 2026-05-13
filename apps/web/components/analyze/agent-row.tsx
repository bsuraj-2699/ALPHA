"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useTypewriter } from "@/lib/use-count-up";
import type { AgentSlot } from "@/lib/run-stream";
import type { AnalystReport } from "@/types/api";

interface AgentRowProps {
  slot: AgentSlot;
  /** When this slot is an analyst, the corresponding report from the run */
  report?: AnalystReport | null;
  /** Whether this row is currently expanded */
  expanded: boolean;
  onToggle: () => void;
}

function StatusDot({ status }: { status: AgentSlot["status"] }) {
  const cls =
    status === "running"
      ? "bg-warn shadow-[0_0_8px_var(--neutral)]"
      : status === "complete"
        ? "bg-buy shadow-[0_0_8px_rgba(0,229,160,0.7)]"
        : status === "error"
          ? "bg-sell"
          : "bg-muted-foreground/40";

  return (
    <span className="relative inline-flex h-2 w-2 items-center justify-center">
      {status === "running" && (
        <span className="absolute inset-0 rounded-full bg-warn/60 animate-market-pulse" />
      )}
      <span className={cn("relative inline-block h-2 w-2 rounded-full", cls)} />
    </span>
  );
}

function pillarScoreFromPayload(payload?: Record<string, unknown>): number | null {
  if (!payload) return null;
  const v = payload["score"];
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  return null;
}

function pillarColor(score: number | null): "buy" | "sell" | "warn" | "gold" {
  if (score === null) return "gold";
  if (score >= 70) return "buy";
  if (score >= 50) return "warn";
  return "sell";
}

export function AgentRow({ slot, report, expanded, onToggle }: AgentRowProps) {
  const { meta, status, summary, durationMs, reasoning, error } = slot;

  // Score precedence: SSE payload (live) > report.score (loaded from API)
  const score =
    pillarScoreFromPayload(slot.payload) ??
    (report?.score ?? null);

  // While the row is "running" we render a typewriter against the latest
  // streaming reasoning text — typically empty until the `thinking` event
  // arrives, at which point we reveal the full output character-by-character.
  const sourceText = reasoning ?? "";
  const typed = useTypewriter(
    status === "running" ? sourceText : "",
    140,
  );

  const showCursor = status === "running";

  return (
    <motion.div
      layout
      transition={{ type: "spring", stiffness: 320, damping: 36 }}
      className={cn(
        "rounded-lg border border-border bg-card/60 transition-colors",
        status === "running" && "border-warn/40",
        status === "error" && "border-sell/50",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {/* Avatar */}
        <div
          className={cn(
            "relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-foreground/90",
            status === "pending" && "opacity-40",
          )}
          style={{ background: meta.avatar }}
        >
          {meta.initial}
          {status === "running" && (
            <span className="absolute inset-0 -m-0.5 rounded-full ring-2 ring-warn/50 animate-pulse" />
          )}
          {status === "complete" && (
            <span className="absolute inset-0 -m-0.5 rounded-full ring-1 ring-buy/40" />
          )}
        </div>

        {/* Body */}
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <span className="font-display text-sm font-semibold text-foreground">
              {meta.displayName}
            </span>
            <StatusDot status={status} />
            {status === "complete" && typeof durationMs === "number" && (
              <span className="font-mono text-[10px] text-muted-foreground">
                {durationMs}ms
              </span>
            )}
          </div>

          {/* Status line beneath the title */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {status === "pending" && <span>queued</span>}

            {status === "running" && (
              <span className="line-clamp-1">
                {typed || "thinking…"}
                {showCursor && (
                  <span className="ml-0.5 inline-block h-3 w-[2px] translate-y-0.5 animate-pulse bg-warn align-middle" />
                )}
              </span>
            )}

            {status === "complete" && (
              <span className="line-clamp-1">
                {summary || meta.blurb}
              </span>
            )}

            {status === "error" && (
              <span className="line-clamp-1 text-sell">
                <AlertTriangle className="mr-1 inline h-3 w-3" />
                {error ?? "error"}
              </span>
            )}
          </div>
        </div>

        {/* Score / chevron */}
        <div className="flex shrink-0 items-center gap-2">
          {meta.hasPillarScore && score !== null && (
            <Badge variant={pillarColor(score)} className="font-mono">
              {score.toFixed(1)}
            </Badge>
          )}
          <motion.span
            animate={{ rotate: expanded ? 180 : 0 }}
            transition={{ duration: 0.18 }}
            className="text-muted-foreground"
          >
            <ChevronDown className="h-4 w-4" />
          </motion.span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="border-t border-border px-4 py-3 text-sm">
              <p className="leading-relaxed text-foreground/85">
                {reasoning ||
                  report?.narrative ||
                  meta.blurb}
              </p>

              {report?.top_signals && report.top_signals.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {report.top_signals.slice(0, 6).map((s) => (
                    <Badge
                      key={s}
                      variant="muted"
                      className="font-mono normal-case tracking-normal"
                    >
                      {s}
                    </Badge>
                  ))}
                </div>
              )}

              {report?.citations && report.citations.length > 0 && (
                <div className="mt-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                    Cited rules
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {report.citations.map((id) => (
                      <span
                        key={id}
                        className="rounded bg-muted/60 px-1.5 py-0.5 font-mono text-[11px] text-foreground/80"
                      >
                        {id}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
