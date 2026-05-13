"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUpRight, Plus, RefreshCcw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { SignalBadge } from "@/components/signal-badge";
import { TickerMultiSelect } from "@/components/ticker-multi-select";
import { toast } from "@/components/ui/toast";
import {
  STRATEGY_META,
  STRATEGY_MODES,
  parseStrategyMode,
  type StrategyMode,
} from "@/lib/strategy";
import { useStrategyBucket } from "@/lib/run-queue";
import { useStrategyStore } from "@/lib/strategy-store";
import { cn } from "@/lib/utils";
import { History } from "lucide-react";

const MAX_BUCKET_SIZE = 5;

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "—";
  const diff = Math.max(0, Date.now() - ts);
  const secs = Math.round(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(iso).toLocaleString();
}

function ModeTabs({
  mode,
  onChange,
}: {
  mode: StrategyMode;
  onChange: (m: StrategyMode) => void;
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-border bg-card/40 p-1">
      {STRATEGY_MODES.map((m) => {
        const isActive = m === mode;
        return (
          <button
            key={m}
            type="button"
            onClick={() => onChange(m)}
            className={cn(
              "relative rounded-lg px-3 py-1.5 text-xs font-medium uppercase tracking-[0.12em] transition-colors",
              isActive
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {isActive && (
              <motion.span
                layoutId="strategy-tab-active"
                className="absolute inset-0 rounded-lg bg-gold/15 ring-1 ring-inset ring-gold/40"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
            <span className="relative z-10">{STRATEGY_META[m].label}</span>
          </button>
        );
      })}
    </div>
  );
}

function TickerCard({
  ticker,
  signal,
  confidence,
  lastUpdatedAt,
  status,
  runId,
  mode,
  onRerun,
  onRemove,
  busy,
}: {
  ticker: string;
  signal: ReturnType<typeof useStrategyBucket>["rows"][number]["signal"];
  confidence: number | null;
  lastUpdatedAt: string | null;
  status: ReturnType<typeof useStrategyBucket>["rows"][number]["status"];
  runId: string | null;
  mode: StrategyMode;
  onRerun: () => void;
  onRemove: () => void;
  busy: boolean;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
    >
      <Card className="group relative h-full overflow-hidden rounded-xl transition-all hover:border-gold/30 hover:shadow-[0_0_24px_-12px_rgba(201,168,76,0.45)]">
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex flex-col gap-0.5">
              <Link
                href={`/analyze/${ticker}?auto=1`}
                className="font-mono text-base font-semibold tracking-tight text-foreground transition-colors hover:text-gold"
              >
                {ticker}
              </Link>
              <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                {STRATEGY_META[mode].label}
              </span>
            </div>
            <SignalBadge signal={signal} confidence={confidence} />
          </div>

          <div className="flex items-center justify-between rounded-lg bg-muted/30 px-3 py-2 ring-1 ring-inset ring-border">
            <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Last updated
            </span>
            <span className="font-mono text-xs tabular-nums text-foreground">
              {relativeTime(lastUpdatedAt)}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <span
              className={cn(
                "text-[10px] uppercase tracking-[0.16em]",
                status === "running" || status === "pending"
                  ? "text-warn"
                  : status === "error"
                    ? "text-sell"
                    : status === "complete"
                      ? "text-buy"
                      : "text-muted-foreground",
              )}
            >
              {status}
            </span>
            <div className="flex items-center gap-1">
              {runId && (
                <Button
                  asChild
                  variant="ghost"
                  size="sm"
                  className="h-7 rounded-lg px-2 text-xs"
                >
                  <Link href={`/runs/${runId}`} className="gap-1">
                    Trace <ArrowUpRight className="h-3 w-3" />
                  </Link>
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={onRerun}
                disabled={busy}
                className="h-7 rounded-lg px-2 text-xs"
                title="Re-run analysis"
              >
                <RefreshCcw className={cn("h-3 w-3", busy && "animate-spin")} />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={onRemove}
                className="h-7 rounded-lg px-2 text-xs text-muted-foreground hover:text-sell"
                title="Remove from bucket"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function StrategyRunsView() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialMode = parseStrategyMode(searchParams.get("mode"));
  const [mode, setMode] = React.useState<StrategyMode>(initialMode);
  const [pickerOpen, setPickerOpen] = React.useState(false);

  // Reflect tab changes into the URL so refresh / share keeps the bucket.
  React.useEffect(() => {
    const current = searchParams.get("mode");
    if (current !== mode) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("mode", mode);
      router.replace(`/runs?${params.toString()}`, { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const tickers = useStrategyStore((s) => s.buckets[mode]);
  const addToBucket = useStrategyStore((s) => s.addToBucket);
  const removeFromBucket = useStrategyStore((s) => s.removeFromBucket);

  const { rows, refreshAll, startTicker } = useStrategyBucket(mode);
  const [busyTicker, setBusyTicker] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const handleAdd = async (symbols: string[]) => {
    const remaining = MAX_BUCKET_SIZE - tickers.length;
    const accepted = symbols.slice(0, Math.max(0, remaining));
    if (accepted.length === 0) {
      toast.warn(`Bucket full`, `${STRATEGY_META[mode].label} caps at ${MAX_BUCKET_SIZE} tickers.`);
      setPickerOpen(false);
      return;
    }
    addToBucket(mode, accepted);
    setPickerOpen(false);
    toast.success(
      `Added ${accepted.length} ticker${accepted.length === 1 ? "" : "s"} to ${STRATEGY_META[mode].label}`,
      accepted.join(", "),
    );
  };

  const handleRerun = async (ticker: string) => {
    setBusyTicker(ticker);
    try {
      await startTicker(ticker);
      toast.info(`Re-ran ${ticker}`);
    } finally {
      setBusyTicker(null);
    }
  };

  const handleRefreshAll = async () => {
    setRefreshing(true);
    try {
      await refreshAll();
      toast.info(`Refreshed ${STRATEGY_META[mode].label}`);
    } finally {
      setRefreshing(false);
    }
  };

  const handleRemove = (ticker: string) => {
    removeFromBucket(mode, ticker);
    toast.info(`Removed ${ticker}`);
  };

  const meta = STRATEGY_META[mode];
  const bucketFull = tickers.length >= MAX_BUCKET_SIZE;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Runs"
        title="Run queue"
        description="Pick a strategy bucket and the server-side scheduler keeps its members fresh — intraday refreshes every 5 minutes during NSE hours, short term and long term run once per business day at 10:00 IST. Click any ticker for the full trace."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="rounded-xl"
              onClick={handleRefreshAll}
              disabled={refreshing || tickers.length === 0}
            >
              <RefreshCcw
                className={cn("h-3.5 w-3.5", refreshing && "animate-spin")}
              />
              Refresh
            </Button>
            <Button
              variant="gold"
              size="sm"
              className="rounded-xl"
              onClick={() => setPickerOpen(true)}
              disabled={bucketFull}
              title={
                bucketFull
                  ? `Bucket holds at most ${MAX_BUCKET_SIZE} tickers`
                  : undefined
              }
            >
              <Plus className="h-3.5 w-3.5" />
              Add ticker
            </Button>
          </div>
        }
      />

      <Card className="rounded-xl">
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-base">
              {meta.label}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                ({tickers.length}/{MAX_BUCKET_SIZE})
              </span>
            </CardTitle>
            <CardDescription className="text-xs">
              {meta.description}
            </CardDescription>
          </div>
          <ModeTabs mode={mode} onChange={setMode} />
        </CardHeader>
        <CardContent className="pt-0">
          {rows.length === 0 ? (
            <EmptyState
              icon={History}
              title="Bucket is empty"
              description={`Click “Add ticker” to enroll up to ${MAX_BUCKET_SIZE} symbols. ${
                mode === "intraday"
                  ? "The intraday scheduler will refresh them every 5 minutes during NSE hours."
                  : "The daily scheduler will refresh them at 10:00 IST every business day."
              }`}
              action={
                <Button
                  variant="gold"
                  size="sm"
                  className="rounded-xl"
                  onClick={() => setPickerOpen(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add ticker
                </Button>
              }
            />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <AnimatePresence mode="popLayout">
                {rows.map((row) => (
                  <TickerCard
                    key={row.ticker}
                    ticker={row.ticker}
                    signal={row.signal}
                    confidence={row.confidence}
                    lastUpdatedAt={row.lastUpdatedAt}
                    status={row.status}
                    runId={row.runId}
                    mode={mode}
                    onRerun={() => handleRerun(row.ticker)}
                    onRemove={() => handleRemove(row.ticker)}
                    busy={busyTicker === row.ticker}
                  />
                ))}
              </AnimatePresence>
            </div>
          )}
        </CardContent>
      </Card>

      <TickerMultiSelect
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={handleAdd}
        alreadyAdded={tickers}
        maxSelect={Math.max(1, MAX_BUCKET_SIZE - tickers.length)}
        title={`Add to ${meta.label}`}
        description={`Pick up to ${Math.max(1, MAX_BUCKET_SIZE - tickers.length)} symbols. Bucket caps at ${MAX_BUCKET_SIZE} total.`}
      />
    </div>
  );
}
