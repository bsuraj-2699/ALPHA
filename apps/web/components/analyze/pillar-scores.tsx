"use client";

import { motion } from "framer-motion";

import type { EvaluationLike } from "@/lib/use-analysis";
import { pillarLabel, scoreColor } from "@/lib/signal";

import { GlassCard } from "./primitives";

export function PillarScores({
  evaluation,
  loading,
}: {
  evaluation: EvaluationLike | null;
  loading: boolean;
}) {
  const scores = evaluation?.pillar_scores ?? {};
  const entries = Object.entries(scores).filter(
    ([, v]) => typeof v === "number",
  ) as [string, number][];
  entries.sort((a, b) => b[1] - a[1]);

  return (
    <GlassCard className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Pillar Scores
        </h3>
        <span className="text-[10px] text-muted-foreground">0 – 100</span>
      </div>

      {entries.length === 0 ? (
        <div className="py-8 text-center text-xs text-muted-foreground">
          {loading ? "Scoring pillars…" : "No pillar scores yet."}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {entries.map(([key, value], i) => {
            const color = scoreColor(value);
            return (
              <div key={key}>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs text-foreground/90">{pillarLabel(key)}</span>
                  <span
                    className="font-mono text-xs font-semibold tabular-nums"
                    style={{ color }}
                  >
                    {value.toFixed(0)}
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/[0.05]">
                  <motion.div
                    className="h-full rounded-full"
                    style={{
                      background: `linear-gradient(90deg, color-mix(in oklab, ${color} 55%, transparent), ${color})`,
                      boxShadow: `0 0 12px -2px ${color}`,
                    }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max(2, Math.min(100, value))}%` }}
                    transition={{ duration: 0.8, ease: "easeOut", delay: i * 0.05 }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
