# ALPHA — Product Requirements Document (Final, v2.0)

**Product:** ALPHA — Deterministic-Decision, Multi-Agent Equity Analysis for NSE **Document type:** Final PRD (as-built specification and forward roadmap) **Version:** 2.0 · **Status:** Production baseline **Date:** 16 November 2026 **Product owner:** bsuraj-2699 (repository owner) **Basis:** Full review of the ALPHA repository: README, CLAUDE.md, rules.json v2.0.1 (schema 2026-05-03), API, agent, data, RAG, web, evaluation, infrastructure and deployment files. The latest commit reviewed is dated 3 September 2026.

## 1. Document control and what changed since v1.0

This document describes ALPHA as built and operated, and sets the requirements for the next phase. It supersedes the Initial PRD (v1.0).

| Area | Initial PRD (v1.0) | Final PRD (v2.0, as built) |
| --- | --- | --- |
| Market scope | US and IN codes in data model | **India (NSE) only**; any other market returns HTTP 400 |
| Execution model | Single pipeline; decision after narration | **Two stages**: deterministic decision first, narration after |
| Confidence | Derived from composite score | **Calibrated P(setup reliable)** over 7 evidence axes |
| Horizons | One weighting | **Three run modes**: intraday, short\_term, long\_term |
| Overrides | 5 | **4** (OVR-O3 removed as defective) |
| Rule logic | Basic evaluator | Hardened grammar, total condition ladders, abstention tracking, thin-evidence floor |
| Historical context | General retrieval | **Intraday market memory**: 24-dimension fingerprints; never affects the signal |
| Scheduling | None | Intraday every 5 min, daily 10:00 IST, event-driven retrigger |
| API | Request/response | **Non-blocking**: 202 + run ID, SSE event stream, idempotency |
| Model layer | Single hosted model | One OpenAI-compatible endpoint, primary + fallback, guardrails, tracing |
| Sentiment inputs | Analyst ratings, insider, short interest | News NLP, FII/DII flows, sector strength, price/volume spike, India VIX |
| Deployment | Not defined | Oracle Cloud (API) + Vercel (web), with a Render blueprint retained |

The answers to the open questions in the Initial PRD are: focus on India; separate confidence from score; narration must not block the decision; weights differ by horizon; historical analogues inform confidence and explanation only.

## 2. Executive summary

ALPHA analyses Indian listed equities and returns an auditable recommendation. A rule engine converts market, fundamental, sentiment, macro and risk data into a composite score on a 0–100 scale and a five-level signal. Deterministic code then derives position size, stop-loss, target and review flags. Language-model agents run afterwards to explain the result through pillar analyses, a structured bull-versus-bear debate and a judge narrative.

**The product invariant:** *the LLM never makes the trade decision.* This is enforced structurally. Narrative schemas contain no score field, the decision agent imports no model code, and a test requires the fast-path signal to equal the full-graph signal for the same context.

The decision is emitted at the end of stage 1 and reaches the client before any model call completes. Model outages, slow providers or malformed output therefore cannot change, delay or lose a recommendation.

## 3. Problem and opportunity

Indian investors need consistent, explainable, fast analysis that respects local data (NSE, FII/DII flows, India VIX, Screener fundamentals). Generic chat assistants are non-deterministic and cannot show why a call was made. Black-box scoring tools do not explain themselves. ALPHA occupies the gap: **repeatable numbers from rules, readable reasoning from language models, and a complete audit trail.**

## 4. Users and use cases

| Persona | Use case | Mode |
| --- | --- | --- |
| Intraday trader | Five-minute refreshed signal during market hours with historical analogues | intraday |
| Swing trader | Daily signal driven mainly by technicals, sentiment and risk | short\_term |
| Long-term investor | Weekly-chart view weighted toward fundamentals | long\_term |
| Analyst | Inspect which rules fired, overrides, coverage and the debate | all |
| Operator / developer | Tune rules and weights, monitor health, replay scenarios | all |

## 5. Goals, non-goals and KPIs

### 5.1 Goals

- Deliver a decision before any LLM latency (time-to-decision is a first-class metric).
- Keep every quantitative output deterministic and traceable to rule IDs.
- Express honest uncertainty through coverage, confidence and thin-evidence handling.
- Degrade gracefully when data providers or models fail.
- Operate scheduled analysis for tracked tickers without manual triggers.

### 5.2 Non-goals

- Brokerage connectivity or order execution.
- Personalised investment advice or suitability profiling.
- Markets outside India, instruments other than cash equities.
- Multi-tenant accounts and billing (not present in the current build).

### 5.3 Key performance indicators

Targets are proposed for operational tracking; the repository provides the instruments (benchmark script, `ttd_ms` field, `run_logs` table, LangSmith tracing) but does not publish measured production values.

| KPI | Definition | Target | Instrument |
| --- | --- | --- | --- |
| Time-to-decision (TTD) | Request to `decision_ready` event | Deterministic compute sub-millisecond; end-to-end bound by data fetch (30 s ceiling) | `ttd_ms`, `scripts/benchmark.py` |
| Determinism | Fast-path signal equals full-graph signal | 100% | `test_fast_path.py` |
| Data coverage | In-scope rules evaluated with real data | At or above 60% on most runs | `data_coverage_pct` |
| Rule health | Abstained rules and structural-expression warnings | Zero | Evaluator logs, ladder tests |
| Decision durability | Runs that keep the decision despite enrichment failure | 100% | Two-stage tests |
| Enrichment success | Runs with narrative generated | Tracked; no hard target while on free-tier models | `run_logs` |
| Signal quality | Backtest return, Sharpe, drawdown, hit rate vs NIFTYBEES | Reported per release | Evaluation harness |
| Availability | `/health` reports `ok` for configured services | Tracked | `/health` |

## 6. Product overview

### 6.1 Capability map

| Layer | Role | LLM involved |
| --- | --- | --- |
| Rule engine | Scores 36 rules and applies 4 overrides, weighted by mode | No |
| Confidence | Calibrated reliability over 7 axes | No |
| Decision agent | Signal, sizing, stop, target, review flag, coverage guard | No |
| Market memory | Intraday recall of similar past situations | No |
| Pillar analysts | Fundamental, technical, sentiment, macro, risk narratives | Yes (narrative only) |
| Debate | Bull and bear cases from analyst reports | Yes |
| Judge | Consolidated explanation citing rule IDs | Yes |

### 6.2 Run modes

Weights are defined in `rules.json` under `modes.<mode>.pillar_weights` and must use five canonical pillar names summing to 1.0.

| Mode | Technical | Sentiment | Risk | Macro | Fundamental | Charts (primary / secondary / context) | Lookback | Cadence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| intraday | 0.40 | 0.30 | 0.30 | 0 | 0 | 5 min / 15 min / none | 78 bars | Every 5 min, 09:15–15:30 IST, Mon–Fri |
| short\_term | 0.48 | 0.20 | 0.20 | 0.12 | 0 | 1 day / 60 min / 1 week | 90 bars | Daily 10:00 IST |
| long\_term | 0.18 | 0.10 | 0.15 | 0.12 | 0.45 | 1 week / 1 month / 1 day | 104 bars | Daily 10:00 IST |

If a caller gives no mode, the engine selects one by IST clock: intraday during market hours, short\_term outside hours on weekdays, long\_term on weekends. Callers may always override. Intraday and short\_term skip the Screener.in fetch because fundamentals carry zero weight.

## 7. Functional requirements and status

Status: **Delivered** (in the repository and covered by tests or documentation), **Partial** (present with limitations), **Planned** (proposed in the roadmap).

### 7.1 Analysis run lifecycle

| ID | Requirement | Status |
| --- | --- | --- |
| FR-01 | `POST /api/analyze` returns 202 with `run_id` immediately; processing runs in the background | Delivered |
| FR-02 | For short\_term and long\_term, a hash of ticker, market, mode and date maps to a fixed run ID; duplicate requests return the existing run with `idempotent_hit` | Delivered |
| FR-03 | Intraday runs always mint a new run ID | Delivered |
| FR-04 | Stage 1 emits the decision and `decision_ready` with `ttd_ms` before enrichment starts | Delivered |
| FR-05 | Stage 2 runs analysts in parallel, then debate, then judge, and cannot alter signal, size or confidence | Delivered |
| FR-06 | Enrichment failure never loses the decision | Delivered |
| FR-07 | Actionable intraday outcomes (BUY, STRONG\_BUY, SELL, STRONG\_SELL) persist at decision time | Delivered |
| FR-08 | STRONG\_BUY and STRONG\_SELL pause for human approval unless auto-approve is on; approval keeps the deterministic decision, any other response downgrades to HOLD | Delivered |
| FR-09 | Only market `IN` accepted; others return HTTP 400 | Delivered |

### 7.2 Rule engine and decision

| ID | Requirement | Status |
| --- | --- | --- |
| FR-10 | Evaluate 36 scoring rules across 8 categories using a safe expression grammar with no `eval()` | Delivered |
| FR-11 | Rules with missing inputs are skipped and leave both numerator and denominator | Delivered |
| FR-12 | Condition ladders tried in order strong\_buy, buy, strong\_sell, sell, neutral; unmatched rules abstain and are tracked separately from data gaps | Delivered |
| FR-13 | Fewer than 8 evaluated rules forces HOLD with an explanatory note; the floor only moves toward HOLD | Delivered |
| FR-14 | Apply override rules OVR-O1, O2, O4 and O5 | Delivered |
| FR-15 | Map composite to signal by thresholds; each mode carries its own threshold table (for example intraday STRONG\_BUY at 78 and above) | Delivered |
| FR-16 | Report `data_coverage_pct`; below 60% cap position at 3% and show a low-coverage warning | Delivered |
| FR-17 | Compute position size, stop-loss (8% below entry for buys) and target (consensus or entry plus 20%) | Delivered |
| FR-18 | Hard cap of 10% per position; construction fails if configuration exceeds it | Delivered |

### 7.3 Confidence and memory

| ID | Requirement | Status |
| --- | --- | --- |
| FR-19 | Compute calibrated confidence over 7 axes with renormalisation when an axis has no evidence | Delivered |
| FR-20 | Attach `confidence_breakdown` to every decision | Delivered |
| FR-21 | Store high-quality completed intraday situations as 24-dimension fingerprints in Qdrant with an in-memory fallback | Delivered |
| FR-22 | Recall similar fingerprints on intraday runs; feed `historical_success` and narrative only | Delivered |
| FR-23 | Do not store HOLD outcomes or skipped runs in memory | Delivered |

### 7.4 Intelligence layer

| ID | Requirement | Status |
| --- | --- | --- |
| FR-24 | Parse free-text queries into ticker, intent and horizon | Delivered |
| FR-25 | Five pillar analysts selected by mode, producing narrative, top signals and citations | Delivered |
| FR-26 | Bull and bear cases built from analyst reports | Delivered |
| FR-27 | Judge narrative added after rules have fired | Delivered |
| FR-28 | Fully offline operation with templated prose when no LLM key is set | Delivered |

### 7.5 Scheduling and reactive triggers

| ID | Requirement | Status |
| --- | --- | --- |
| FR-29 | `IntradayScheduler` dispatches every 5 minutes in NSE hours for the intraday bucket | Delivered |
| FR-30 | `DailyScheduler` dispatches short\_term and long\_term buckets once per business day | Delivered |
| FR-31 | `RetriggerSubscriber` reacts to Redis `retrigger:*` events from Upstox WebSocket thresholds, with a 60-second cooldown | Delivered |
| FR-32 | Strategy buckets per mode, readable and writable through the API | Delivered |
| FR-33 | Exchange holiday calendar awareness | Planned (current logic keys on weekdays) |

### 7.6 Client and operations

| ID | Requirement | Status |
| --- | --- | --- |
| FR-34 | Web dashboard: analyse, live pipeline, decision card, pillar radar, debate panel, price chart, run inspector with execution graph, watchlist | Delivered |
| FR-35 | SSE stream with event types `agent_start`, `agent_complete`, `thinking`, `decision`, `decision_ready`, `interrupted`, `analysis_complete`, `error`, plus keep-alive | Delivered |
| FR-36 | Watchlist deduplicated on ticker and market | Delivered |
| FR-37 | Portfolio endpoint | Partial (in-memory list; value fields are USD-named) |
| FR-38 | Run audit log and Excel export | Delivered |
| FR-39 | `/health` reports ok, degraded or not\_configured per service | Delivered |

## 8. Decision engine specification

### 8.1 Rule inventory (rules.json v2.0.1)

| Category | Rules | Examples |
| --- | --- | --- |
| fundamentals | 5 | EPS growth, revenue growth, net margin, ROE/ROA, free cash flow |
| balance\_sheet | 3 | Debt-to-equity, current and quick ratio, interest coverage |
| trend | 3 | 50/200-day cross, 52-week range, EMA ribbon |
| momentum | 6 | RSI, MACD, stochastic, volume, Bollinger, support/resistance |
| sentiment | 5 | News NLP, FII/DII flow, sector strength, price/volume spike, India VIX (contrarian) |
| macro | 7 | Rates, GDP cycle, inflation, sector rotation, currency, FII flow, put-call ratio |
| valuation | 5 | P/E, PEG, EV/EBITDA, P/B, dividend yield |
| risk | 2 | Beta, India VIX volatility |

### 8.2 Signal thresholds (long\_term and short\_term)

| STRONG\_SELL | SELL | HOLD | BUY | STRONG\_BUY |
| --- | --- | --- | --- | --- |
| below 15 | 15 – 44.99 | 45 – 62.99 | 63 – 84.99 | 85 and above |

### 8.3 Overrides

| ID | Trigger | Action |
| --- | --- | --- |
| OVR-O1 | Fraud allegation, material restatement or regulator investigation | Force STRONG\_SELL |
| OVR-O2 | Guidance withdrawn without explanation | Force SELL |
| OVR-O4 | Price 8% or more below average purchase | Pause BUY (existing positions) |
| OVR-O5 | Position 10% or more of portfolio | Block BUY |

OVR-O3 (dividend cut) was removed because its input measured a decline in payout ratio rather than an announced cut and its income-portfolio scope was never enforced.

### 8.4 Confidence axes

| Axis | Weight | Question answered |
| --- | --- | --- |
| rule\_agreement | 0.22 | Do fired directional rules point one way? |
| data\_coverage | 0.20 | What share of in-scope rules had real data? |
| pillar\_agreement | 0.16 | Do active pillars agree with the composite? |
| historical\_success | 0.12 | How did similar past setups perform? |
| indicator\_agreement | 0.12 | Do core technical indicators agree? |
| rule\_consistency | 0.10 | Do overrides and skips undercut the score? |
| regime\_confidence | 0.08 | Does the market regime support the direction? |

Axes without evidence are dropped and the remaining weights renormalised, so missing evidence neither inflates nor deflates confidence.

### 8.5 Sizing and risk controls

| Signal | Position target |
| --- | --- |
| STRONG\_BUY | 8% |
| BUY | 4% |
| HOLD | 0% (no new entry) |
| SELL | 2% (trim) |
| STRONG\_SELL | 0% (exit) |

Low coverage caps size at 3%. Stop-loss and target are produced only for BUY and STRONG\_BUY; other signals carry no entry plan.

## 9. Intelligence layer

### 9.1 Model provider

All chat flows use `instructor` over `litellm` against one OpenAI-compatible endpoint. Default host is Groq with `openai/gpt-oss-120b` as primary and `openai/gpt-oss-20b` as fallback. Any compatible host works by changing the base URL. Agents depend only on a `ChatProvider` interface; a test prevents agents from importing `litellm` or hardcoding model IDs.

**Requirements**

- Models must support tool calling, since structured output depends on it. Validate any new model with a real structured completion call.
- Model IDs are host-specific and move together with the base URL.
- Retired models (HTTP 410) are treated as permanent and skipped straight to the fallback.
- Groq's `openai/` namespace collides with LiteLLM routing, so the code sends a deliberate double prefix; this must not be “fixed”.

### 9.2 Guardrails

| Control | Default | Purpose |
| --- | --- | --- |
| Requests per minute | 60 | Sliding-window cap |
| Concurrency | 4 (README) | Semaphore on in-flight calls |
| Prompt limit | 24,000 characters | Input truncation |
| Output limit | 4,000 characters | Truncation, control-character stripping, confidence clamped to 0–1 |

Guardrails never touch signal, score or size.

### 9.3 Tracing

Setting `LANGSMITH_API_KEY` enables LangSmith logging of every model call (prompt, response, tokens, latency) under project `alpha-fin-agent`. Without a key tracing is a no-op.

## 10. Data layer

| Provider | Supplies |
| --- | --- |
| Upstox | Quotes, OHLC, company fundamentals, WebSocket price and volume events, daily-refreshed token |
| Screener.in | Indian fundamentals (long\_term only) |
| NSE | India VIX, FII/DII flows, put-call ratio, NIFTY data |
| Yahoo Finance | Fallback prices and indices |
| GDELT | News sentiment |

**Requirements**

- Five provider blocks fetched concurrently under a 30-second global timeout; a timeout returns partial context.
- Per-provider caching in Redis and rate limiting.
- Upstox instrument master (cash-equity segments) indexed by verbatim and normalised symbol, NSE preferred on dual listings, cached 24 hours, falling back to a static registry of Nifty 50 and Nifty Next 50.
- NIFTY 50 trend data resolves to the index symbol, not an equity key.
- GDELT errors and HTTP 429 return neutral sentiment so sentiment rules are not all skipped.
- VIX and beta are backfilled with neutral defaults when unavailable.
- “Rules skipped” means missing context fields, not a failed LLM call.

## 11. API specification

All endpoints sit under `/api`; interactive documentation is at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/analyze` | Start a run; 202 with run ID, idempotency flag and chart config |
| GET | `/api/runs/{run_id}` | Full state snapshot |
| GET | `/api/runs/{run_id}/stream` | Server-sent events |
| POST | `/api/runs/{run_id}/approve` | Resume a human-review run |
| GET | `/api/price/{ticker}` | OHLC for charts |
| GET, POST | `/api/watchlist` | List or add |
| GET | `/api/portfolio` | Positions |
| GET | `/api/buckets` | All strategy buckets |
| GET, POST, PUT | `/api/buckets/{mode}` | Read, append or replace a bucket |
| GET | `/health` | Per-service status |

## 12. Web application

Next.js 15, React 19, TypeScript, Tailwind CSS 4, TanStack Query, Zustand, Framer Motion, Lightweight Charts, Recharts and React Flow. Dark theme with green, red and amber signal colours and gold accent.

| Route | Purpose |
| --- | --- |
| `/` | Dashboard, quick analyse, market clock |
| `/analyze`, `/analyze/[ticker]` | Live analysis with pipeline, decision, pillars, debate, chart |
| `/runs`, `/runs/[id]` | Run history and execution graph with trace timeline |
| `/watchlist` | Watchlist management |
| `/portfolio` | Positions |

The frontend needs only `NEXT_PUBLIC_API_URL`.

## 13. Non-functional requirements

| Category | Requirement |
| --- | --- |
| Safety | Model output must never reach signal, score, size, stop, target or overrides |
| Determinism | Same context gives same decision on every path |
| Performance | Stage 1 compute sub-millisecond; total TTD dominated by data providers |
| Resilience | Partial context on timeout; fallback model; in-memory fallbacks for Redis, Postgres and Qdrant |
| Security | No dynamic code evaluation; secrets in environment variables; CORS restricted by `ALLOW_ORIGINS` (wildcard for development only) |
| Observability | Run audit log, SSE lifecycle events, `/health`, optional LangSmith |
| Quality | Ruff, strict mypy, pytest with coverage; 36 test files in the repository |
| Portability | Python 3.11 or later, `uv`, Docker for backing services |

## 14. Architecture and deployment

**Stage 1 (critical path):** market data → context build → intraday memory recall → rule engine → confidence → sizing and risk → decision emitted. **Stage 2 (enrichment):** analysts in parallel → bull/bear debate → judge narrative. The full graph (`arun`) remains for tests and the human-review path.

| Component | Technology |
| --- | --- |
| API | FastAPI, background tasks, SSE |
| Orchestration | LangGraph with Redis checkpoints |
| Persistence | PostgreSQL (Timescale image): `run_logs`, `intraday_signals` |
| Cache and bus | Redis: idempotency, SSE fan-out, checkpoints, buckets, provider cache, Upstox token |
| Vector store | Qdrant on host ports 6335/6336 |
| API hosting | Oracle Cloud compute, Uvicorn single worker |
| Web hosting | Vercel, root directory `apps/web` |
| Token refresh | Upstox token exchanged at boot, then daily at 09:00 IST |

A Render blueprint (`render.yaml`, free plan, Singapore) remains in the repository as an alternative API host.

## 15. Quality and evaluation

- **Unit and integration tests** for rule grammar, ladders, confidence, guardrails, model provider, fast path, orchestrator, data providers, RAG and API.
- **Test markers:** `integration` and `live` are excluded by default so the suite runs offline.
- **Scenario suite:** 20 labelled scenario files and tests detect signal drift.
- **Backtester:** day-by-day replay with stops and targets, benchmark comparison with NIFTYBEES, HTML report.
- **Benchmark script:** offline measurement of rule evaluation, confidence, memory recall, decision build and the end-to-end fast path.
- **Known intentional failures:** three scenario fixtures (`ge_2018_dividend_cut`, `peloton_2022_post_pandemic_collapse`, `meta_2022_ad_slowdown`) encode earlier engine behaviour and await re-baselining.

## 16. Risks, compliance and responsible use

| Risk | Level | Mitigation / requirement |
| --- | --- | --- |
| Output perceived as investment advice | High | Display decision-support disclaimer on every result; obtain legal review of Indian securities regulations (including SEBI rules on research and advisory services) before any public or paid launch |
| Silent rule failure | High | Structural-expression warnings, ladder sweeps, abstention tracking |
| Data provider dependence (scraped or free-tier sources) | High | Caching, timeouts, neutral fallbacks; review terms of use before commercial use |
| Model drift or retirement | Medium | Fallback model, 410 handling, structured-output probe before swaps |
| Thin-data overconfidence | Medium | Coverage cap, thin-evidence floor, calibrated confidence |
| Single-worker API and free-tier hosting | Medium | Move to managed workers and paid tier before scale |
| No user authentication documented | Medium | Add auth and rate limits before external exposure |
| Historical analogue bias | Low | Memory limited to confidence and explanation |

## 17. Known gaps and technical debt

1. **Documentation drift.** CLAUDE.md still describes NVIDIA NIM models, 5 override rules and Qdrant on port 6333; the README and code describe Groq, 4 overrides and port 6335. The web README says pages are empty scaffolds, which no longer matches the implemented components. README deployment steps reference Render logs while Oracle Cloud is the stated host.
2. **Configuration inconsistencies.** Default LLM timeout is 25 s in the README and 120 s in `.env.example`; concurrency is 4 in the README, 2 in `.env.example`, and the README says the example ships 6.
3. **Portfolio** is in-memory with USD-named fields, unsuited to INR holdings or persistence.
4. **Evaluation fixtures** contain US tickers and three deliberately stale scenarios.
5. **Scheduling** is weekday-based without an NSE holiday calendar.
6. **Fallback weights** in `config.py` must be hand-synchronised with `rules.json`.
7. **Silent weight fallback:** invalid pillar weights log a warning and keep defaults.
8. **Sentiment pillar** blends sentiment and valuation (15/33 and 18/33), so changing it also changes valuation influence.

## 18. Roadmap

| Phase | Horizon | Deliverables |
| --- | --- | --- |
| Stabilise | 0–1 month | Reconcile documentation and config defaults; re-baseline three fixtures; add disclaimer to UI and API responses; NSE holiday calendar |
| Harden | 1–3 months | Authentication and rate limiting; persistent INR portfolio; schema validation CI for `rules.json`; monitoring dashboards for TTD, coverage and enrichment success |
| Prove | 2–4 months | Published backtest across Nifty 50 and Next 50 with out-of-sample periods; confidence calibration report (stated confidence vs realised hit rate) |
| Expand | 4–6 months | Broader universe beyond Nifty 100; alerts for signal changes; portfolio-aware sizing; multi-worker deployment |
| Evolve | 6–12 months | Rule versioning with A/B evaluation, explainability exports, optional broker read-only integration |

## 19. Open questions

1. Which legal and licensing review is required for the intended audience (personal use, shared beta, paid product)?
2. What realised-accuracy threshold justifies promoting a signal from “information” to “actionable”?
3. Should human-review approvals be recorded with user identity and reason?
4. Which production hosting standard (single VM or managed platform) is the commitment?
5. Should market memory extend beyond intraday once enough outcomes are stored?

## 20. Appendix — configuration reference

| Area | Variables |
| --- | --- |
| Data | `UPSTOX_API_KEY`, `UPSTOX_API_SECRET`, `UPSTOX_ACCESS_TOKEN`, `UPSTOX_REFRESH_TOKEN`, `UPSTOX_REDIRECT_URI`, `SCREENER_SESSION_COOKIE` |
| LLM | `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_TIMEOUT` |
| Guardrails | `LLM_MAX_REQUESTS_PER_MINUTE`, `LLM_MAX_CONCURRENCY`, `LLM_MAX_PROMPT_CHARS`, `LLM_MAX_OUTPUT_CHARS` |
| Tracing | `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING` |
| Infrastructure | `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` |
| API tuning | `AUTO_APPROVE_STRONG_SIGNALS`, `IDEMPOTENCY_TTL_HOURS` (24), `SSE_KEEPALIVE_SECONDS` (15), `ALLOW_ORIGINS` |
| Frontend | `NEXT_PUBLIC_API_URL` |

## 21. Approvals

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Product owner | bsuraj-2699 | Approved |  |
| Engineering lead |  | Pending |  |
| Risk / compliance reviewer |  | Pending |  |
