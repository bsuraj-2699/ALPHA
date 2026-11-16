# ALPHA — Product Requirements Document (Initial, v1.0)

**Product:** ALPHA — Multi-Agent Equity Analysis Platform **Document type:** Initial PRD (baseline scope and vision) **Version:** 1.0 · **Status:** Baseline for build approval **Product owner:** bsuraj-2699 (repository owner) **Basis:** Reconstructed on 16 November 2026 from the ALPHA repository (README, CLAUDE.md, rules.json changelog, schemas, evaluation harness, early-stage artefacts). Statements about original intent are inferred from those artefacts and marked as assumptions where evidence is indirect.

## 1. Purpose of this document

This PRD defines the original product vision, scope and requirements for ALPHA before the production hardening described in the Final PRD. It answers four questions: what problem is being solved, for whom, what the first release must do, and how success is judged. It is the reference point against which the Final PRD measures how far the product evolved.

## 2. Executive summary

Retail and semi-professional equity investors in India face an information-overload problem. A single stock decision requires reading financial statements, technical indicators, news, institutional flows, macro conditions and risk metrics, then reconciling signals that frequently conflict. Generic LLM chatbots can summarise this material but cannot be trusted to issue a repeatable, auditable BUY/SELL/HOLD call, because their output varies run to run and cannot be traced to evidence.

ALPHA is a multi-agent analysis system that turns a ticker into a structured recommendation: a signal (STRONG\_BUY, BUY, HOLD, SELL, STRONG\_SELL), a 0–100 composite score, a confidence value, a suggested position size, stop-loss and target, and a written rationale that cites the rules that fired. Specialist analyst agents examine five pillars in parallel, a bull and a bear agent argue the case, and a judge consolidates the result.

The defining design choice, present from the first version, is that **a rule-based scoring engine owns the quantitative output** while language models supply explanation. This keeps recommendations explainable and testable.

## 3. Problem statement

| # | Problem | Impact |
| --- | --- | --- |
| P1 | Evidence is scattered across fundamentals, technicals, sentiment, macro and risk sources | Analysis takes hours per stock and is inconsistently applied |
| P2 | Signals conflict (strong earnings, weak chart, hostile macro) | Investors default to gut feel or herd behaviour |
| P3 | LLM-only tools are non-deterministic and unauditable | The same question can yield different calls; no trace to evidence |
| P4 | No standard link between a signal and a disciplined action | Position size, stop-loss and exit rules are improvised |
| P5 | Tools built for US markets ignore Indian data realities (NSE, FII/DII flows, India VIX, Screener fundamentals) | Poor fit for Indian equity investors |

## 4. Vision and product principles

**Vision:** Give every Indian equity investor an institutional-style, explainable second opinion on any listed stock in minutes.

**Principles**

1. **Rules decide, language explains.** Signal, score, sizing and risk controls come from a declarative rule set. Models write narrative only.
2. **Explainability by default.** Every recommendation lists the rules and overrides that produced it.
3. **Graceful degradation.** Missing data lowers coverage, it does not crash the run.
4. **Risk before return.** Hard overrides (fraud, withdrawn guidance, concentration limits) outrank any score.
5. **Human in the loop for extremes.** The strongest signals require approval before they are final.
6. **Configuration over code.** Weights, thresholds and rules live in one versioned file.

## 5. Target users

| Persona | Description | Primary need |
| --- | --- | --- |
| Active retail investor | Trades or swing-trades Nifty 50 and Nifty Next 50 names | Fast, structured view on a ticker before acting |
| Long-term investor | Builds a portfolio over years | Fundamental and valuation-led view with risk context |
| Analyst / researcher | Screens ideas and validates theses | Traceable reasoning and evidence citations |
| Product owner / quant developer | Tunes the engine | Editable rules, repeatable evaluation |

## 6. Goals, non-goals and success metrics

### 6.1 Goals

- G1. Produce a five-level signal with a 0–100 composite score for any supported ticker.
- G2. Combine five analytical pillars: fundamental, technical, sentiment, macro and risk.
- G3. Make every decision traceable to named rules and overrides.
- G4. Translate signals into position size, stop-loss and target.
- G5. Provide a web interface with a live view of the analysis.
- G6. Prove determinism and signal quality offline through scenario tests and backtests.

### 6.2 Non-goals for v1.0

- Order placement or brokerage execution.
- Personalised financial advice or suitability assessment.
- Derivatives, commodities, crypto or mutual funds.
- Multi-user accounts, billing or mobile apps.
- Real-time tick-level trading automation.

### 6.3 Success metrics

| Metric | Target at release | Measurement |
| --- | --- | --- |
| Determinism | Identical inputs always produce an identical signal | Automated regression tests |
| Scenario accuracy | At least 90% of labelled scenarios return the expected signal | Frozen scenario suite |
| Explainability | 100% of decisions cite at least one rule ID | Output schema check |
| Data resilience | Run completes with partial data from any single provider failure | Fault-injection tests |
| Analysis time | Full analysis in under 2 minutes | End-to-end timing |
| Backtest sanity | Strategy reported against buy-and-hold on Sharpe, drawdown and hit rate | Backtest report |

## 7. Scope of the initial release

### 7.1 In scope

- Natural-language or ticker-based query parsing.
- Context assembly from market data, fundamentals, news and macro providers.
- Rule engine with 36 scoring rules across 8 categories and 5 override rules.
- Five pillar analyst agents, a bull/bear debate and a judge.
- Deterministic decision agent for sizing, stop-loss, target and review flag.
- Web dashboard with analysis view, run inspector, watchlist and portfolio.
- Offline evaluation harness: scenarios and backtester.

### 7.2 Market assumption

The original data model supports two market codes, US and IN. The framework and test fixtures include US examples, while provider selection and product direction centre on Indian equities. This ambiguity was later resolved in favour of India only (see Final PRD).

## 8. Functional requirements

Priority: **P0** must have, **P1** should have, **P2** nice to have.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-01 | Accept a ticker and market and start an analysis run | P0 |
| FR-02 | Parse free-text queries into ticker, market, intent and horizon | P1 |
| FR-03 | Build a single context object from price, fundamentals, news and macro data | P0 |
| FR-04 | Evaluate 36 weighted rules defined in a JSON rule file | P0 |
| FR-05 | Skip rules whose data is missing and exclude them from the score | P0 |
| FR-06 | Report data coverage as a percentage on every decision | P0 |
| FR-07 | Apply override rules that can force or block signals | P0 |
| FR-08 | Map composite score to five signals using fixed thresholds | P0 |
| FR-09 | Run five pillar analysts in parallel to write narrative per pillar | P0 |
| FR-10 | Generate a structured bull case and bear case from analyst output | P1 |
| FR-11 | Judge consolidates the debate into a final narrative citing rule IDs | P0 |
| FR-12 | Compute position size, stop-loss and target deterministically | P0 |
| FR-13 | Flag STRONG\_BUY and STRONG\_SELL for human review | P1 |
| FR-14 | Cap position size when data coverage is low | P1 |
| FR-15 | Expose the run result and reasoning trace to the web UI | P0 |
| FR-16 | Maintain a watchlist and a portfolio view | P1 |
| FR-17 | Persist a run audit log with signal, status, latency and token cost | P1 |
| FR-18 | Replay the pipeline over history and report performance vs benchmarks | P1 |
| FR-19 | Provide labelled scenario tests that fail on signal drift | P0 |
| FR-20 | Run offline with templated prose when no model key is present | P2 |

## 9. Scoring framework (v1.0)

### 9.1 Composite score

The composite is a weighted blend of six factor scores on a 0–100 scale:

| Factor | Weight | Content |
| --- | --- | --- |
| Fundamentals | 25% | Earnings growth, revenue growth, net margin, ROE/ROA, free cash flow |
| Technicals | 20% | Trend (62.5%) and momentum (37.5%) |
| Valuation | 18% | P/E, PEG, EV/EBITDA, P/B, dividend yield |
| Sentiment | 15% | News and market-participant signals |
| Risk | 12% | Beta and volatility |
| Macro | 10% | Rates, growth, inflation, sector rotation, currency |

Balance-sheet rules (debt-to-equity, liquidity, interest coverage) form a further category carrying 15% in the category table.

### 9.2 Signal thresholds

| Signal | Composite score | Suggested action |
| --- | --- | --- |
| STRONG\_BUY | 85 and above | Full position |
| BUY | 63 – 84.99 | Initiate and scale in |
| HOLD | 45 – 62.99 | Hold, no new entry |
| SELL | 15 – 44.99 | Trim, exit on bounces |
| STRONG\_SELL | below 15 | Full exit |

### 9.3 Override rules

| ID | Trigger | Effect |
| --- | --- | --- |
| OVR-O1 | Fraud allegation, material restatement or regulator investigation | Force STRONG\_SELL |
| OVR-O2 | Guidance withdrawn without explanation | Force SELL |
| OVR-O3 | Dividend cut announced (income-portfolio scope) | Force SELL |
| OVR-O4 | Price 8% or more below average purchase price | Pause BUY signals |
| OVR-O5 | Position 10% or more of portfolio | Block BUY |

### 9.4 Decision mechanics

| Signal | Target position size |
| --- | --- |
| STRONG\_BUY | 8% of portfolio |
| BUY | 4% |
| HOLD | 0% (no new entry) |
| SELL | 2% (trim target) |
| STRONG\_SELL | 0% (full exit) |

Stop-loss is set 8% below entry for BUY signals. Target price uses analyst consensus when available, otherwise entry plus 20%. No position may exceed 10% of the portfolio.

In v1.0, the confidence value shown to users was derived from the composite score. Separating confidence from score was identified as an improvement during build.

## 10. Initial solution architecture

The initial design is a single sequential pipeline built on LangGraph:

**Parse → Context build → five analysts in parallel → Bull/Bear debate → Judge → Decide → End**

| Layer | Responsibility |
| --- | --- |
| Data layer | Providers for quotes and OHLC (Upstox, Yahoo Finance), Indian fundamentals (Screener.in), NSE market data (India VIX, FII/DII flows, put-call ratio), and news sentiment (GDELT) |
| Rule engine | Declarative rules, hand-written expression grammar (no use of eval), weighted aggregation |
| Agent layer | Pillar analysts, debate, judge, deterministic decision agent |
| Model layer | Hosted LLM accessed through a provider abstraction so agents never depend on a specific vendor (the evaluation harness references an Anthropic key, indicating an Anthropic-hosted model in the original design) |
| API | FastAPI service returning run results and reasoning steps |
| UI | Next.js dashboard with dark theme, analysis view, run trace, watchlist and portfolio |
| Storage | PostgreSQL run log, Redis for caching and state, Qdrant for retrieval |
| Evaluation | Offline scenario suite and day-by-day backtester with HTML report |

**Initial characteristic:** the decision was produced at the end of the pipeline, after model narration, so response time was bound to model latency. This became the main performance finding that drove the two-stage redesign.

## 11. Non-functional requirements

| Category | Requirement |
| --- | --- |
| Determinism | The same context must always yield the same signal, score and sizing |
| Safety | No model output may alter signal, score, size, stop or target |
| Performance | Complete analysis under 2 minutes at the 95th percentile |
| Reliability | Provider failure yields partial context, never a failed run |
| Security | No arbitrary code evaluation; secrets via environment variables |
| Observability | Every run logged with status, latency, token usage and cost |
| Testability | Core logic runnable offline with no external services |
| Maintainability | Strict typing, linting and a unit test suite on core packages |
| Portability | Run locally with Docker for backing services; deployable to a standard cloud host |

## 12. User experience requirements

- **Dashboard:** quick-analyse entry, market clock, recent runs.
- **Analysis view:** live pipeline progress, signal card, pillar scores and radar, analyst narratives, bull/bear panel, price chart.
- **Run inspector:** execution graph and timeline of agent steps.
- **Watchlist and portfolio:** manage tracked tickers and positions.
- **Visual language:** dark mode, green for buy, red for sell, amber for neutral.

## 13. Assumptions, dependencies and risks

**Assumptions**

- Free-tier data and model providers are adequate for a first release.
- Nifty 50 and Nifty Next 50 coverage is sufficient to prove value.
- Users treat output as decision support, not advice.

**Dependencies:** Upstox API and daily token refresh, Screener.in page structure, NSE public endpoints, GDELT public API, a hosted LLM endpoint with structured-output support.

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Silent rule failures distort scores | Medium | High | Warnings on structural expression errors; ladder tests |
| Provider rate limits or outages | High | Medium | Caching, timeouts, neutral fallbacks, partial context |
| Model unavailable or retired | Medium | Medium | Primary and fallback models; offline templated prose |
| Slow response due to narration on critical path | High | High | Separate decision from narration (addressed in v2) |
| Regulatory exposure from perceived advice | Medium | High | Decision-support positioning and disclaimers; legal review before public launch |
| Overfitting rules to historical scenarios | Medium | Medium | Frozen scenarios plus out-of-sample backtests |

## 14. Release plan

| Milestone | Deliverables |
| --- | --- |
| M1 — Core engine | Rule file, evaluator, thresholds, overrides, unit tests |
| M2 — Data layer | Providers, context builder, caching, rate limiting |
| M3 — Agents | Analysts, debate, judge, decision agent, model abstraction |
| M4 — API and UI | FastAPI service, run storage, Next.js dashboard |
| M5 — Evaluation | Scenario suite, backtester, benchmark comparison |
| M6 — Beta | Deployment, smoke tests, owner review |

## 15. Open questions at baseline

1. Should the product support US markets, or focus on India?
2. Should confidence be a separate calibrated measure rather than the composite score?
3. Should model narration block the decision?
4. Should scoring weights differ by holding horizon?
5. How should historical analogues be used without letting them drive the signal?

*These questions are answered in the Final PRD.*

## 16. Approvals

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Product owner | bsuraj-2699 | Pending |  |
| Engineering lead |  | Pending |  |
| Risk / compliance reviewer |  | Pending |  |
