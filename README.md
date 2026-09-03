<div align="center">

<img src="https://capsule-render.vercel.app/api?type=venom&color=0:0f172a,50:1e3a5f,100:6366f1&height=200&section=header&text=ALPHA&fontSize=58&fontColor=ffffff&fontAlignY=38&desc=Your%20AI%20Edge%20in%20Indian%20Markets%20%E2%80%94%20multi-agent%20equity%20analysis%20for%20NSE&descAlignY=62&descSize=14&descColor=a5b4fc&animation=fadeIn" width="100%" />

<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=18&duration=2800&pause=900&color=6366F1&center=true&vCenter=true&multiline=false&repeat=true&width=680&height=45&lines=Two-stage+pipeline+%E2%80%94+decision+first%2C+narration+after;Deterministic+rules+%2B+LLM+analysts+%2B+structured+debate;One+OpenAI-compatible+endpoint%2C+open-weight+models;Auditable+decisions+%E2%80%94+no+LLM+touches+position+sizing" alt="Typing" />

<br/><br/>

[![Demo](https://img.shields.io/badge/Loom-Watch%20Demo-06b6d4?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/c41e9064730e477580ed14c7983f6ee7)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-FF6B35?style=for-the-badge&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)

<br/>

![Status](https://img.shields.io/badge/Status-Production-6366f1?style=flat-square)
![Market](https://img.shields.io/badge/Market-NSE%20%C2%B7%20India-f59e0b?style=flat-square)
![Rules](https://img.shields.io/badge/Rules-36%20%2B%204%20overrides-22c55e?style=flat-square)
![Confidence](https://img.shields.io/badge/Confidence-7%20axis%20calibrated-06b6d4?style=flat-square)
![Decision](https://img.shields.io/badge/Decision%20Layer-Deterministic-a5b4fc?style=flat-square)

</div>

---

## ⚡ What it does

> Multi-agent financial analysis for **Indian equities (NSE)**. A deterministic rule engine produces the trade decision; LLM analysts, a structured bull/bear debate, and a judge produce the *explanation* — exposed through a non-blocking FastAPI backend (`202` + SSE) with an optional Next.js dashboard.

| | Layer | Role |
|:---:|:---|:---|
| 📐 | **Rule engine** | `RuleEvaluator` + `rules.json` — **LLM-free** scoring, override rules, signal thresholds |
| 🎯 | **Confidence** | Calibrated *P(setup reliable)* over 7 renormalised evidence axes — separate from the composite score |
| 🤖 | **Pillar analysts** | Fundamental, Technical, Sentiment, Macro, Risk — run in parallel via LangGraph |
| ⚖️ | **Debate** | Structured bull vs. bear cases built from the analyst reports |
| 🧑‍⚖️ | **Judge** | Rules fire first; the LLM adds narrative on top |
| 🧠 | **Market memory** | Intraday RAG over 24-dim market fingerprints — feeds confidence + explanation, **never the signal** |
| ✅ | **Decision** | Fully deterministic — position sizing, stop/target, human-review flags — **no LLM** |

### The one invariant

**The LLM never makes the trade decision.** Signal (`BUY`/`SELL`/`HOLD`), composite score, position size, stop-loss, target, overrides and risk controls come entirely from `RuleEvaluator` (`packages/core/rule_evaluator.py`) + `DecisionAgent` (`packages/agents/decision.py`) — pure Python, no LLM anywhere in the call graph.

This is enforced *structurally*, not by convention: the `AnalystNarrative` / `JudgeNarrative` schemas have **no score field**, and `DecisionAgent` imports no LLM code. `packages/agents/tests/test_fast_path.py` pins it — the fast-path signal must equal the full-graph signal for the same context.

---

## 🏗️ Architecture

### Two-stage execution (Time-To-Decision)

The API is **non-blocking**: `POST /api/analyze` returns `202 + run_id` immediately, and `RunManager` (`apps/api/runs.py`) drives the orchestrator on a background task while streaming lifecycle events over SSE.

```
  ┌─ STAGE 1 — critical path (deterministic, sub-ms compute) ────────────────┐
  │  market data → context build → intraday memory recall → rule engine      │
  │  → confidence → sizing / risk → ▐ DECISION EMITTED ▌                     │
  └──────────────────────────────────────────────────────────────────────────┘
                                    │  (decision already on the wire)
  ┌─ STAGE 2 — enrichment (off the critical path) ───────────────────────────┐
  │  mode-routed analysts ∥ → bull/bear debate → judge prose                 │
  │  CANNOT change signal / size / confidence                                │
  └──────────────────────────────────────────────────────────────────────────┘
```

| Method | Stage | Returns |
|:---|:---|:---|
| `Orchestrator.arun_fast` | 1 | `FastDecision` — decision + evaluation + rule summary + similar historical setups + `ttd_ms` |
| `Orchestrator.arun_enrich` | 2 | Analyst reports, bull/bear cases, judge narrative — reuses the already-built context |
| `Orchestrator.arun` | full graph | Compiles the whole LangGraph; used by tests and the human-review / interrupt path |

The full graph topology (`arun`) is unchanged:

```
                                 ┌──[ Fundamental Analyst ]──┐
                                 ├──[ Technical  Analyst  ]──┤
[ Parse ] ──► [ Context Build ] ─┼──[ Sentiment  Analyst  ]──┼──► [ Bull/Bear Debate ] ──► [ Judge ] ──► [ Decide ] ──► END
                                 ├──[ Macro      Analyst  ]──┤
                                 └──[ Risk       Analyst  ]──┘
```

### End-to-end run

1. **Client** calls `POST /api/analyze` with ticker, market (`IN`), optional `mode` and portfolio context → `202 Accepted` + `run_id`
2. **Idempotency** — for `short_term` / `long_term`, `sha256(ticker:market:mode:date)` maps to a fixed `run_id`; a duplicate POST returns the existing run with `idempotent_hit=True`. `intraday` mints a fresh id every time (no dedupe)
3. **RunManager** starts stage 1 on a background task and streams lifecycle events on the **event bus** (Redis, or in-memory fallback)
4. **Context build** (`ContextBuilder.build`) fetches 5 provider blocks concurrently under a **30 s global timeout** into one `context` dict; a timeout returns the *partial* context rather than failing the run
5. **Market memory** (intraday only, when `QDRANT_URL` is set) recalls similar historical fingerprints
6. **Rule engine** evaluates 36 scoring rules + 4 overrides against the context, weighted by the run mode
7. **Confidence + sizing** produce the final `Decision`; `decision` and `decision_ready` events fire, carrying `ttd_ms`
8. **Persistence** — actionable intraday outcomes become durable at TTD, *before* narration
9. **Enrichment** (stage 2) runs analysts → debate → judge and finalizes the run. Enrichment failure never loses the decision
10. **Audit** — completed runs write to `run_logs`; Redis backs idempotency, SSE fan-out, LangGraph checkpoints, strategy buckets, per-provider data cache and the Upstox token

**Human-in-the-loop:** `STRONG_BUY` / `STRONG_SELL` interrupt when `AUTO_APPROVE_STRONG_SIGNALS` is off. `POST /api/runs/{id}/approve` finalizes against the *stashed deterministic decision* — approve keeps it, anything else downgrades to `HOLD`. No graph replay.

### Scheduled & reactive paths

Same pipeline, different `run_id` prefix — all three bypass the daily idempotency cache by minting their own ids.

| Scheduler | Trigger |
|:---|:---|
| `IntradayScheduler` | Every **5 min** during NSE hours (09:15–15:30 IST, Mon–Fri) for the `intraday` bucket |
| `DailyScheduler` | Once per business day (default **10:00 IST**, from `rules.json` schedules) for `short_term` + `long_term` |
| `RetriggerSubscriber` | Reacts to Redis `retrigger:*` events (Upstox WS price/volume thresholds) with a 60 s cooldown |

---

## 📐 Rule Engine

`packages/core/rules.json` (**v2.0.1**, schema `2026-05-03`) is the single source of truth: **36 scoring rules + 4 override rules** across 8 categories.

| Category | Rules | | Category | Rules |
|:---|:---:|:---|:---|:---:|
| `fundamentals` | 5 | | `sentiment` | 5 |
| `balance_sheet` | 3 | | `macro` | 7 |
| `trend` | 3 | | `valuation` | 5 |
| `momentum` | 6 | | `risk` | 2 |

**Signal thresholds** (composite 0–100):

| `STRONG_SELL` | `SELL` | `HOLD` | `BUY` | `STRONG_BUY` |
|:---:|:---:|:---:|:---:|:---:|
| ≤ 14.99 | 15 – 44.99 | 45 – 62.99 | 63 – 84.99 | ≥ 85 |

**Expression grammar.** `rule_evaluator.py` ships a hand-rolled, injection-safe grammar — `AND` / `OR`, parentheses, `in [list]`, one-level attribute access, `abs()` — and **no `eval()`**. Its failure mode is silence: an unparseable side coerces to `None`, the comparison answers `False`, and the rule vanishes from the composite. `_eval_atom` therefore logs a warning when a *structural* expression fails, as distinct from ordinary missing data — treat that warning as a bug. Pinned by `packages/core/tests/test_expression_grammar.py`.

**Condition ladders are total.** Tiers are tried `strong_buy → buy → strong_sell → sell → neutral`, so each extreme is tested *before* the moderate tier that subsumes it. If nothing matches, the rule **abstains** — excluded from the composite like a skip, but tracked separately (`RuleResult.abstained`) so it doesn't count against `data_coverage_pct`: an abstention is a `rules.json` defect, not a data gap. `test_rule_ladders.py` sweeps every ladder for dead zones and checks the threshold bands are contiguous.

**Thin-evidence floor.** Below `_MIN_RULES_FOR_ACTIONABLE_SIGNAL` (**8**) evaluated rules the signal is forced to `HOLD` with an explanatory note. It only ever damps *toward* `HOLD` — it never manufactures a `BUY` or `SELL`.

### Run modes

Modes reshape which pillars contribute and which analysts run. Weights live in `rules.json` under `modes.<mode>.pillar_weights` (the literals in `packages/shared/config.py::_MODE_CONFIGS` are a fallback for an unreadable JSON — keep them in sync).

| Mode | Technical | Sentiment | Risk | Macro | Fundamental | Chart — primary / secondary / context | Lookback | Scheduler |
|:---|:---:|:---:|:---:|:---:|:---:|:---|:---:|:---|
| `intraday` | 0.40 | 0.30 | 0.30 | — | — | 5 min / 15 min / — | 78 bars | every 5 min |
| `short_term` | 0.48 | 0.20 | 0.20 | 0.12 | — | 1 day / 60 min / 1 week | 90 bars | daily 10:00 IST |
| `long_term` | 0.18 | 0.10 | 0.15 | 0.12 | 0.45 | 1 week / 1 month / 1 day | 104 bars | daily 10:00 IST |

`intraday` and `short_term` set `skip_screener=True` — the Screener.in fundamentals fetch is skipped entirely, since the fundamental pillar carries zero weight in those modes. Only `long_term` pays for it.

> Weights must use the five canonical pillar names and sum to 1.0, or the loader warns and silently keeps the built-in defaults. The 8 rule *categories* are derived from the 5 pillars via `PILLAR_TO_CATEGORIES` — never hand-write category weights. Note the `sentiment` pillar is only 45% sentiment (it splits 15/33 sentiment, 18/33 **valuation**), so trimming it also trims valuation.

---

## 🎯 Confidence

`Decision.confidence` is **not** the composite score. It is a calibrated *P(the setup is reliable)*, direction-independent, computed in `packages/core/confidence.py` and attached as `confidence_breakdown` for explainability.

| Axis | Weight | Measures |
|:---|:---:|:---|
| `rule_agreement` | 0.22 | Do the fired directional rules point one way? |
| `data_coverage` | 0.20 | Fraction of in-scope rules that had real data |
| `pillar_agreement` | 0.16 | Do the active pillars agree with the composite? |
| `historical_success` | 0.12 | Hit-rate of similar historical setups (RAG) |
| `indicator_agreement` | 0.12 | Do the core technical indicators agree? |
| `rule_consistency` | 0.10 | Do overrides / skips undercut the score? |
| `regime_confidence` | 0.08 | Does the market regime support the direction? |

Axes with no evidence (no historical memories, a pillar with no technicals) are **dropped and their weight renormalised**, so absence of evidence neither inflates nor deflates the result. Confidence converges to the composite at full coverage with every axis agreeing, and diverges downward on thin or conflicting data.

---

## 🧠 Market Memory — intraday RAG

`packages/rag/market_memory.py` stores completed market situations as a **24-dimension numeric fingerprint** (normalised indicators, derivatives, breadth, regime) in Qdrant with COSINE similarity, plus an in-memory cosine fallback so it works — and tests — without a running Qdrant.

- Similarity is computed over the numeric fingerprint, **not text embeddings** — <5 ms, no model download, and semantically correct for comparing market states
- Only *high-quality completed* situations are stored: an actionable intraday signal that reached a known outcome. `HOLD`s and skipped runs are not remembered
- Recalled outcomes feed the `historical_success` confidence axis and the explanation — **never the signal**
- Wired only when `QDRANT_URL` is set; unset it and the intraday path simply runs without historical evidence

> The general `packages/rag` hybrid retriever (BM25 + embeddings) exists but is **not** on the live rules path.

---

## 🤖 LLM — one provider, open-weight models

Chat flows (**query parse**, pillar **analysts**, **debate**, **judge**) use **`instructor`** over **`litellm`** against **one** OpenAI-compatible endpoint. The default is **Groq** — free tier, fast inference, hosts open-weight models. Any other compatible host (NVIDIA NIM, OpenRouter, a local vLLM/Ollama `/v1`) works by changing the base URL.

Agents depend only on the `ChatProvider` interface — **no agent imports `litellm`/`instructor` or hardcodes a model id** (guarded by `test_model_provider.py`).

| Variable | Default | Meaning |
|:---|:---|:---|
| `LLM_API_BASE` | `https://api.groq.com/openai/v1` | OpenAI-compatible base URL |
| `LLM_API_KEY` | *(blank)* | Endpoint key. **Blank = fully offline** — templated prose, zero API calls |
| `LLM_MODEL` | `openai/gpt-oss-120b` | **Primary** model |
| `LLM_FALLBACK_MODEL` | `openai/gpt-oss-20b` | **Fallback**, tried automatically when the primary raises |
| `LLM_TIMEOUT` | `25` | Per-call timeout (seconds) |

`get_chat_provider()` builds both models, wraps them in `FailoverChatProvider` (primary → fallback on any error), then in `GuardedChatProvider`.

> [!WARNING]
> **Do not swap model ids without probing them first.** Both models must support **tool/function calling**, because instructor needs structured output; a model that cannot do it fails every call with `InstructorRetryException` rather than degrading. **Model ids are host-specific** — a name that is valid on one provider generally 404s on another, and a provider's public model list is not the same as what a given key may invoke, so ids must move together with `LLM_API_BASE`. Size is not a proxy for reliability in either direction: a model can be too small to satisfy the Pydantic schemas, while a larger id may simply not be available to you. Ids also get **withdrawn**, which returns **HTTP 410** — `is_model_retired_error` treats that as permanent, so failover skips straight to the fallback instead of burning instructor retries on a model that no longer exists. A fallback that cannot do structured output is worse than none — every failover burns the full timeout budget before failing anyway. Probe with a real `provider.complete(response_model=...)` call, not a plain chat completion.
>
> **Groq ids carry an `openai/` namespace** (`openai/gpt-oss-120b`), which collides with LiteLLM's provider-routing prefix. `_routed_model()` therefore sends `openai/openai/gpt-oss-120b`: LiteLLM strips one layer and Groq receives the full id. The double prefix is correct — see the comment in `packages/agents/model_provider.py` before "fixing" it.

### Guardrails & rate limiting

Every model call passes through `GuardedChatProvider` (`packages/agents/guardrails.py`). Guardrails never touch signal / score / size.

| Variable | Default | Meaning |
|:---|:---:|:---|
| `LLM_MAX_REQUESTS_PER_MINUTE` | `60` | Sliding-window RPM cap on model calls |
| `LLM_MAX_CONCURRENCY` | `4` | Semaphore on in-flight model calls (`.env.example` ships `6`) |
| `LLM_MAX_PROMPT_CHARS` | `24000` | Per-message input truncation |
| `LLM_MAX_OUTPUT_CHARS` | `4000` | Output truncation + control-char stripping; `confidence` clamped to `[0,1]` |

### Tracing

Set `LANGSMITH_API_KEY` and `packages/shared/tracing.py` enables the LiteLLM **LangSmith** callback — every model call (prompt, response, tokens, latency) lands under `LANGSMITH_PROJECT`. `init_tracing()` is called from the API lifespan and the instructor client factory. No key → no-op, so offline and CI runs are unaffected.

| Variable | Default |
|:---|:---|
| `LANGSMITH_API_KEY` | *(blank — disabled)* |
| `LANGSMITH_PROJECT` | `alpha-fin-agent` |
| `LANGSMITH_TRACING` | `true` |
| `LANGSMITH_ENDPOINT` | *(optional, self-hosted)* |

---

## 🌐 API Surface

Interactive docs at `/docs`. Everything under `/api`; `IN` is the only accepted market (anything else → `400`).

| Method | Path | Purpose |
|:---|:---|:---|
| `POST` | `/api/analyze` | Start a run → **`202`** + `run_id` (+ `idempotent_hit`, chart config) |
| `GET` | `/api/runs/{run_id}` | Full state snapshot |
| `GET` | `/api/runs/{run_id}/stream` | **SSE** event stream |
| `POST` | `/api/runs/{run_id}/approve` | Resume an interrupted (human-review) run → `202` |
| `GET` | `/api/price/{ticker}` | OHLC for the analyze-page chart (`?market=IN&interval=1d&lookback_days=200`) |
| `GET` · `POST` | `/api/watchlist` | List / add (deduped on `ticker`+`market`) |
| `GET` | `/api/portfolio` | Current positions |
| `GET` | `/api/buckets` | All strategy buckets |
| `GET` · `POST` · `PUT` | `/api/buckets/{mode}` | Read / add to / replace a mode's bucket |
| `GET` | `/health` | Per-service status — `ok` / `degraded` / `not_configured` |

**SSE event types:** `agent_start` · `agent_complete` · `thinking` · `decision` · `decision_ready` (carries `ttd_ms`) · `interrupted` · `analysis_complete` · `error`. A keep-alive comment is emitted every `SSE_KEEPALIVE_SECONDS`.

---

## 📁 Repository Layout

| Path | Role |
|:---|:---|
| `apps/api` | FastAPI — analyze runs, SSE, watchlist/portfolio, buckets, schedulers, persistence |
| `apps/web` | Next.js 15 dashboard — analyze flow, execution DAG, runs, watchlist, charts |
| `packages/core` | `RuleEvaluator` + `rules.json` + `confidence.py` — **LLM-free** |
| `packages/data` | Providers (Upstox, Screener, NSE, Yahoo, GDELT) + `ContextBuilder` |
| `packages/agents` | Orchestrator, pillar analysts, debate, judge, decision, provider layer, guardrails |
| `packages/rag` | Intraday market memory + hybrid retrieval (Qdrant + BM25) |
| `packages/shared` | Schemas, mode config, ticker registry, observability, tracing |
| `eval/` | Offline scenario / backtest harness (**not** used by the live API) |
| `infra/` | Docker Compose — Postgres (Timescale), Redis, Qdrant only |
| `scripts/` | Critical-path benchmark, Excel export, context debug |
| `render.yaml` | Render Blueprint for deploying `apps/api` |

### Context data — Upstox instrument master

Upstox addresses instruments by `<SEGMENT>|<ISIN>` (e.g. `NSE_EQ|INE002A01018`), and both the historical-candle API and the Company Fundamentals API need that ISIN. `packages/data/providers/upstox_instruments.py` downloads the published instrument master, filters to cash-equity segments and indexes symbols **both verbatim and normalized** (uppercase, alphanumerics only) so internal forms like `BAJAJAUTO` resolve to the exchange symbol `BAJAJ-AUTO`. NSE is preferred over BSE on dual listings. Cached in Redis + in-process for 24 h, degrading to the static ticker registry if the download fails.

---

## 🛠️ Tech Stack

<div align="center">

[![Skills](https://skillicons.dev/icons?i=python,fastapi,nextjs,react,ts,tailwind,nodejs,postgres,redis,docker&theme=dark)](https://skillicons.dev)

![LangGraph](https://img.shields.io/badge/LangGraph-FF6B35?style=for-the-badge&logoColor=white)
![LiteLLM](https://img.shields.io/badge/LiteLLM-1C3C3C?style=for-the-badge&logoColor=white)
![instructor](https://img.shields.io/badge/instructor-4B32C3?style=for-the-badge&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-1C3C3C?style=for-the-badge&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?style=for-the-badge&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logo=groq&logoColor=white)
![GPT-OSS](https://img.shields.io/badge/GPT--OSS%20120B-412991?style=for-the-badge&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)
![Upstox](https://img.shields.io/badge/Upstox-5B2C8D?style=for-the-badge&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)

</div>

---

## ⚙️ Configuration

```bash
cp .env.example .env
```

| Area | Variables |
|:---|:---|
| **Data** | `UPSTOX_API_KEY` / `_SECRET` / `_ACCESS_TOKEN` / `_REFRESH_TOKEN` / `_REDIRECT_URI`, optional `SCREENER_SESSION_COOKIE` |
| **LLM** | `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_TIMEOUT` |
| **Guardrails** | `LLM_MAX_REQUESTS_PER_MINUTE`, `LLM_MAX_CONCURRENCY`, `LLM_MAX_PROMPT_CHARS`, `LLM_MAX_OUTPUT_CHARS` |
| **Tracing** | `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_TRACING` |
| **Infra** | `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` — unset falls back to in-memory where possible; `/health` reports what's active |
| **API tuning** | `AUTO_APPROVE_STRONG_SIGNALS`, `IDEMPOTENCY_TTL_HOURS` (24), `SSE_KEEPALIVE_SECONDS` (15), `ALLOW_ORIGINS` (comma-separated; `*` dev only) |
| **Frontend** | `NEXT_PUBLIC_API_URL` in `apps/web/.env.local` |

> [!NOTE]
> `infra/docker-compose.yml` maps Qdrant to host ports **6335/6336** (container 6333/6334) to avoid clashing with a stray local Qdrant on the default port. `QDRANT_URL` must match — `.env.example` ships `http://localhost:6335`.

**Upstox tokens** refresh automatically: the API lifespan exchanges once on boot, then re-runs daily at **09:00 IST** (03:30 UTC, when Upstox tokens expire). The new token lands in Redis, so it propagates without a process restart.

### Context data vs. "rules skipped"

In the UI or logs, **"rules skipped"** means the evaluator did not have the required **context fields** — a provider timed out or rate-limited. It does **not** mean an LLM call failed: narrative uses whatever context exists, and scores come from the rules that could run. Skipped rules drop out of *both* the numerator and the denominator, so the 0–100 range is preserved; their absence is reported via `data_coverage_pct`, not via score depression.

Hardening already in place:

- **NIFTY 50** OHLC for trend/SMA resolves to the Upstox *index* symbol `NSE_INDEX|Nifty 50`, not an equity `NSE_EQ|…` key
- **GDELT** returns neutral sentiment fields on HTTP errors or **429** instead of skipping every sentiment rule when the public API throttles
- A few risk inputs (`vix`, `beta`) are backfilled with neutral defaults

### Local debugging

- **`scripts/debug_context.py`** — loads the root `.env` and builds a default `ContextBuilder` context for a ticker (default `TCS` / `IN`); useful for checking which keys actually reached the evaluator
- **`scripts/benchmark.py`** — measures the deterministic TTD critical path offline with a stubbed context builder, so the number is stable run-to-run

---

## 🚀 Commands

**Prerequisites:** Python ≥ 3.11 · [`uv`](https://docs.astral.sh/uv/) · Node.js + npm · Docker. On Windows the interpreter is `.venv/Scripts/python.exe`.

```bash
# one-shot setup (Python deps + tooling)
make setup                  # = uv sync --all-extras

# infrastructure ONLY (no app) — Postgres : 5432 · Redis : 6379 · Qdrant : 6335/6336
make docker-up              # = docker compose -f infra/docker-compose.yml up -d
make docker-down

# API — from repo root, so apps/ and packages/ resolve
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
# docs: http://localhost:8000/docs   ·   health: GET /health

# frontend
cd apps/web && npm install && npm run dev
# build: npm run build   ·   lint: npm run lint   ·   types: npm run typecheck

# quality gates
make lint                   # ruff check + ruff format --check
make type                   # mypy (strict)
make test                   # core rule smoke script + full pytest

# deterministic critical-path latency (offline, no network, no LLM)
uv run python scripts/benchmark.py
uv run python scripts/benchmark.py --json out.json --iters 2000

# run history → Excel (needs DATABASE_URL)
uv run python scripts/export_runs_to_excel.py --out exports/runs_export.xlsx
```

### Testing notes

`pyproject.toml` sets default `addopts` = coverage + `-m "not integration and not live"`, with `testpaths = packages, apps, eval`.

| Marker | Meaning |
|:---|:---|
| `integration` | Hits live market-data APIs (needs credentials) — **excluded by default** |
| `live` | Hits live LLM APIs (needs an LLM key) — **excluded by default** |
| `requires_env(*names)` | Skipped unless those env vars are set |

Offline runs are the norm: with no LLM key configured every narrator falls back to templated prose, so most of the suite passes with no external service at all.

To run a **single test** without the coverage / marker machinery:

```bash
uv run pytest packages/core/tests/test_confidence.py::test_confidence_is_zero_to_hundred -o addopts="" --no-cov
```

> [!IMPORTANT]
> **Known-failing tests are pre-existing and environmental, not regressions.** Some `eval/scenarios/*` fixtures encode US tickers with signals that drifted from `rules.json`, and several `apps/api` tests POST US-market tickers this IN-only deployment rejects with `400`. Verify a "failure" reproduces on a clean checkout before treating it as yours.
>
> Three eval fixtures are left failing **deliberately**:
> - `ge_2018_dividend_cut` expects `SELL`, which only held because `OVR-O3` force-sold it. That override was removed — its `dividend_cut_announced` input measured a payout-*ratio* decline, not an announced cut, and its `INCOME_PORTFOLIO` scope was never enforced — so the scenario now scores 56.7 → `HOLD`.
> - `peloton_2022_post_pandemic_collapse` now scores 12.4 and reads `STRONG_SELL` where the fixture expects `SELL`.
> - `meta_2022_ad_slowdown` now produces the *correct* `SELL` (it was `HOLD`) but trips the fixture's `expected_max` confidence cap of 45, because rules that used to abstain now agree with each other.
>
> All three encode the old compressed behaviour; re-baseline them when someone owns those scenarios.

---

## ☁️ Deployment — Oracle Cloud + Vercel
### 1. API on Oracle cloud
1.The FastAPI backend runs on an Oracle Cloud Compute instance. The repository is deployed to the instance and the API is started with Uvicorn as a long-running process.
2.Provision an Oracle Cloud Compute instance and connect to it through SSH
3.Clone the GitHub repository on the Oracle Cloud instance
4.Install Python dependencies and configure the backend .env
5.Configure the required environment variables, including LLM_API_KEY, UPSTOX_*, DATABASE_URL, REDIS_URL / QDRANT_URL where applicable
6.Start the FastAPI application from the repository root
7.Keep the API process running continuously and expose the API port through the Oracle Cloud network/security rules
8.Set ALLOW_ORIGINS to the Vercel frontend origin, e.g. https://your-app.vercel.app

###Backend start command:
uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --workers 1

### 2. Frontend on Vercel
1.Import the GitHub repository into Vercel
2.Root Directory: apps/web — critical, don't use the monorepo root
3.Build: default npm run build
4.Add the environment variable NEXT_PUBLIC_API_URL
5.Set NEXT_PUBLIC_API_URL to the Oracle Cloud backend URL, with no trailing slash, e.g. https://your-api-domain.com or http://<oracle-cloud-public-ip>:8000 when using the API directly
6.Redeploy the frontend after changing the environment variable

### 3. Smoke test

Open `https://<your-vercel-app>.vercel.app/analyze` and run a ticker. If analyze fails, check the Network tab for CORS/404 and the Render API logs.

---

## 🔄 Typical Local Workflow

```bash
make docker-up
cp .env.example .env                          # + apps/web/.env.local if needed
make setup

# Terminal A — API
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal B — UI
cd apps/web && npm install && npm run dev
```

Open the UI and run an analysis, or call `POST /api/analyze` directly from `http://localhost:8000/docs`:

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"TCS","market":"IN","mode":"short_term"}'
# -> 202 {"run_id":"...","idempotent_hit":false,...}

curl -N http://localhost:8000/api/runs/<run_id>/stream
```

---

## 📚 Further Reading

| Topic | File |
|:---|:---|
| Two-stage execution & Time-To-Decision | `packages/agents/orchestrator.py` (`arun_fast`, `arun_enrich`) |
| Provider layer, failover, model ids | `packages/agents/model_provider.py`, `packages/agents/llm_provider.py` |
| Guardrails & rate limiting | `packages/agents/guardrails.py` |
| Rule grammar, ladders & overrides | `packages/core/rule_evaluator.py`, `packages/core/rules.json` |
| Calibrated confidence axes | `packages/core/confidence.py` |
| Intraday market memory (RAG) | `packages/rag/market_memory.py` |
| Context assembly & providers | `packages/data/context_builder.py`, `packages/data/providers/` |
| Run lifecycle, SSE, human review | `apps/api/runs.py`, `apps/api/routes/runs.py` |
| API lifespan (schedulers, Redis, Postgres) | `apps/api/main.py` |
| Mode config & pillar weights | `packages/shared/config.py` |
| Render API deploy | [`render.yaml`](render.yaml) |

---

<div align="center">

*Deterministic where it matters. AI where it helps. Built for NSE.*

<br/>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:6366f1,100:06b6d4&height=120&section=footer&text=signal%20over%20noise&fontSize=15&fontColor=e2e8f0&fontAlignY=68" width="100%" />

</div>
