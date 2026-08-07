"use client";

import { motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";

import type { Stage } from "@/lib/use-analysis";
import { cn } from "@/lib/utils";
import { scoreColor } from "@/lib/signal";

import { GlassCard } from "./primitives";

function StageRow({ stage }: { stage: Stage }) {
  const done = stage.state === "done";
  const active = stage.state === "active";
  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="relative grid h-6 w-6 shrink-0 place-items-center">
        {active && (
          <span className="absolute inset-0 rounded-full bg-accent1/25 animate-market-pulse" />
        )}
        <span
          className={cn(
            "grid h-6 w-6 place-items-center rounded-full border text-[10px]",
            done && "border-buy/40 bg-buy/15 text-buy",
            active && "border-accent1/50 bg-accent1/10 text-accent1",
            !done && !active && "border-white/10 bg-white/[0.03] text-muted-foreground",
          )}
        >
          {done ? (
            <Check className="h-3 w-3" />
          ) : active ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <span className="h-1.5 w-1.5 rounded-full bg-current opacity-50" />
          )}
        </span>
      </div>
      <span
        className={cn(
          "flex-1 text-sm transition-colors",
          done ? "text-foreground" : active ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {stage.label}
      </span>
      {stage.score != null && (
        <span
          className="font-mono text-xs font-semibold tabular-nums"
          style={{ color: scoreColor(stage.score) }}
        >
          {stage.score.toFixed(0)}
        </span>
      )}
    </div>
  );
}

export function LivePipeline({
  stages,
  running,
}: {
  stages: Stage[];
  running: boolean;
}) {
  const done = stages.filter((s) => s.state === "done").length;
  const groups: { key: Stage["kind"]; label: string }[] = [
    { key: "core", label: "Critical Path" },
    { key: "analyst", label: "Analysts" },
    { key: "synthesis", label: "Synthesis" },
  ];

  return (
    <GlassCard className="p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Reasoning Pipeline
        </h3>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {done}/{stages.length}
          </span>
          {running && (
            <span className="flex items-center gap-1 rounded-full border border-accent1/30 bg-accent1/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent1">
              <span className="h-1.5 w-1.5 rounded-full bg-accent1 animate-orb" />
              live
            </span>
          )}
        </div>
      </div>

      <motion.div layout className="flex flex-col gap-2">
        {groups.map((g) => {
          const items = stages.filter((s) => s.kind === g.key);
          if (items.length === 0) return null;
          return (
            <div key={g.key}>
              <div className="mb-1 mt-2 text-[9px] uppercase tracking-[0.24em] text-muted-foreground/70">
                {g.label}
              </div>
              {items.map((s) => (
                <StageRow key={s.id} stage={s} />
              ))}
            </div>
          );
        })}
      </motion.div>
    </GlassCard>
  );
}
