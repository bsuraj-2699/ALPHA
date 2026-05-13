/**
 * Wire types for the FastAPI backend at apps/api/.
 *
 * Hand-mirrored from `apps/api/models.py` — keep in sync when the API
 * evolves. (We could codegen from the OpenAPI schema later; for now
 * the surface is small enough that manual mirrors are clearer.)
 */

export type Market = "IN" | "US";

export type RunStatus =
  | "pending"
  | "running"
  | "interrupted"
  | "complete"
  | "error";

export type Signal =
  | "STRONG_BUY"
  | "BUY"
  | "HOLD"
  | "SELL"
  | "STRONG_SELL";

/**
 * Time-horizon preset accepted by /api/analyze.
 *
 * Mirrors `packages.shared.config.Mode` on the backend — keep in sync.
 */
export type Mode = "intraday" | "short_term" | "long_term";

/* ------------------------------------------------------------ */
/* /api/analyze                                                  */
/* ------------------------------------------------------------ */

export interface AnalyzeRequest {
  ticker: string;
  market: Market;
  /** Defaults server-side to `long_term` when omitted. */
  mode?: Mode;
  portfolio_context?: Record<string, unknown> | null;
}

export interface AnalyzeResponse {
  run_id: string;
  idempotent_hit: boolean;
  status: RunStatus;
  mode?: Mode;
}

/* ------------------------------------------------------------ */
/* /api/runs/{id}                                                */
/* ------------------------------------------------------------ */

export interface AnalystReport {
  category: string;
  score: number;
  narrative: string;
  top_signals?: string[];
  citations?: string[];
}

export interface Decision {
  ticker: string;
  market: Market;
  signal: Signal;
  confidence: number;
  position_size_pct: number;
  entry_price: number | null;
  stop_loss: number | null;
  target_price: number | null;
  rationale: string;
  citations: string[];
  overrides_active: string[];
  requires_human_review: boolean;
  timestamp: string;
}

export interface ReasoningStep {
  agent: string;
  output: string;
  timestamp: string;
  duration_ms?: number;
  tokens_in?: number;
  tokens_out?: number;
}

export interface RunDetail {
  run_id: string;
  ticker: string;
  market: Market;
  status: RunStatus;
  created_at: string;
  completed_at: string | null;

  decision: Decision | null;
  judgment: Record<string, unknown> | null;
  bull_case: Record<string, unknown> | null;
  bear_case: Record<string, unknown> | null;
  analyst_reports: Record<string, AnalystReport>;
  evaluation: Record<string, unknown> | null;
  reasoning_trace: ReasoningStep[];

  error: string | null;
  interrupt: Record<string, unknown> | null;
}

export interface ApproveRequest {
  response: string;
}

export interface ApproveResponse {
  run_id: string;
  status: RunStatus;
  final_signal: Signal | null;
}

/* ------------------------------------------------------------ */
/* SSE event types                                               */
/* ------------------------------------------------------------ */

export type RunEventType =
  | "agent_start"
  | "agent_complete"
  | "thinking"
  | "decision"
  | "interrupted"
  | "error"
  | "_terminal_";

export interface RunEvent<T = unknown> {
  run_id: string;
  type: RunEventType;
  timestamp: string;
  data: T;
}

/* ------------------------------------------------------------ */
/* /api/price/{ticker}                                           */
/* ------------------------------------------------------------ */

export type PriceInterval =
  | "1m"
  | "5m"
  | "15m"
  | "30m"
  | "1h"
  | "1d"
  | "1wk"
  | "1mo";

export interface PriceBar {
  /** Unix-seconds timestamp (lightweight-charts compatible). */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceQuote {
  price: number;
  change_pct: number | null;
  currency: string;
  timestamp: string;
}

export interface PriceResponse {
  ticker: string;
  market: Market;
  interval: PriceInterval;
  currency: string;
  bars: PriceBar[];
  quote: PriceQuote | null;
  /** `upstox` | `yahoo` | `synthetic` */
  source: string;
  /** True when only the synthetic placeholder was available. */
  stale: boolean;
}

/* ------------------------------------------------------------ */
/* /api/portfolio                                                */
/* ------------------------------------------------------------ */

export interface PortfolioPosition {
  ticker: string;
  market: Market;
  shares: number;
  avg_purchase_price: number | null;
  current_value_usd: number | null;
}

export interface PortfolioResponse {
  positions: PortfolioPosition[];
  total_value_usd: number;
}

/* ------------------------------------------------------------ */
/* /api/buckets                                                  */
/* ------------------------------------------------------------ */

export interface BucketResponse {
  mode: Mode;
  tickers: string[];
}

export interface BucketsResponse {
  buckets: Partial<Record<Mode, string[]>>;
}

export interface BucketAddRequest {
  tickers: string[];
}

export interface BucketReplaceRequest {
  tickers: string[];
}

/* ------------------------------------------------------------ */
/* /api/runs/latest                                              */
/* ------------------------------------------------------------ */

export interface LatestRunResponse {
  ticker: string;
  market: Market;
  mode: Mode;
  run_id: string | null;
  status: RunStatus | null;
  created_at: string | null;
  completed_at: string | null;
}

/* ------------------------------------------------------------ */
/* /api/watchlist                                                */
/* ------------------------------------------------------------ */

export interface WatchlistItem {
  ticker: string;
  market: Market;
  added_at: string;
}

export interface WatchlistResponse {
  items: WatchlistItem[];
}

export interface WatchlistAddRequest {
  ticker: string;
  market: Market;
}

/* ------------------------------------------------------------ */
/* /health                                                       */
/* ------------------------------------------------------------ */

export type ServiceStatus = "ok" | "degraded" | "down" | "not_configured";

export interface HealthService {
  status: ServiceStatus;
  latency_ms: number | null;
  error: string | null;
}

export interface HealthResponse {
  status: ServiceStatus;
  services: Record<string, HealthService>;
  version: string;
}
