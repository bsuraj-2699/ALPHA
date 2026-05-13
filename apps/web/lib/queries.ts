"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ApproveRequest,
  ApproveResponse,
  HealthResponse,
  PriceInterval,
  PriceResponse,
  RunDetail,
  WatchlistAddRequest,
  WatchlistResponse,
} from "@/types/api";

/**
 * TanStack Query hook factory for each API surface. Pages should
 * use these rather than calling `api.*` directly so caching, refetch
 * behavior and invalidation stay consistent.
 */

export const queryKeys = {
  health: ["health"] as const,
  run: (runId: string | null | undefined) => ["run", runId] as const,
  watchlist: ["watchlist"] as const,
  portfolio: ["portfolio"] as const,
  price: (
    ticker: string,
    market: "IN" | "US",
    interval: PriceInterval,
    lookbackDays: number,
  ) => ["price", market, ticker.toUpperCase(), interval, lookbackDays] as const,
};

export function useHealth() {
  return useQuery<HealthResponse, ApiError>({
    queryKey: queryKeys.health,
    queryFn: () => api.health(),
    refetchInterval: 30_000,
  });
}

export function useStartAnalysis() {
  const qc = useQueryClient();
  return useMutation<AnalyzeResponse, ApiError, AnalyzeRequest>({
    mutationFn: (req) => api.analyze(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist });
    },
  });
}

/**
 * Poll the run detail every 2s while the run is in flight. Once it
 * reaches a terminal state the polling cadence drops to manual
 * (refetchInterval = false). The SSE stream is the primary live source;
 * this query is the safety net + the source of truth for non-streamed
 * fields like `analyst_reports`.
 */
export function useRun(runId: string | null | undefined) {
  return useQuery<RunDetail, ApiError>({
    queryKey: queryKeys.run(runId ?? null),
    queryFn: () => api.getRun(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 2_000;
      if (
        status === "complete" ||
        status === "error" ||
        status === "interrupted"
      ) {
        return false;
      }
      return 2_000;
    },
    staleTime: 0,
  });
}

export function useApproveRun() {
  const qc = useQueryClient();
  return useMutation<
    ApproveResponse,
    ApiError,
    { runId: string; body: ApproveRequest }
  >({
    mutationFn: ({ runId, body }) => api.approveRun(runId, body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.run(vars.runId) });
    },
  });
}

export function useWatchlist() {
  return useQuery<WatchlistResponse, ApiError>({
    queryKey: queryKeys.watchlist,
    queryFn: () => api.watchlist(),
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation<WatchlistResponse, ApiError, WatchlistAddRequest>({
    mutationFn: (body) => api.addToWatchlist(body),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.watchlist, data);
    },
  });
}

export function useRemoveFromWatchlist() {
  const qc = useQueryClient();
  return useMutation<
    void,
    ApiError,
    { ticker: string; market: "IN" | "US" }
  >({
    mutationFn: ({ ticker, market }) =>
      api.removeFromWatchlist(ticker, market),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist });
    },
  });
}

export function usePortfolio() {
  return useQuery({
    queryKey: queryKeys.portfolio,
    queryFn: () => api.portfolio(),
  });
}

/**
 * Real OHLC + spot quote for the analyze chart.
 *
 * Refetches every 60s (matches the backend in-process cache TTL) and
 * keeps prior data on the screen across ticker changes so the chart
 * doesn't flash to "loading" between switches.
 */
export function usePrice(
  ticker: string,
  opts: {
    market?: "IN" | "US";
    interval?: PriceInterval;
    lookbackDays?: number;
    enabled?: boolean;
    /** Poll interval in ms. Defaults to 60_000. Pass `false` to disable polling. */
    refetchInterval?: number | false;
  } = {},
) {
  const market = opts.market ?? "IN";
  const interval = opts.interval ?? "1d";
  const lookbackDays = opts.lookbackDays ?? 200;
  return useQuery<PriceResponse, ApiError>({
    queryKey: queryKeys.price(ticker, market, interval, lookbackDays),
    queryFn: () =>
      api.price(ticker, { market, interval, lookbackDays }),
    enabled: (opts.enabled ?? true) && ticker.length > 0,
    refetchInterval:
      opts.refetchInterval !== undefined ? opts.refetchInterval : 60_000,
    staleTime: 30_000,
  });
}
