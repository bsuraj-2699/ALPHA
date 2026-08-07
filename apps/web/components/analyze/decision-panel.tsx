"use client";

import { motion } from "framer-motion";
import { ShieldAlert } from "lucide-react";

import type { Decision } from "@/types/api";
import type { EvaluationLike } from "@/lib/use-analysis";
import { formatPrice } from "@/lib/format";
import { signalTheme } from "@/lib/signal";
import { cn } from "@/lib/utils";

import { GlassCard, Gauge, SignalOrb } from "./primitives";

function Level({
  label,
  value,
  market,
  accent,
}: {
  label: string;
  value: number | null | undefined;
  market: "IN" | "US";
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <div
        className="mt-1 font-mono text-sm font-semibold tabular-nums"
        style={{ color: accent }}
      >
        {value == null ? "—" : formatPrice(value, market)}
      </div>
    </div>
  );
}

export function DecisionPanel({
  decision,
  evaluation,
  loading,
}: {
  decision: Decision | null;
  evaluation: EvaluationLike | null;
  loading: boolean;
}) {
  const theme = signalTheme(decision?.signal);
  const confidence = decision?.confidence ?? 0;
  const composite =
    (evaluation?.composite_score as number | undefined) ??
    (decision as unknown as { composite_score?: number })?.composite_score ??
    null;
  const coverage = evaluation?.data_coverage_pct ?? null;
  const overrides = decision?.overrides_active ?? [];

  return (
    <GlassCard tilt strong glow={decision ? theme.glow : undefined} className="p-6">
      <div className="perspective">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
              Decision
            </div>
            <div className="mt-2 flex items-center gap-3">
              <motion.h2
                key={decision?.signal ?? "pending"}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="font-display text-4xl font-semibold leading-none"
                style={{ color: decision ? theme.color : undefined }}
              >
                {decision ? theme.label : loading ? "Analyzing…" : "—"}
              </motion.h2>
            </div>
            {decision && (
              <div className="mt-2 font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground">
                {decision.ticker} · {decision.market}
              </div>
            )}
          </div>

          <SignalOrb color={theme.color} active={!!decision} size={104} />
        </div>

        {/* Metrics row */}
        <div className="mt-6 flex flex-wrap items-center gap-6">
          <Gauge
            value={confidence}
            color={theme.color}
            label={`${confidence.toFixed(0)}%`}
            sublabel="Confidence"
          />
          <div className="flex flex-1 flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Composite
                </div>
                <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-foreground">
                  {composite == null ? "—" : `${composite.toFixed(1)}`}
                  <span className="ml-1 text-xs text-muted-foreground">/100</span>
                </div>
              </div>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Position
                </div>
                <div className="mt-1 font-mono text-lg font-semibold tabular-nums text-foreground">
                  {decision ? `${decision.position_size_pct.toFixed(1)}%` : "—"}
                </div>
              </div>
            </div>
            {coverage != null && (
              <div>
                <div className="mb-1 flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  <span>Data Coverage</span>
                  <span className="font-mono text-foreground">{coverage.toFixed(0)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <motion.div
                    className="h-full rounded-full"
                    style={{
                      background:
                        "linear-gradient(90deg, var(--accent-1), var(--accent-2))",
                    }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min(100, coverage)}%` }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Levels */}
        <div className="mt-5 grid grid-cols-3 gap-3">
          <Level label="Entry" value={decision?.entry_price} market={decision?.market ?? "IN"} />
          <Level
            label="Stop"
            value={decision?.stop_loss}
            market={decision?.market ?? "IN"}
            accent="var(--sell)"
          />
          <Level
            label="Target"
            value={decision?.target_price}
            market={decision?.market ?? "IN"}
            accent="var(--buy)"
          />
        </div>

        {overrides.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-warn" />
            {overrides.map((o) => (
              <span
                key={o}
                className="rounded-md border border-warn/30 bg-warn/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide text-warn"
              >
                {o}
              </span>
            ))}
          </div>
        )}

        {decision?.rationale && (
          <p className={cn("mt-4 text-sm leading-relaxed text-muted-foreground")}>
            {decision.rationale}
          </p>
        )}
      </div>
    </GlassCard>
  );
}
