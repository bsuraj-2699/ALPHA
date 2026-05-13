"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { History, RefreshCcw, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { WatchlistButton } from "@/components/watchlist-button";
import { toast } from "@/components/ui/toast";
import { useStartAnalysis, useRun } from "@/lib/queries";
import { useRunStream } from "@/lib/run-stream";
import { useUIStore } from "@/lib/store";
import { toApiTicker, toDisplayTicker } from "@/lib/tickers";
import { useWatchlistStore } from "@/lib/watchlist-store";
import type { Decision, Market } from "@/types/api";

import { DebatePanel } from "./debate-panel";
import { DecisionCard } from "./decision-card";
import { OverrideBanner } from "./override-banner";
import { PillarRadar } from "./pillar-radar";
import { PriceChart } from "./price-chart";
import { ReasoningStream } from "./reasoning-stream";
import { RecentList } from "./recent-list";
import { TickerForm } from "./ticker-form";

interface AnalyzeViewProps {
  initialTicker: string;
  initialMarket: Market;
  /** When true, fire `/api/analyze` automatically on mount. */
  autoStart?: boolean;
}

export function AnalyzeView({
  initialTicker,
  initialMarket,
  autoStart = false,
}: AnalyzeViewProps) {
  const router = useRouter();

  // Always render the display form — strip any leftover `.NS`.
  const initialDisplay = React.useMemo(
    () => toDisplayTicker(initialTicker),
    [initialTicker],
  );

  const [ticker, setTicker] = React.useState(initialDisplay);
  const [market, setMarket] = React.useState<Market>(initialMarket);
  const [runId, setRunId] = React.useState<string | null>(null);

  const startMutation = useStartAnalysis();
  const stream = useRunStream(runId);
  const detail = useRun(runId);

  const pushRecent = useUIStore((s) => s.pushRecentTicker);
  const decorateWatchlist = useWatchlistStore((s) => s.decorate);
  const watchlistHas = useWatchlistStore((s) => s.has);

  React.useEffect(() => {
    pushRecent(initialDisplay);
  }, [initialDisplay, pushRecent]);

  // When the URL ticker changes, sync state. (Browser back/forward, or
  // clicking a recent.)
  React.useEffect(() => {
    setTicker(initialDisplay);
    setMarket(initialMarket);
    setRunId(null);
  }, [initialDisplay, initialMarket]);

  // SSE may close without a parsed `decision` event (proxy quirks, etc.)
  // while GET /api/runs/{id} is already terminal — without the API check the
  // button stays on "Analyzing…". Treat either source as done. `useRunStream`
  // resets on `runId` change in a layout effect so a prior "complete" does not
  // suppress loading for the next run after one extra render.
  const apiTerminal =
    detail.data?.status === "complete" ||
    detail.data?.status === "error" ||
    detail.data?.status === "interrupted";
  const streamTerminal =
    stream.status === "complete" ||
    stream.status === "error" ||
    stream.status === "interrupted";
  const isRunning =
    startMutation.isPending ||
    (Boolean(runId) && !apiTerminal && !streamTerminal);

  const handleAnalyze = React.useCallback(async () => {
    try {
      const apiTicker = toApiTicker(ticker, market);
      const res = await startMutation.mutateAsync({ ticker: apiTicker, market });
      setRunId(res.run_id);
    } catch {
      // Errors surface via the mutation's `error` field below.
    }
  }, [market, startMutation, ticker]);

  // Auto-start once on mount when `?auto=1` was on the URL.
  const autoStartedRef = React.useRef(false);
  React.useEffect(() => {
    if (!autoStart || autoStartedRef.current) return;
    if (!ticker || isRunning) return;
    autoStartedRef.current = true;
    void handleAnalyze();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, ticker]);

  // Live-or-loaded decision: prefer the SSE-derived value, fall back to
  // the API snapshot for navigations / refreshes.
  const decision: Decision | null = stream.decision ?? detail.data?.decision ?? null;

  // Mirror the freshest decision into the watchlist store so the
  // Watchlist tab always has the latest signal/price/timestamp without
  // a separate fetch.
  React.useEffect(() => {
    if (!decision) return;
    const display = toDisplayTicker(decision.ticker || ticker);
    if (!watchlistHas(display)) return;
    decorateWatchlist(display, {
      lastSignal: decision.signal,
      lastConfidence: decision.confidence,
      lastPrice: decision.entry_price ?? undefined,
      lastAnalysisAt: decision.timestamp,
      ...(runId !== null && { lastRunId: runId }),
    });
  }, [decision, runId, ticker, watchlistHas, decorateWatchlist]);

  // Toast on completion so users get a heads-up even when the page
  // is in the background.
  const completedRunRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (stream.status === "complete" && runId && completedRunRef.current !== runId) {
      completedRunRef.current = runId;
      toast.success(`Analysis refreshed for ${ticker}`);
    }
  }, [stream.status, runId, ticker]);

  const overrides = decision?.overrides_active ?? [];
  const bull = (detail.data?.bull_case ?? null) as Record<string, unknown> | null;
  const bear = (detail.data?.bear_case ?? null) as Record<string, unknown> | null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={`${market} · Analysis`}
        title={
          <span className="font-mono text-3xl tracking-tight md:text-4xl">
            {ticker}
          </span>
        }
        description="Five analysts, two debaters, one judge. Deterministic scoring, narrative-only LLMs."
        actions={
          <div className="flex items-center gap-2">
            <WatchlistButton
              ticker={ticker}
              market={market}
              decision={decision}
            />
            {runId && (
              <Button asChild variant="outline" size="sm" className="rounded-xl">
                <Link href={`/runs/${runId}`} className="gap-1.5">
                  <History className="h-3.5 w-3.5" />
                  Trace
                </Link>
              </Button>
            )}
            {runId && stream.status === "complete" && (
              <Button
                variant="ghost"
                size="sm"
                className="rounded-xl"
                onClick={() => {
                  completedRunRef.current = null;
                  void handleAnalyze();
                }}
                disabled={isRunning}
              >
                <RefreshCcw className="h-3.5 w-3.5" />
                Re-run
              </Button>
            )}
            <Button asChild variant="ghost" size="sm" className="rounded-xl">
              <Link href="/analyze" className="gap-1.5">
                <Search className="h-3.5 w-3.5" />
                Pick another
              </Link>
            </Button>
            {runId && stream.status === "complete" && (
              <Badge variant="buy">complete</Badge>
            )}
            {stream.status === "interrupted" && (
              <Badge variant="gold">awaiting review</Badge>
            )}
            {stream.status === "error" && <Badge variant="sell">error</Badge>}
          </div>
        }
      />

      <div className="flex flex-col gap-4 xl:flex-row">
        {/* LEFT: Ticker selector + recents */}
        <aside className="flex shrink-0 flex-col gap-4 xl:w-[280px]">
          <TickerForm
            ticker={ticker}
            market={market}
            isRunning={isRunning}
            onChange={({ ticker: t, market: m }) => {
              setTicker(toDisplayTicker(t));
              setMarket(m);
            }}
            onSubmit={() => {
              const display = toDisplayTicker(ticker);
              if (display !== initialDisplay || market !== initialMarket) {
                router.replace(`/analyze/${display}`);
              }
              handleAnalyze();
            }}
          />

          <RecentList activeTicker={ticker} />

          {startMutation.error && (
            <p className="px-1 text-xs text-sell">
              {startMutation.error.message}
            </p>
          )}
        </aside>

        {/* CENTER: Reasoning stream */}
        <main className="flex min-w-0 flex-1 flex-col gap-4">
          <motion.div layout className="min-h-[560px]">
            <ReasoningStream
              stream={stream}
              detail={detail.data}
              hasRun={runId !== null}
            />
          </motion.div>
        </main>

        {/* RIGHT: Decision + chart + radar */}
        <aside className="flex shrink-0 flex-col gap-4 xl:w-[380px]">
          <DecisionCard
            decision={decision}
            pending={isRunning && decision === null}
          />
          <PriceChart ticker={ticker} />
          <PillarRadar
            reports={detail.data?.analyst_reports}
            liveSlots={stream.agents}
          />
        </aside>
      </div>

      {/* BOTTOM: overrides + debate */}
      <div className="flex flex-col gap-4">
        {overrides.length > 0 && decision && (
          <OverrideBanner
            overrides={overrides}
            signal={decision.signal}
          />
        )}
        <DebatePanel
          bull={bull}
          bear={bear}
          pending={isRunning && bull === null && bear === null}
        />
      </div>
    </div>
  );
}
