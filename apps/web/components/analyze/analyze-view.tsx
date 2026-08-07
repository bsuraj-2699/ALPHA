"use client";

import * as React from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { History } from "lucide-react";

import { api } from "@/lib/api";
import { useAnalysis } from "@/lib/use-analysis";
import { useUIStore } from "@/lib/store";
import { lookupTickerName, toDisplayTicker } from "@/lib/tickers";
import { WatchlistButton } from "@/components/watchlist-button";
import type { Market } from "@/types/api";

import { AnalystGrid } from "./analyst-grid";
import { DecisionPanel } from "./decision-panel";
import { LivePipeline } from "./live-pipeline";
import { PillarScores } from "./pillar-scores";
import { PriceChart } from "./price-chart";
import { DebatePanel, JudgePanel } from "./synthesis-panels";
import { TickerForm } from "./ticker-form";

interface AnalyzeViewProps {
  initialTicker: string;
  initialMarket: Market;
  autoStart?: boolean;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; dot: string }> = {
    complete: { label: "Complete", cls: "border-buy/30 bg-buy/10 text-buy", dot: "bg-buy" },
    running: { label: "Analyzing", cls: "border-accent1/30 bg-accent1/10 text-accent1", dot: "bg-accent1" },
    pending: { label: "Queued", cls: "border-white/10 bg-white/[0.04] text-muted-foreground", dot: "bg-muted-foreground" },
    interrupted: { label: "Awaiting review", cls: "border-gold/30 bg-gold/10 text-gold", dot: "bg-gold" },
    error: { label: "Error", cls: "border-sell/30 bg-sell/10 text-sell", dot: "bg-sell" },
    idle: { label: "Idle", cls: "border-white/10 bg-white/[0.03] text-muted-foreground", dot: "bg-muted-foreground" },
  };
  const s = map[status] ?? map.idle;
  return (
    <span className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] uppercase tracking-wide ${s.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot} ${status === "running" ? "animate-orb" : ""}`} />
      {s.label}
    </span>
  );
}

export function AnalyzeView({
  initialTicker,
  initialMarket,
  autoStart = true,
}: AnalyzeViewProps) {
  const display = React.useMemo(() => toDisplayTicker(initialTicker), [initialTicker]);
  const pushRecent = useUIStore((s) => s.pushRecentTicker);

  React.useEffect(() => {
    if (display) pushRecent(display);
  }, [display, pushRecent]);

  const a = useAnalysis({
    ticker: display,
    market: initialMarket,
    autoStart,
  });

  const approve = React.useCallback(
    async (response: string) => {
      if (!a.runId) return;
      await api.approveRun(a.runId, { response });
      a.resume();
    },
    [a],
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.3em] text-muted-foreground">
            {initialMarket} · Analysis
          </div>
          <div className="mt-1 flex items-center gap-3">
            <motion.h1
              key={display}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="font-display text-4xl font-semibold tracking-tight md:text-5xl"
            >
              <span className="text-gradient">{display}</span>
            </motion.h1>
            <StatusBadge status={a.status} />
          </div>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            {lookupTickerName(display)} — five analysts, two debaters, one judge.
            Deterministic scoring, narrative-only LLMs.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <WatchlistButton ticker={display} market={initialMarket} decision={a.decision} />
          {a.runId && (
            <Link
              href={`/runs/${a.runId}`}
              className="flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <History className="h-3.5 w-3.5" />
              Trace
            </Link>
          )}
        </div>
      </div>

      {a.status === "interrupted" && (
        <div className="glass rounded-2xl border border-gold/30 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-gold">Human review required</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                A strong signal needs approval before it is finalized.
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => approve("approve")}
                className="rounded-lg border border-buy/40 bg-buy/10 px-3 py-1.5 text-xs font-medium text-buy hover:bg-buy/20"
              >
                Approve
              </button>
              <button
                onClick={() => approve("reject")}
                className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
              >
                Downgrade to Hold
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main grid */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
        {/* Left rail */}
        <aside className="flex flex-col gap-5 xl:sticky xl:top-6 xl:self-start">
          <TickerForm current={display} running={a.isRunning} onRerun={a.restart} />
          <LivePipeline stages={a.stages} running={a.isRunning} />
        </aside>

        {/* Content */}
        <div className="flex min-w-0 flex-col gap-5">
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DecisionPanel
              decision={a.decision}
              evaluation={a.evaluation}
              loading={a.isRunning}
            />
            <PriceChart ticker={display} />
          </div>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
            <PillarScores evaluation={a.evaluation} loading={a.isRunning} />
            <div className="flex flex-col gap-5">
              <AnalystGrid reports={a.analystReports} />
            </div>
          </div>

          <DebatePanel bull={a.bullCase} bear={a.bearCase} />
          <JudgePanel judgment={a.judgment} />

          {a.error && (
            <div className="glass rounded-2xl border border-sell/30 p-4 text-sm text-sell">
              {a.error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
