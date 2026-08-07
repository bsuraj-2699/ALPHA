# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

ALPHA is a multi-agent financial analysis system for **Indian equities (NSE only)**. A FastAPI backend runs a LangGraph pipeline that combines a deterministic rule engine with LLM analysts, exposed over a non-blocking API (202 + SSE) with an optional Next.js UI.

## The one invariant that governs everything

**The LLM never makes the trade decision.** Signal (BUY/SELL/HOLD), composite score, position size, stop-loss, target, overrides, and risk controls are produced entirely by `RuleEvaluator` (`packages/core/rule_evaluator.py`) + `DecisionAgent` (`packages/agents/decision.py`) — pure Python, no LLM. LLMs (analysts, debate, judge) only write **narrative/explanation**. This is enforced structurally: `AnalystNarrative`/`JudgeNarrative` schemas have no score field, and `DecisionAgent` imports no LLM code.

When editing the pipeline, **preserve this separation**. Never let a model output flow into a signal, score, or size. Determinism is verified by `packages/agents/tests/test_fast_path.py` (fast-path signal must equal the full-graph signal).

## Commands

Prereqs: Python ≥3.11, [uv](https://docs.astral.sh/uv/), Node+npm (web), Docker (backing services). On Windows the interpreter is `.venv/Scripts/python.exe`.

```bash
make setup                 # uv sync --all-extras
make docker-up             # Postgres(5432) + Redis(6379) + Qdrant(6333) ONLY (no app)
make docker-down

# API (from repo root so apps/ and packages/ resolve)
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000   # docs: /docs, health: /health

# Web
cd apps/web && npm install && npm run dev        # build: npm run build; lint: npm run lint

make test                  # core rule smoke script + full pytest
uv run pytest              # honors pyproject addopts (see below)
uv run python scripts/benchmark.py               # deterministic critical-path latency (offline)
```

### Testing notes (important)

`pyproject.toml` sets default `addopts` = coverage + `-m "not integration and not live"`. Markers:
- `integration` — hits live market-data APIs (needs credentials); **excluded by default**.
- `live` — hits live LLM APIs (needs an LLM key); **excluded by default**.
- `requires_env(*names)` — skipped unless those env vars are set.

To run a **single test** without the coverage/marker machinery, override addopts:

```bash
uv run pytest packages/core/tests/test_confidence.py::test_confidence_is_zero_to_hundred -o addopts="" --no-cov
```

Offline runs are the norm: with no LLM key configured, every narrator falls back to templated prose, so most of the suite passes without any external service. `testpaths = packages, apps, eval`.

**Known-failing tests are pre-existing and environmental**, not regressions: some `eval/scenarios/*` fixtures encode US tickers with signals that drifted from `rules.json`, and several `apps/api` tests POST US-market tickers that this IN-only deployment rejects (400). Verify a "failure" reproduces on a clean checkout before treating it as yours.

One eval failure is **deliberate**: `eval/scenarios/ge_2018_dividend_cut.json` expects SELL, which only held because `OVR-O3` force-sold it. That override was removed (its `dividend_cut_announced` input measured a payout-*ratio* decline, not an announced cut, and its `INCOME_PORTFOLIO` scope was never enforced), so the scenario now scores 56.7 → HOLD. The fixture is intentionally left failing rather than re-baselined; retire or rewrite it when someone owns that scenario.

Two more are **stale fixtures the engine now outruns**, left failing on purpose. After the expression-grammar and tier-ordering fixes below, `peloton_2022_post_pandemic_collapse` scores 12.4 and reads STRONG_SELL where the fixture expects SELL, and `meta_2022_ad_slowdown` now produces the *correct* SELL (it was HOLD) but trips the fixture's `expected_max` confidence cap of 45, because rules that used to abstain now agree with each other. Both fixtures encode the old compressed behaviour; re-baseline them when someone owns those scenarios.

## Architecture

### Two-stage execution (Time-To-Decision)

The API is non-blocking: `POST /api/analyze` returns `202 + run_id`, and `RunManager` (`apps/api/runs.py`) drives the orchestrator on a background task while streaming lifecycle events over SSE.

- **Stage 1 — critical path** (`Orchestrator.arun_fast`): market data → context → intraday memory recall → rule engine → confidence → sizing/risk → **decision emitted**. Fully deterministic, sub-millisecond compute. Returns a `FastDecision` (decision + evaluation + rule summary + similar historical setups).
- **Stage 2 — enrichment** (`Orchestrator.arun_enrich`): analysts → debate → judge prose, reusing the already-built context. Runs *after* the decision is emitted; **cannot change signal/size/confidence**.

`Orchestrator.arun` still compiles the full LangGraph (`parse → context_build → [5 analysts ∥] → debate → judge → decide`) and is used by tests and the human-review/interrupt path. When adding pipeline behavior, decide whether it belongs on the critical path (`arun_fast`) or in enrichment.

Human-in-the-loop: STRONG_BUY/STRONG_SELL signals interrupt when `auto_approve_strong_signals` is off; `RunManager.approve` finalizes against the stashed deterministic decision (approve keeps it, anything else downgrades to HOLD) — no graph replay.

### Rule engine (`packages/core`)

`rules.json` is the source of truth: 36 scoring rules + 5 override rules across 8 categories (fundamentals, balance_sheet, trend, momentum, sentiment, valuation, macro, risk). `rule_evaluator.py` has a hand-rolled, injection-safe expression grammar (AND/OR, parens, `in [list]`, one-level attr access, `abs()` — no `eval()`). Rules skip when required context fields are absent (excluded from numerator and denominator). Run **modes** (`intraday`/`short_term`/`long_term`) reshape which pillars contribute via `category_weights()` and which analysts run.

**Condition ladders must be total, and a rule that matches no tier abstains.** Tiers are tried in the order `strong_buy → buy → strong_sell → sell → neutral`: first match wins, so each extreme is tested *before* the moderate tier whose condition subsumes it. If nothing matches, the rule abstains — excluded from the composite like a skip, but tracked separately (`RuleResult.abstained`) so it doesn't count against `data_coverage_pct`, since an abstention is a `rules.json` defect rather than a data gap. Abstention is a safety net, not the design: write `neutral` to cover the residual of the rule's input space. `packages/core/tests/test_rule_ladders.py` sweeps the ladders for dead zones and checks the threshold bands are contiguous.

A separate floor guards thin evidence: below `_MIN_RULES_FOR_ACTIONABLE_SIGNAL` (8) evaluated rules the signal is forced to HOLD with an explanatory note. It only ever damps toward HOLD, never manufactures a BUY or SELL.

**Be careful editing the expression grammar** — its failure mode is silence. An unparseable side coerces to `None`, the comparison answers `False`, no tier matches, and the rule vanishes from the composite with no error. Three such bugs (an attribute-path check that swallowed any arithmetic containing a decimal literal, `abs()` unsupported as a sub-term, and a greedy whole-token `abs(...)` shortcut) plus the tier misordering together mis-scored 74 of 103 bearish rule hits and made 14 of 36 rules abstain — which is what pinned nearly every run to HOLD. `_eval_atom` now logs a warning when a *structural* expression fails to evaluate, as distinct from ordinary missing data; treat that warning as a bug. Pinned by `packages/core/tests/test_expression_grammar.py`.

**Scoring weights live in `rules.json` only.** `modes.<mode>.pillar_weights` is read by `packages/shared/config.py` (`_pillar_weights_from_spec`); the `pillar_weights` literals in `_MODE_CONFIGS` are a *fallback* for when the JSON is unreadable, so keep them in sync. Weights must use the five canonical pillar names (`technical`, `sentiment`, `fundamental`, `macro`, `risk`) and sum to 1.0 — otherwise the loader warns and silently keeps the built-in defaults. The 8 rule *categories* are derived from the 5 pillars via `PILLAR_TO_CATEGORIES`; never hand-write category weights. Watch out: the `sentiment` pillar is only 45% sentiment (it splits 15/33 sentiment, 18/33 **valuation**), so trimming it also trims valuation.

### Confidence (`packages/core/confidence.py`)

`Decision.confidence` is a calibrated **P(setup reliable)** — NOT the composite score. It combines 7 renormalized evidence axes (data_coverage, rule/pillar/indicator agreement, regime, consistency, historical success) and is attached as `confidence_breakdown` for explainability. `composite_score` (raw signal strength) is a separate field.

### Model Provider Layer (`packages/agents/model_provider.py` + `llm_provider.py`)

Agents depend only on the `ChatProvider` interface — **no agent imports `litellm`/`instructor` or hardcodes a model id** (guarded by `test_model_provider.py`). The system uses **one** OpenAI-compatible provider (default **NVIDIA NIM**, `LLM_API_BASE`/`LLM_API_KEY`) serving open-weight models, with a **primary** (`LLM_MODEL`, default `meta/llama-3.1-8b-instruct`) and a genuine **fallback** (`LLM_FALLBACK_MODEL`, default `nvidia/nvidia-nemotron-nano-9b-v2`). `get_chat_provider()` builds both models, wraps them in `FailoverChatProvider` (primary → fallback on any error), then in `GuardedChatProvider`. Any other compatible host (Groq, OpenRouter, local vLLM/Ollama `/v1`) works by changing the base URL. Blank `LLM_API_KEY` → fully offline templated prose.

**Do not swap model ids without probing them first.** Both models must support tool/function calling, because instructor needs structured output. Most of the NIM catalogue does not: it either raises `InstructorRetryException` immediately, times out, or returns `404 "Function ... not found for account"` (the `/v1/models` list is NVIDIA's public catalogue, *not* what a given key may invoke — a model can be listed and still 404). Bigger is not better here: the 70b models are not invocable on this account, while `meta/llama-3.1-8b-instruct` returns valid structured narrative in **under 1s**. A fallback that cannot do structured output is worse than none — every failover burns the full timeout budget before failing anyway. Probe with a real `provider.complete(response_model=...)` call, not a plain chat completion.

### Guardrails & rate limiting (`packages/agents/guardrails.py`)

Every model call passes through `GuardedChatProvider`: an `AsyncRateLimiter` (sliding-window `LLM_MAX_REQUESTS_PER_MINUTE` + `LLM_MAX_CONCURRENCY` semaphore), input prompt truncation (`LLM_MAX_PROMPT_CHARS`), and output sanitisation (`LLM_MAX_OUTPUT_CHARS` truncation, control-char stripping, `confidence` clamped to `[0,1]`). Guardrails never touch signal/score/size — those remain deterministic.

### Tracing (`packages/shared/tracing.py`)

`init_tracing()` (called from the API lifespan and the instructor client factory) enables the LiteLLM **LangSmith** callback when `LANGSMITH_API_KEY` is set (`LANGSMITH_PROJECT`, `LANGSMITH_TRACING`). No key → no-op, so offline/CI runs are unaffected.

### Context & data (`packages/data`)

`ContextBuilder.build()` fetches 5 provider blocks concurrently under a global timeout (Upstox=quotes/OHLC, Screener=IN fundamentals, NSE=VIX/FII-DII/PCR/NIFTY, Yahoo=fallback+indices, GDELT=news sentiment) into one `context` dict — the god-object every analyst, the evaluator, and the override engine read. Missing fields become skipped rules; a few risk inputs (vix, beta) are backfilled with neutral defaults. IN-only: `market` must be `"IN"`. Inject a shared `RuleEvaluator` to avoid re-parsing `rules.json`.

### RAG market memory (`packages/rag/market_memory.py`) — intraday only

Historical market situations are stored as a 24-dim **numeric fingerprint** (normalized indicators/derivatives/breadth/regime) in Qdrant, with an in-memory cosine fallback so it works and tests without a running Qdrant. On intraday runs, similar past fingerprints are recalled and their outcomes feed the confidence `historical_success` axis and the explanation — **never the signal**. Wired only when `QDRANT_URL` is set (`apps/api/main.py`). (The general `packages/rag` hybrid retriever/BM25/embeddings exists but is not on the live rules path.)

### Persistence

- **Postgres** (`apps/api/db.py`): `run_logs` (audit) + `intraday_signals` (actionable intraday outcomes). In-memory fallbacks when `DATABASE_URL` unset.
- **Redis**: idempotency (ticker+market+UTC-day → fixed `run_id`), SSE fan-out, LangGraph checkpoints, strategy buckets, per-provider data cache, Upstox token.
- Schedulers (`apps/api/scheduler.py`): intraday every 5 min during NSE hours; daily once per business day; `RetriggerSubscriber` reacts to Redis `retrigger:*` events.

## Repo layout

`packages/core` (rules + evaluator + confidence, LLM-free) · `packages/data` (providers + ContextBuilder) · `packages/agents` (Orchestrator, analysts, debate, judge, decision, provider layer, guardrails) · `packages/rag` (market memory + retrieval) · `packages/shared` (schemas, mode config, observability, tracing) · `apps/api` (FastAPI, runs, events, persistence, schedulers) · `apps/web` (Next.js) · `eval` (offline scenario/backtest harness, not used by the live API) · `infra` (docker-compose for backing services).
