"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowUpRight, Eye, Plus, Sparkles, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { SignalBadge } from "@/components/signal-badge";
import { TickerMultiSelect } from "@/components/ticker-multi-select";
import { toast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import { formatPrice } from "@/lib/format";
import { toApiTicker } from "@/lib/tickers";
import { useWatchlistStore, type WatchlistEntry } from "@/lib/watchlist-store";
import { cn } from "@/lib/utils";

function relativeTime(iso?: string | null): string {
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
  return new Date(iso).toLocaleDateString();
}

function WatchlistRow({
  entry,
  onAnalyze,
  onRemove,
}: {
  entry: WatchlistEntry;
  onAnalyze: () => void;
  onRemove: () => void;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
    >
      <Card
        className={cn(
          "group relative overflow-hidden rounded-xl transition-all",
          "hover:border-gold/30 hover:shadow-[0_0_24px_-12px_rgba(201,168,76,0.45)]",
        )}
      >
        <CardContent className="flex items-center gap-4 p-4">
          <Link
            href={`/analyze/${entry.ticker}?auto=1`}
            className="flex min-w-0 flex-1 items-center gap-4"
          >
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="font-mono text-base font-semibold tracking-tight text-foreground transition-colors group-hover:text-gold">
                {entry.ticker}
              </span>
              <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                {entry.market} · added {relativeTime(entry.addedAt)}
              </span>
            </div>

            <div className="hidden min-w-[100px] flex-col items-start gap-0.5 sm:flex">
              <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                Price
              </span>
              <span className="font-mono text-sm tabular-nums">
                {entry.lastPrice !== undefined
                  ? formatPrice(entry.lastPrice, entry.market)
                  : "—"}
              </span>
            </div>

            <div className="hidden min-w-[140px] flex-col items-start gap-0.5 md:flex">
              <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                Signal
              </span>
              <SignalBadge
                signal={entry.lastSignal ?? null}
                confidence={entry.lastConfidence ?? null}
              />
            </div>

            <div className="hidden min-w-[120px] flex-col items-start gap-0.5 lg:flex">
              <span className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                Last analysis
              </span>
              <span className="font-mono text-xs tabular-nums">
                {relativeTime(entry.lastAnalysisAt)}
              </span>
            </div>
          </Link>

          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="gold"
              size="sm"
              className="rounded-xl"
              onClick={(e) => {
                e.preventDefault();
                onAnalyze();
              }}
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Analyze</span>
            </Button>
            {entry.lastRunId && (
              <Button
                asChild
                variant="ghost"
                size="sm"
                className="rounded-xl"
              >
                <Link href={`/runs/${entry.lastRunId}`} className="gap-1">
                  Trace <ArrowUpRight className="h-3 w-3" />
                </Link>
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="rounded-xl text-muted-foreground hover:text-sell"
              onClick={(e) => {
                e.preventDefault();
                onRemove();
              }}
              title="Remove"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function WatchlistView() {
  const router = useRouter();
  const qc = useQueryClient();

  const items = useWatchlistStore((s) => s.items);
  const add = useWatchlistStore((s) => s.add);
  const remove = useWatchlistStore((s) => s.remove);

  const [pickerOpen, setPickerOpen] = React.useState(false);

  const handleAdd = async (symbols: string[]) => {
    setPickerOpen(false);
    for (const sym of symbols) {
      add({ ticker: sym, market: "IN" });
      try {
        await api.addToWatchlist({ ticker: toApiTicker(sym, "IN"), market: "IN" });
      } catch {
        // best-effort sync
      }
    }
    qc.invalidateQueries({ queryKey: queryKeys.watchlist });
    toast.success(
      `Added ${symbols.length} to Watchlist`,
      symbols.join(", "),
    );
  };

  const handleRemove = async (ticker: string) => {
    remove(ticker);
    toast.info(`Removed ${ticker} from Watchlist`);
    try {
      await api.removeFromWatchlist(toApiTicker(ticker, "IN"), "IN");
    } catch {
      // backend DELETE may not be wired — local store is source of truth
    }
    qc.invalidateQueries({ queryKey: queryKeys.watchlist });
  };

  const handleAnalyze = (ticker: string) => {
    router.push(`/analyze/${ticker}?auto=1`);
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Watchlist"
        title="Your watchlist"
        description="Tickers you want to keep an eye on. Click any row to open the full analysis, or fire off a fresh run on demand."
        actions={
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

      {items.length === 0 ? (
        <EmptyState
          icon={Eye}
          title="No tickers yet"
          description="Add a symbol from the Analyze page or with the button above."
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
        <div className="flex flex-col gap-2">
          <AnimatePresence mode="popLayout">
            {items.map((entry) => (
              <WatchlistRow
                key={entry.ticker}
                entry={entry}
                onAnalyze={() => handleAnalyze(entry.ticker)}
                onRemove={() => handleRemove(entry.ticker)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      <TickerMultiSelect
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={handleAdd}
        alreadyAdded={items.map((i) => i.ticker)}
        maxSelect={5}
        title="Add to Watchlist"
        description="Pick up to 5 symbols to follow."
      />
    </div>
  );
}
