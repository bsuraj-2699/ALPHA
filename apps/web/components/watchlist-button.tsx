"use client";

import * as React from "react";
import { Check, Eye, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { useQueryClient } from "@tanstack/react-query";
import { toApiTicker, toDisplayTicker } from "@/lib/tickers";
import { useWatchlistStore } from "@/lib/watchlist-store";
import type { Decision, Market } from "@/types/api";

interface WatchlistButtonProps {
  ticker: string;
  market: Market;
  /** Optional decision to seed the local entry with the most recent signal. */
  decision?: Decision | null;
  className?: string;
  size?: "sm" | "default" | "lg";
}

/**
 * "+ Add to Watchlist" toggle.
 *
 * Source of truth is the local Zustand+localStorage store; the API
 * call is fire-and-forget so a 500ms backend hiccup never blocks the
 * UI. Seeding `decision` lets the Watchlist tab show the latest
 * signal without re-fetching.
 */
export function WatchlistButton({
  ticker,
  market,
  decision,
  className,
  size = "sm",
}: WatchlistButtonProps) {
  const display = toDisplayTicker(ticker);
  const has = useWatchlistStore((s) => s.has(display));
  const add = useWatchlistStore((s) => s.add);
  const remove = useWatchlistStore((s) => s.remove);
  const decorate = useWatchlistStore((s) => s.decorate);
  const qc = useQueryClient();
  const [busy, setBusy] = React.useState(false);

  const handleClick = async () => {
    setBusy(true);
    try {
      if (has) {
        remove(display);
        toast.info(`Removed ${display} from Watchlist`);
        try {
          await api.removeFromWatchlist(toApiTicker(display, market), market);
        } catch {
          // Backend DELETE may not be wired yet — silent.
        }
        qc.invalidateQueries({ queryKey: queryKeys.watchlist });
        return;
      }

      add({ ticker: display, market });
      if (decision) {
        decorate(display, {
          lastSignal: decision.signal,
          lastConfidence: decision.confidence,
          lastPrice: decision.entry_price ?? undefined,
          lastAnalysisAt: decision.timestamp,
        });
      }
      toast.success(`Added ${display} to Watchlist`);

      try {
        await api.addToWatchlist({
          ticker: toApiTicker(display, market),
          market,
        });
      } catch {
        // Local store remains the source of truth; surface no UI error.
      }
      qc.invalidateQueries({ queryKey: queryKeys.watchlist });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      type="button"
      onClick={handleClick}
      variant={has ? "outline" : "gold"}
      size={size}
      disabled={busy}
      className={cn("rounded-xl", className)}
    >
      {has ? (
        <>
          <Check className="h-3.5 w-3.5" />
          In Watchlist
        </>
      ) : (
        <>
          <Plus className="h-3.5 w-3.5" />
          Add to Watchlist
        </>
      )}
      <Eye className="ml-0.5 h-3.5 w-3.5 opacity-60" />
    </Button>
  );
}
