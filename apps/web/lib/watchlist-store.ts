"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { toDisplayTicker } from "@/lib/tickers";
import type { Market, Signal } from "@/types/api";

/**
 * Local watchlist mirror.
 *
 * The FastAPI backend already exposes GET/POST /api/watchlist (see
 * `apps/api/routes/watchlist.py`), but the in-memory store there
 * doesn't survive a server restart and there's no DELETE yet. We keep
 * a parallel localStorage-backed copy as the UI's source of truth and
 * write through to the API as a best-effort sync.
 *
 * Latest price / signal / analysis time are decorated locally as runs
 * complete so the Watchlist tab can render an at-a-glance grid.
 */

export interface WatchlistEntry {
  ticker: string; // display form, no .NS
  market: Market;
  addedAt: string; // ISO
  lastSignal?: Signal;
  lastConfidence?: number;
  lastPrice?: number;
  lastAnalysisAt?: string; // ISO
  lastRunId?: string;
}

interface WatchlistState {
  items: WatchlistEntry[];

  add: (entry: { ticker: string; market: Market }) => WatchlistEntry;
  remove: (ticker: string) => void;
  has: (ticker: string) => boolean;
  decorate: (ticker: string, patch: Partial<WatchlistEntry>) => void;
}

export const useWatchlistStore = create<WatchlistState>()(
  persist(
    (set, get) => ({
      items: [],

      add: ({ ticker, market }) => {
        const display = toDisplayTicker(ticker);
        const existing = get().items.find((i) => i.ticker === display);
        if (existing) return existing;
        const entry: WatchlistEntry = {
          ticker: display,
          market,
          addedAt: new Date().toISOString(),
        };
        set((s) => ({ items: [entry, ...s.items] }));
        return entry;
      },

      remove: (ticker) => {
        const display = toDisplayTicker(ticker);
        set((s) => ({ items: s.items.filter((i) => i.ticker !== display) }));
      },

      has: (ticker) => {
        const display = toDisplayTicker(ticker);
        return get().items.some((i) => i.ticker === display);
      },

      decorate: (ticker, patch) =>
        set((s) => {
          const display = toDisplayTicker(ticker);
          return {
            items: s.items.map((i) =>
              i.ticker === display ? { ...i, ...patch } : i,
            ),
          };
        }),
    }),
    {
      name: "fin-agent-watchlist",
    },
  ),
);
