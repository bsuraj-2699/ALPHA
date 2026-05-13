/**
 * Tiny typed fetch wrapper around the FastAPI backend.
 *
 * Pages should consume these via TanStack Query rather than calling them
 * directly — see `app/providers.tsx` for the QueryClient setup.
 */

import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ApproveRequest,
  ApproveResponse,
  BucketAddRequest,
  BucketReplaceRequest,
  BucketResponse,
  BucketsResponse,
  HealthResponse,
  LatestRunResponse,
  Mode,
  PortfolioResponse,
  PriceInterval,
  PriceResponse,
  RunDetail,
  WatchlistAddRequest,
  WatchlistResponse,
} from "@/types/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ??
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text().catch(() => null);
    }
    throw new ApiError(
      `API ${res.status} on ${path}`,
      res.status,
      body,
    );
  }

  // 204 / empty body
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  base: API_BASE,

  health: () => request<HealthResponse>("/health"),

  analyze: (body: AnalyzeRequest) =>
    request<AnalyzeResponse>("/api/analyze", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getRun: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),

  /**
   * Resolve the newest run for `(ticker, mode)` from the backend's
   * in-process record map. Returns `run_id: null` when nothing has been
   * dispatched yet — callers should treat that as the empty state, not
   * an error. Used by the Runs page to follow auto-scheduled runs that
   * the client never explicitly POSTed.
   */
  getLatestRun: (
    ticker: string,
    opts: { market?: "IN" | "US"; mode?: Mode } = {},
  ) => {
    const params = new URLSearchParams();
    params.set("ticker", ticker);
    params.set("market", opts.market ?? "IN");
    if (opts.mode) params.set("mode", opts.mode);
    return request<LatestRunResponse>(
      `/api/runs/latest?${params.toString()}`,
    );
  },

  approveRun: (runId: string, body: ApproveRequest) =>
    request<ApproveResponse>(`/api/runs/${runId}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ----- buckets -----

  listBuckets: () => request<BucketsResponse>("/api/buckets"),

  getBucket: (mode: Mode) =>
    request<BucketResponse>(`/api/buckets/${mode}`),

  addToBucket: (mode: Mode, body: BucketAddRequest) =>
    request<BucketResponse>(`/api/buckets/${mode}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  replaceBucket: (mode: Mode, body: BucketReplaceRequest) =>
    request<BucketResponse>(`/api/buckets/${mode}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  removeFromBucket: (mode: Mode, ticker: string) =>
    request<BucketResponse>(
      `/api/buckets/${mode}/${encodeURIComponent(ticker)}`,
      { method: "DELETE" },
    ),

  /** Returns the absolute SSE endpoint URL — caller wires up EventSource. */
  runStreamUrl: (runId: string) =>
    `${API_BASE}/api/runs/${runId}/stream`,

  price: (
    ticker: string,
    opts: {
      market?: "IN" | "US";
      interval?: PriceInterval;
      lookbackDays?: number;
    } = {},
  ) => {
    const params = new URLSearchParams();
    params.set("market", opts.market ?? "IN");
    params.set("interval", opts.interval ?? "1d");
    params.set("lookback_days", String(opts.lookbackDays ?? 200));
    return request<PriceResponse>(
      `/api/price/${encodeURIComponent(ticker)}?${params.toString()}`,
    );
  },

  watchlist: () => request<WatchlistResponse>("/api/watchlist"),

  addToWatchlist: (body: WatchlistAddRequest) =>
    request<WatchlistResponse>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Best-effort delete. The current backend doesn't expose DELETE
   * yet — we attempt the call so a future endpoint Just Works, but
   * callers should not gate UI on the result.
   *
   * TODO(backend): wire DELETE /api/watchlist/:ticker.
   */
  removeFromWatchlist: (ticker: string, market: "IN" | "US") =>
    request<void>(
      `/api/watchlist/${encodeURIComponent(ticker)}?market=${market}`,
      { method: "DELETE" },
    ),

  portfolio: () => request<PortfolioResponse>("/api/portfolio"),
};

export type Api = typeof api;
