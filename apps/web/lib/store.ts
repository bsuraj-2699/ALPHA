"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * App-wide client state.
 *
 * Anything *server* (run state, decisions, prices, OHLC) belongs in
 * TanStack Query cache, not here. This store is for purely client-side
 * UI concerns: sidebar collapsed, recently-viewed tickers, the
 * preferred market filter, etc.
 */

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebar: (collapsed: boolean) => void;

  /** Last 10 tickers the user looked at — powers the dashboard quick-list. */
  recentTickers: string[];
  pushRecentTicker: (ticker: string) => void;

  /** Primary market the user trades from (used as a soft default). */
  primaryMarket: "IN" | "US";
  setPrimaryMarket: (m: "IN" | "US") => void;
}

const MAX_RECENTS = 10;

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebar: (sidebarCollapsed) => set({ sidebarCollapsed }),

      recentTickers: [],
      pushRecentTicker: (ticker) =>
        set((s) => {
          const t = ticker.toUpperCase();
          const next = [t, ...s.recentTickers.filter((x) => x !== t)].slice(
            0,
            MAX_RECENTS,
          );
          return { recentTickers: next };
        }),

      primaryMarket: "US",
      setPrimaryMarket: (primaryMarket) => set({ primaryMarket }),
    }),
    {
      name: "fin-agent-ui",
      // We don't ship a server snapshot of this state, so SSR is fine.
      skipHydration: false,
    },
  ),
);
