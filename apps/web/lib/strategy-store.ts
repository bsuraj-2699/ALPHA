"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { api, ApiError } from "@/lib/api";
import type { StrategyMode } from "@/lib/strategy";
import { toDisplayTicker } from "@/lib/tickers";

/**
 * Strategy buckets persist the user's "what should the auto-runner be
 * watching for me right now" decision across reloads.
 *
 * Two layers of persistence:
 *   * Client localStorage (zustand `persist`) keeps the UI snappy and
 *     usable even when the API is offline.
 *   * Best-effort write-through to `POST /api/buckets/{mode}` so the
 *     server-side scheduler (`apps/api/scheduler.py`) can keep the
 *     intraday and daily runs flowing without a browser tab open.
 *
 * Symbols are stored in display form (no `.NS` suffix) — convert at the
 * API boundary.
 */

interface StrategyBucketState {
  buckets: Record<StrategyMode, string[]>;
  /**
   * Last `run_id` we kicked off for `(mode, ticker)`. Lets the Runs UI
   * resolve the latest run without re-POSTing to /analyze on every
   * navigation.
   */
  lastRunIds: Record<string, string>;
  /** True once we've reconciled localStorage with the server at least once. */
  hydrated: boolean;

  addToBucket: (mode: StrategyMode, tickers: string[]) => void;
  removeFromBucket: (mode: StrategyMode, ticker: string) => void;
  replaceBucket: (mode: StrategyMode, tickers: string[]) => void;
  setLastRunId: (mode: StrategyMode, ticker: string, runId: string) => void;
  getLastRunId: (mode: StrategyMode, ticker: string) => string | undefined;
  /**
   * Pull the canonical bucket lists from the server. Called from
   * `app/providers.tsx` on mount so a fresh tab inherits the schedule
   * the backend is already running. Falls back to whatever's in
   * localStorage on network errors.
   */
  syncFromServer: () => Promise<void>;
}

const KEY = (mode: StrategyMode, ticker: string): string =>
  `${mode}:${toDisplayTicker(ticker)}`;

const ALL_MODES: StrategyMode[] = ["intraday", "short_term", "long_term"];

function notProduction(): boolean {
  return process.env.NODE_ENV !== "production";
}

/** Best-effort write-through. Logs in dev; never throws. */
function pushBucket(mode: StrategyMode, tickers: string[]): void {
  void api.replaceBucket(mode, { tickers }).catch((err: unknown) => {
    if (notProduction()) {
      const status = err instanceof ApiError ? err.status : "n/a";
      console.warn(`[strategy-store] PUT /api/buckets/${mode} failed (${status})`, err);
    }
  });
}

export const useStrategyStore = create<StrategyBucketState>()(
  persist(
    (set, get) => ({
      buckets: {
        intraday: [],
        short_term: [],
        long_term: [],
      },
      lastRunIds: {},
      hydrated: false,

      addToBucket: (mode, tickers) => {
        let nextList: string[] = [];
        set((s) => {
          const next = new Set(s.buckets[mode].map((t) => toDisplayTicker(t)));
          for (const t of tickers) {
            const display = toDisplayTicker(t);
            if (display) next.add(display);
          }
          nextList = Array.from(next);
          return {
            buckets: { ...s.buckets, [mode]: nextList },
          };
        });
        pushBucket(mode, nextList);
      },

      removeFromBucket: (mode, ticker) => {
        const display = toDisplayTicker(ticker);
        let nextList: string[] = [];
        set((s) => {
          nextList = s.buckets[mode].filter(
            (t) => toDisplayTicker(t) !== display,
          );
          return {
            buckets: { ...s.buckets, [mode]: nextList },
          };
        });
        pushBucket(mode, nextList);
      },

      replaceBucket: (mode, tickers) => {
        const next = Array.from(
          new Set(
            tickers
              .map((t) => toDisplayTicker(t))
              .filter((t): t is string => Boolean(t)),
          ),
        );
        set((s) => ({ buckets: { ...s.buckets, [mode]: next } }));
        pushBucket(mode, next);
      },

      setLastRunId: (mode, ticker, runId) =>
        set((s) => ({
          lastRunIds: { ...s.lastRunIds, [KEY(mode, ticker)]: runId },
        })),

      getLastRunId: (mode, ticker) => get().lastRunIds[KEY(mode, ticker)],

      syncFromServer: async () => {
        try {
          const resp = await api.listBuckets();
          set((s) => {
            const merged = { ...s.buckets };
            for (const mode of ALL_MODES) {
              const fromServer = resp.buckets[mode] ?? [];
              merged[mode] = fromServer.map((t) => toDisplayTicker(t));
            }
            return { buckets: merged, hydrated: true };
          });
        } catch (err) {
          if (notProduction()) {
            console.warn("[strategy-store] GET /api/buckets failed", err);
          }
          set({ hydrated: true });
        }
      },
    }),
    {
      name: "fin-agent-strategy-buckets",
      // `hydrated` is a runtime flag — never restore the persisted value,
      // otherwise a stale `true` on the next load would skip the server sync.
      partialize: (s) => ({
        buckets: s.buckets,
        lastRunIds: s.lastRunIds,
      }),
    },
  ),
);
