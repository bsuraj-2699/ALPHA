"use client";

import { Gavel, TrendingDown, TrendingUp } from "lucide-react";

import { GlassCard } from "./primitives";

type Dict = Record<string, unknown> | null;

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}
function list(v: unknown): string[] {
  return Array.isArray(v) ? (v.filter((x) => typeof x === "string") as string[]) : [];
}
function conf(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

function CaseCard({
  side,
  data,
}: {
  side: "bull" | "bear";
  data: Dict;
}) {
  const isBull = side === "bull";
  const color = isBull ? "var(--buy)" : "var(--sell)";
  const thesis = str(data?.thesis) ?? str(data?.narrative);
  const supports = list(data?.key_supports).length
    ? list(data?.key_supports)
    : list(data?.key_points);
  const c = conf(data?.confidence);

  return (
    <GlassCard tilt className="p-4" glow={undefined}>
      <div className="flex items-center gap-2">
        <span
          className="grid h-7 w-7 place-items-center rounded-lg"
          style={{ background: `color-mix(in oklab, ${color} 16%, transparent)`, color }}
        >
          {isBull ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
        </span>
        <h4 className="text-sm font-semibold" style={{ color }}>
          {isBull ? "Bull Case" : "Bear Case"}
        </h4>
        {c != null && (
          <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
            {(c * 100).toFixed(0)}% conviction
          </span>
        )}
      </div>
      {thesis ? (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{thesis}</p>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground/60">No case generated.</p>
      )}
      {supports.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {supports.slice(0, 5).map((s, i) => (
            <li key={i} className="flex gap-2 text-xs text-foreground/85">
              <span className="mt-1 h-1 w-1 shrink-0 rounded-full" style={{ background: color }} />
              {s}
            </li>
          ))}
        </ul>
      )}
    </GlassCard>
  );
}

export function DebatePanel({ bull, bear }: { bull: Dict; bear: Dict }) {
  if (!bull && !bear) return null;
  return (
    <div>
      <h3 className="mb-3 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
        Bull vs Bear
      </h3>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <CaseCard side="bull" data={bull} />
        <CaseCard side="bear" data={bear} />
      </div>
    </div>
  );
}

export function JudgePanel({ judgment }: { judgment: Dict }) {
  if (!judgment) return null;
  const narrative = str(judgment.narrative);
  const cited = list(judgment.cited_rule_ids);
  if (!narrative && cited.length === 0) return null;

  return (
    <GlassCard className="p-5">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-gold/15 text-gold">
          <Gavel className="h-4 w-4" />
        </span>
        <h3 className="text-sm font-semibold text-foreground">Judge Synthesis</h3>
        <span className="ml-auto text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          Narrative only
        </span>
      </div>
      {narrative && (
        <p className="mt-3 text-sm leading-relaxed text-foreground/90">{narrative}</p>
      )}
      {cited.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {cited.map((r) => (
            <span
              key={r}
              className="rounded-md border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
            >
              {r}
            </span>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
