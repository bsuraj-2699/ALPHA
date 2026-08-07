"use client";

import { motion } from "framer-motion";

import type { AnalystReport } from "@/types/api";
import { pillarLabel, scoreColor } from "@/lib/signal";

import { GlassCard } from "./primitives";

const ORDER = ["fundamentals", "technicals", "sentiment", "macro", "risk"];

function ReportCard({ id, report, i }: { id: string; report: AnalystReport; i: number }) {
  const color = scoreColor(report.score);
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: i * 0.06 }}
    >
      <GlassCard tilt className="h-full p-4">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold text-foreground">{pillarLabel(id)}</h4>
          <div className="flex items-center gap-1.5">
            <span
              className="grid h-8 w-8 place-items-center rounded-lg font-mono text-xs font-bold tabular-nums"
              style={{
                color,
                background: `color-mix(in oklab, ${color} 14%, transparent)`,
                boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${color} 35%, transparent)`,
              }}
            >
              {report.score.toFixed(0)}
            </span>
          </div>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {report.narrative}
        </p>
        {report.top_signals && report.top_signals.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {report.top_signals.slice(0, 4).map((s, k) => (
              <span
                key={k}
                className="rounded-md border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-foreground/80"
              >
                {s}
              </span>
            ))}
          </div>
        )}
      </GlassCard>
    </motion.div>
  );
}

export function AnalystGrid({
  reports,
}: {
  reports: Record<string, AnalystReport>;
}) {
  const keys = Object.keys(reports);
  if (keys.length === 0) return null;
  keys.sort((a, b) => {
    const ia = ORDER.indexOf(a);
    const ib = ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });

  return (
    <div>
      <h3 className="mb-3 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
        Analyst Narratives
      </h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {keys.map((k, i) => (
          <ReportCard key={k} id={k} report={reports[k]} i={i} />
        ))}
      </div>
    </div>
  );
}
