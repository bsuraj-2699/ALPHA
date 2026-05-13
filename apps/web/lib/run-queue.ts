"use client";

import * as React from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { STRATEGY_META, type StrategyMode } from "@/lib/strategy";
import { useStrategyStore } from "@/lib/strategy-store";
import { toApiTicker, toDisplayTicker } from "@/lib/tickers";
import { useWatchlistStore } from "@/lib/watchlist-store";
import type { LatestRunResponse, RunDetail, Signal } from "@/types/api";

/**
 * Frontend orchestration for the strategy buckets.
 *
 * Backend story (now in place — see apps/api/scheduler.py):
 *   * The intraday scheduler re-runs every bucket member every 5 min
 *     during NSE hours.
 *   * The daily scheduler runs short_term + long_term once per business
 *     day at 10:00 IST.
 *   * `/api/runs/latest?ticker=…&mode=…` resolves the newest run for a
 *     bucket entry (in-flight or terminal).
 *
 * The frontend therefore does not POST `/api/analyze` on a timer
 * anymore — that was a no-op within the daily idempotency window. We
 * only:
 *   1. Kick a one-shot `/analyze` when a brand-new ticker enters the
 *      bucket (so the user sees an answer immediately rather than
 *      waiting for the next scheduler tick).
 *   2. Periodically poll `/api/runs/latest` so the card flips to the
 *      scheduler's freshly-dispatched run id.
 *   3. Poll `/api/runs/{id}` so the card content refreshes.
 *
 * `useStrategyBucket(mode)` is the single hook the Runs page consumes.
 */

export interface BucketRow {
  ticker: string; // display form
  runId: string | null;
  detail: RunDetail | null;
  signal: Signal | null;
  confidence: number | null;
  lastUpdatedAt: string | null;
  status: RunDetail["status"] | "idle";
}

interface UseStrategyBucketResult {
  rows: BucketRow[];
  refreshAll: () => Promise<void>;
  startTicker: (ticker: string) => Promise<string | null>;
}

const LATEST_RUN_POLL_MS = 60_000;

/** One-shot kick for newly added tickers — bypasses the scheduler delay. */
async function startAnalysis(
  ticker: string,
  mode: StrategyMode,
): Promise<string | null> {
  try {
    const res = await api.analyze({
      ticker: toApiTicker(ticker, "IN"),
      market: "IN",
      mode,
    });
    return res.run_id;
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(`[run-queue] start failed for ${ticker} (${mode})`, err);
    }
    return null;
  }
}

async function fetchLatestRun(
  ticker: string,
  mode: StrategyMode,
): Promise<LatestRunResponse | null> {
  try {
    return await api.getLatestRun(toApiTicker(ticker, "IN"), {
      market: "IN",
      mode,
    });
  } catch (err) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(`[run-queue] latest lookup failed for ${ticker} (${mode})`, err);
    }
    return null;
  }
}

export function useStrategyBucket(
  mode: StrategyMode,
): UseStrategyBucketResult {
  const tickers = useStrategyStore((s) => s.buckets[mode]);
  const setLastRunId = useStrategyStore((s) => s.setLastRunId);
  const getLastRunId = useStrategyStore((s) => s.getLastRunId);
  const decorateWatchlist = useWatchlistStore((s) => s.decorate);
  const watchlistHas = useWatchlistStore((s) => s.has);

  const qc = useQueryClient();
  const meta = STRATEGY_META[mode];

  // Hydrate previously-saved run_ids so the first paint isn't blank.
  const [runIds, setRunIds] = React.useState<Record<string, string | null>>(
    () => {
      const seed: Record<string, string | null> = {};
      for (const t of tickers) {
        seed[toDisplayTicker(t)] = getLastRunId(mode, t) ?? null;
      }
      return seed;
    },
  );

  // For brand-new bucket members, kick off a one-shot analyze. Within
  // the same UTC day the second call would idempotent-hit anyway, so we
  // only need to do this for tickers we haven't seen before.
  React.useEffect(() => {
    let cancelled = false;
    const display = tickers.map((t) => toDisplayTicker(t));

    const reconcile = async () => {
      const next: Record<string, string | null> = {};
      for (const t of display) {
        next[t] = runIds[t] ?? getLastRunId(mode, t) ?? null;
      }

      const toStart = display.filter((t) => !next[t]);
      if (toStart.length > 0) {
        const settled = await Promise.allSettled(
          toStart.map((t) => startAnalysis(t, mode)),
        );
        if (cancelled) return;
        toStart.forEach((t, i) => {
          const r = settled[i];
          if (r && r.status === "fulfilled" && r.value) {
            next[t] = r.value;
            setLastRunId(mode, t, r.value);
          }
        });
      }
      if (!cancelled) setRunIds(next);
    };

    void reconcile();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickers.join("|"), mode]);

  // Poll the server for the newest run id every minute. The scheduler
  // mints a fresh id on every tick, so this is how the card flips off
  // the original analyze run onto the latest scheduler dispatch.
  React.useEffect(() => {
    if (tickers.length === 0) return;
    let cancelled = false;

    const refreshLatest = async () => {
      for (const t of tickers) {
        const display = toDisplayTicker(t);
        const latest = await fetchLatestRun(t, mode);
        if (cancelled) return;
        const newId = latest?.run_id ?? null;
        if (!newId) continue;
        setRunIds((cur) => {
          if (cur[display] === newId) return cur;
          setLastRunId(mode, t, newId);
          qc.invalidateQueries({ queryKey: queryKeys.run(newId) });
          return { ...cur, [display]: newId };
        });
      }
    };

    void refreshLatest();
    const id = window.setInterval(() => {
      void refreshLatest();
    }, LATEST_RUN_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [tickers, mode, qc, setLastRunId]);

  // Poll each ticker's run detail.
  const queries = useQueries({
    queries: tickers.map((t) => {
      const display = toDisplayTicker(t);
      const runId = runIds[display] ?? null;
      return {
        queryKey: queryKeys.run(runId),
        queryFn: () => api.getRun(runId as string),
        enabled: Boolean(runId),
        refetchInterval: meta.refreshIntervalMs,
        staleTime: 30_000,
      };
    }),
  });

  // Side-effect: when a query yields a fresh decision for a watchlist
  // member, decorate it so the Watchlist tab can show the latest signal.
  React.useEffect(() => {
    queries.forEach((q, i) => {
      const t = tickers[i];
      const data = q.data as RunDetail | undefined;
      if (!t || !data || !data.decision) return;
      const display = toDisplayTicker(t);
      if (!watchlistHas(display)) return;
      decorateWatchlist(display, {
        lastSignal: data.decision.signal,
        lastConfidence: data.decision.confidence,
        lastPrice: data.decision.entry_price ?? undefined,
        lastAnalysisAt: data.decision.timestamp,
        lastRunId: data.run_id,
      });
    });
    // queries changes by reference each render — depend on a stable
    // serialization of ids/statuses to avoid an infinite loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    queries
      .map((q) => `${(q.data as RunDetail | undefined)?.run_id ?? ""}:${q.dataUpdatedAt}`)
      .join("|"),
  ]);

  const rows: BucketRow[] = tickers.map((t, i) => {
    const display = toDisplayTicker(t);
    const runId = runIds[display] ?? null;
    const data = queries[i]?.data as RunDetail | undefined;
    const decision = data?.decision ?? null;
    return {
      ticker: display,
      runId,
      detail: data ?? null,
      signal: decision?.signal ?? null,
      confidence: decision?.confidence ?? null,
      lastUpdatedAt:
        decision?.timestamp ?? data?.completed_at ?? data?.created_at ?? null,
      status: data?.status ?? (runId ? "pending" : "idle"),
    };
  });

  const refreshAll = React.useCallback(async () => {
    // Manual refresh button — re-resolve the latest run id for every
    // bucket member. The scheduler keeps minting them; this just makes
    // the UI snap to the freshest one without waiting for the timer.
    for (const t of tickers) {
      const display = toDisplayTicker(t);
      const latest = await fetchLatestRun(t, mode);
      const newId = latest?.run_id ?? null;
      if (!newId) continue;
      setRunIds((cur) => {
        setLastRunId(mode, t, newId);
        qc.invalidateQueries({ queryKey: queryKeys.run(newId) });
        return { ...cur, [display]: newId };
      });
    }
  }, [mode, tickers, qc, setLastRunId]);

  const startTicker = React.useCallback(
    async (ticker: string) => {
      // The "Re-run" button is one of the few cases where we still want
      // to POST /analyze directly — the user explicitly asked for a
      // fresh analysis off the schedule.
      const rid = await startAnalysis(ticker, mode);
      if (rid) {
        setRunIds((cur) => ({ ...cur, [toDisplayTicker(ticker)]: rid }));
        setLastRunId(mode, ticker, rid);
        qc.invalidateQueries({ queryKey: queryKeys.run(rid) });
      }
      return rid;
    },
    [mode, setLastRunId, qc],
  );

  return { rows, refreshAll, startTicker };
}
