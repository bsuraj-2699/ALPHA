# ALPHA - Your AI Edge in Indian Markets

Multi-agent financial analysis for **Indian equities (NSE)**. The system combines deterministic rule scoring with LLM analysts, a structured debate, and a final mechanical decision layer exposed through a FastAPI backend and optional Next.js UI.

## Repository layout

| Path | Role |
|------|------|
| `apps/api` | HTTP API: analyze runs, SSE progress, watchlist/portfolio, buckets, schedulers, persistence |
| `apps/web` | Next.js dashboard (analyze flow, runs, watchlist, charts) |
| `packages/core` | `RuleEvaluator` + `rules.json` — **LLM-free** scoring and overrides |
| `packages/data` | Market data providers (Upstox, Yahoo, screener.in, etc.) and `ContextBuilder` |
| `packages/agents` | LangGraph **Orchestrator**, pillar analysts, debate, judge, decision |
| `packages/rag` | Optional hybrid retrieval (Qdrant + BM25) for judge context |
| `packages/shared` | Schemas, mode config, observability helpers |
| `infra/` | Docker Compose for **Postgres (Timescale)**, **Redis**, **Qdrant** only |
| `eval/` | Offline scenario / backtest harness (not used by the live API) |
| `scripts/` | Utilities (e.g. Excel export of run history) |

---
## Live URL - https://fin-agent-drab.vercel.app/ 

## Agent Demo video link - https://www.loom.com/share/c41e9064730e477580ed14c7983f6ee7

## How the agent runs (end-to-end)

1. **Client** calls `POST /api/analyze` with ticker, market (`IN`), optional `mode`, and optional portfolio context.
2. **Idempotency**: Same ticker + market + **UTC calendar day** maps to a fixed `run_id` (16-char hex). A duplicate POST returns the existing run with `idempotent_hit=True` instead of starting a second graph.
3. **RunManager** starts a **LangGraph** invocation on the shared **Orchestrator** and streams lifecycle events on the **event bus** (Redis when configured, else in-memory).
4. **Graph** (high level):

   ```text
   parse → context_build → [fundamental | technical | sentiment | macro | risk] (parallel)
                        → debate (bull ∥ bear) → judge → decide → END
   ```

5. **Context build** (`ContextBuilder`) pulls OHLC, fundamentals, news/sentiment hooks, etc., from configured providers into one structured context dict.
6. **Analysts** (OpenAI / instructor, per pillar) produce `AnalystReport` payloads in parallel where the graph allows.
7. **Debate** runs bull and bear agents on those reports to produce structured bull/bear cases.
8. **Judge** calls **`RuleEvaluator.evaluate()`** first — signals, scores, and **override rules** from `rules.json` are **deterministic**. The LLM then adds narrative and may be skipped or templated when score-only overrides fire. Optional **RAG** can enrich the judge if Qdrant is configured.
9. **Decision** (`DecisionAgent`) is **fully deterministic**: position sizing bands, stop/target from context, `requires_human_review`, and low–data-coverage caps — **no LLM** — so “moving money” logic stays auditable.
10. **Persistence**: When `DATABASE_URL` is set, completed runs are written to **`run_logs`**; intraday-only rows may also hit **`intraday_signals`**. Redis backs idempotency, SSE fan-out, LangGraph **checkpoints** (resume), **bucket** storage for schedulers, and **Upstox token** refresh via cache.

Scheduled and reactive paths (same graph, different `run_id` prefix):

- **IntradayScheduler**: every **5 minutes** during **NSE hours** (09:15–15:30 IST, Mon–Fri), runs tickers in the **intraday** bucket (`intraday-…` / `retrigger-…` style ids — not the daily idempotency key).
- **DailyScheduler**: once per business day (default **10:00 IST**, configurable via `rules.json` schedules) for **short_term** and **long_term** buckets.
- **RetriggerSubscriber** (Redis): reacts to **`retrigger:*`** events (e.g. from Upstox WS thresholds) with cooldowns to spawn intraday runs.

---

## Configuration

Copy the root template and fill in keys your deployment needs:

```bash
cp .env.example .env
```

Important variables (see `.env.example` for the full list):

- **LLM**: `OPENAI_API_KEY` (and/or `ANTHROPIC_API_KEY` if used elsewhere in the stack).
- **Data**: Upstox keys/tokens; optional `SCREENER_SESSION_COOKIE`.
- **Infra**: `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` — if unset, the API falls back to in-memory stores where possible; `/health` reports what is configured.

Frontend API base URL (for the browser):

```bash
cp apps/web/.env.example apps/web/.env.local
# Edit NEXT_PUBLIC_API_URL if the API is not on http://localhost:8000
```

Optional API env (see `apps/api/config.py`):

- `AUTO_APPROVE_STRONG_SIGNALS`, `OPENAI_MODEL`, `IDEMPOTENCY_TTL_HOURS`, `SSE_KEEPALIVE_SECONDS`, `ALLOW_ORIGINS` (comma-separated; use `*` only in dev).

---

## Commands

### Prerequisites

- **Python ≥ 3.11**, [**uv**](https://docs.astral.sh/uv/)
- **Node.js** + **npm** (for `apps/web`)
- **Docker** (for Postgres / Redis / Qdrant via Compose)

### One-shot setup (Python deps + linters/tests tooling)

```bash
make setup
# equivalent:
uv sync --all-extras
```

### Infrastructure (Docker)

Compose **does not** build or run the API or the frontend — only backing services:

```bash
make docker-up
# equivalent:
docker compose -f infra/docker-compose.yml up -d
```

Services: **Postgres** on `5432`, **Redis** on `6379`, **Qdrant** on `6333`/`6334` (defaults align with `.env.example`).

Stop:

```bash
make docker-down
```

### API (Uvicorn)

From the **repository root** (so `apps` and `packages` resolve correctly):

```bash
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: `http://localhost:8000/docs`
- Health / subsystem status: `GET /health`

### Frontend (Next.js)

```bash
cd apps/web
npm install
npm run dev
```

### App is live at  `https://fin-agent-drab.vercel.app/` and calls the API at `NEXT_PUBLIC_API_URL` (`https://fin-agent-production-9c25.up.railway.app/`).

### Agent Demo video link - https://www.loom.com/share/c41e9064730e477580ed14c7983f6ee7

Production-style build:

```bash
cd apps/web
npm run build
npm run start
```

### Tests

```bash
make test
# runs the core rule smoke script + pytest
```

### Optional: run history export (Excel)

Requires `DATABASE_URL` and dev deps (`uv sync` includes `openpyxl` / `tzdata` in dev):

```bash
uv run python scripts/export_runs_to_excel.py --out exports/runs_export.xlsx
```

---

## Typical local workflow

1. `make docker-up`
2. Configure `.env` (and `apps/web/.env.local` if needed)
3. `make setup`
4. Terminal A: `uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000`
5. Terminal B: `cd apps/web && npm install && npm run dev`
6. Open the UI, run an analysis, or call `POST /api/analyze` from `http://localhost:8000/docs`

---

## Further reading

- Orchestrator graph and prompts: `packages/agents/orchestrator.py`, `packages/agents/prompts/`
- Rule grammar and overrides: `packages/core/rule_evaluator.py`, `packages/core/rules.json`
- API lifespan (schedulers, Redis, Postgres): `apps/api/main.py`
