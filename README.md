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
| `render.yaml` | [Render](https://render.com) Blueprint for deploying **`apps/api`** as a Python web service |
| `eval/` | Offline scenario / backtest harness (not used by the live API) |
| `scripts/` | Utilities (Excel export of run history, optional context debug script) |

---

## Links

- **Demo (Loom)**: https://www.loom.com/share/c41e9064730e477580ed14c7983f6ee7
- **Live deployment** (optional): add your public URL here when hosted.

## How the agent runs (end-to-end)

1. **Client** calls `POST /api/analyze` with ticker, market (`IN`), optional `mode`, and optional portfolio context.
2. **Idempotency**: Same ticker + market + **UTC calendar day** maps to a fixed `run_id` (16-char hex). A duplicate POST returns the existing run with `idempotent_hit=True` instead of starting a second graph.
3. **RunManager** starts a **LangGraph** invocation on the shared **Orchestrator** and streams lifecycle events on the **event bus** (Redis when configured, else in-memory).
4. **Graph** (high level):

   ```text
   parse → context_build → [fundamental | technical | sentiment | macro | risk] (parallel)
                        → debate (bull ∥ bear) → judge → decide → END
   ```

5. **Context build** (`ContextBuilder`) pulls OHLC, fundamentals, news/sentiment hooks, etc., from configured providers into one structured context dict. If a provider fails or rate-limits, some fields may be absent; the **rule engine** then marks individual rules as *skipped* (missing required inputs). That is separate from the LLM: narrative uses whatever context exists; scores come from rules that could run.
6. **Analysts** (per pillar) call an **instructor** client backed by **LiteLLM** so structured narratives work with **OpenAI, Anthropic, Gemini, Mistral, or Groq** depending on which API key is configured (see [LLMs](#llms-multi-provider) below).
7. **Debate** runs bull and bear agents on those reports to produce structured bull/bear cases (same LLM stack as analysts).
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

- **Data**: Upstox keys/tokens; optional `SCREENER_SESSION_COOKIE`.
- **Infra**: `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` — if unset, the API falls back to in-memory stores where possible; `/health` reports what is configured.

### LLMs (multi-provider)

Chat flows (**query parse**, pillar **analysts**, **debate**, **judge**) use **`instructor`** with **`litellm`** as the completion backend. Set **at least one** of these (non-empty) API keys:

| Variable | Provider |
|----------|----------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Google Gemini (AI Studio) |
| `MISTRAL_API_KEY` | Mistral |
| `GROQ_API_KEY` | Groq |

Resolution logic lives in `packages/agents/llm_provider.py`:

- **`LLM_PROVIDER_PRIORITY`** (optional): comma-separated order, default `openai,anthropic,gemini,mistral,groq`. The **first** provider in this list that has a configured key is used for all chat steps.
- **`LLM_MODEL`** (optional): force a single LiteLLM model id for every chat call (must match the active provider), e.g. `gpt-4o-mini`, `anthropic/claude-3-5-sonnet-20241022`, `gemini/gemini-2.0-flash`.
- **`OPENAI_MODEL`** (optional): when the active provider is **OpenAI** and `LLM_MODEL` is unset, selects the OpenAI model (API default in `apps/api/config.py` is `gpt-4o`).

If **no** LLM key is set, narrators and the parse step use **templated fallbacks** (no external LLM calls). Python dependency: **`litellm`** (see `pyproject.toml`).

**Embeddings** (optional RAG path in `packages/rag/embeddings.py`): when `EMBEDDING_PROVIDER=openai`, OpenAI embeddings still expect `OPENAI_API_KEY`; that path is independent of the multi-provider chat resolver above.

### Context data vs “rules skipped”

In the UI or logs, **“rules skipped”** means the evaluator did not have required **context fields** (e.g. a macro or sentiment input missing after a provider timeout or rate limit). It does **not** mean the LLM failed. Recent hardening includes:

- **NIFTY 50** OHLC for trend/SMA: Upstox index symbol resolves to `NSE_INDEX|Nifty 50` (not an equity `NSE_EQ|…` key).
- **GDELT**: on HTTP errors or **429**, the adapter returns neutral sentiment fields so sentiment rules are not all skipped when the public API throttles.

Frontend API base URL (for the browser):

```bash
cp apps/web/.env.example apps/web/.env.local
# Edit NEXT_PUBLIC_API_URL if the API is not on http://localhost:8000
```

Optional API env (see `apps/api/config.py`):

- `AUTO_APPROVE_STRONG_SIGNALS`, `OPENAI_MODEL` (OpenAI-only model when that provider is active), `IDEMPOTENCY_TTL_HOURS`, `SSE_KEEPALIVE_SECONDS`, `ALLOW_ORIGINS` (comma-separated; use `*` only in dev).

### Local debugging

- **`scripts/debug_context.py`**: loads root `.env`, builds default `ContextBuilder` context for a ticker (default `TCS` / `IN`), useful when checking which keys made it into the evaluator context.

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

## Deploying (Vercel + API)

The **Next.js UI** (`apps/web`) is a good fit for [Vercel](https://vercel.com). The **agent and API** (`apps/api` — FastAPI, LangGraph, long-running `POST /api/analyze`, SSE, Redis, optional Postgres/Qdrant) are **not** a good fit for Vercel’s serverless model (short timeouts, no long-lived process for schedulers, Redis-backed checkpoints). Run the API on a **container or VM host** (this repo includes a **[Render](https://render.com) Blueprint** via `render.yaml`) and point the UI at it.

### 1. Deploy the API on Render

1. Push this repository to GitHub (if it is not already).
2. In the [Render Dashboard](https://dashboard.render.com): **New → Blueprint** → select the repo → confirm the resources from [`render.yaml`](render.yaml) (a **Web Service** named `alpha-api`).
3. After the first deploy opens the service, go to **Environment** and add the variables you use locally (see [`.env.example`](.env.example)). Mark secrets (**LLM** keys, `UPSTOX_*`, `DATABASE_URL`, etc.) as **Secret** in the UI.
4. Set **`ALLOW_ORIGINS`** to your frontend origin(s), e.g. `https://your-app.vercel.app` (comma-separated for multiple). The API’s CORS middleware reads this env var (`apps/api/config.py`).
5. Optional but typical in production: create **[Render Postgres](https://render.com/docs/postgresql-creating-connecting)** and **[Render Key Value (Redis)](https://render.com/docs/redis)** in the same account/region, then set `DATABASE_URL` and `REDIS_URL` on `alpha-api` from each service’s **Connect** / external URL instructions.

**Blueprint knobs** (edit `render.yaml` before or after import):

- **`region`**: defaults to `singapore` (often lower latency to India); change if you prefer another Render region.
- **`plan`**: defaults to `starter` (stays awake; suitable for SSE and schedulers). For experiments you can switch to `free` (cold starts and sleep after idle).

**Build / start** (defined in `render.yaml`): `pip install .` from the **repository root** (so `packages/*` and `apps/api` resolve), then `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT --workers 1`. Health checks use **`GET /health`**.

### 2. Deploy the frontend on Vercel

1. Import this GitHub repo in Vercel.
2. **Root Directory**: `apps/web` (important — do not use the monorepo root or the install/build paths will be wrong).
3. **Build**: default `npm run build` is fine; install runs in `apps/web`.
4. **Environment variables** (Production / Preview):
   - `NEXT_PUBLIC_API_URL` = your Render API URL **without** a trailing slash, e.g. `https://alpha-api.onrender.com`

The browser loads `apps/web/lib/api.ts`, which reads `NEXT_PUBLIC_API_URL` and calls your FastAPI host.

### 3. Smoke-test after deploy

- Open `https://<your-vercel-app>.vercel.app/analyze` and run a ticker.
- If the UI loads but analyze fails, check browser devtools **Network** (CORS, 404 to wrong API URL) and API logs.

### Why not “everything on Vercel”?

Putting the FastAPI agent **inside** Vercel serverless would hit **execution time limits**, cold starts, and weak support for **long SSE streams** and **background schedulers**. Keeping the API on a always-on or container platform matches how this repo is designed.

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

- Multi-provider LLM resolution: `packages/agents/llm_provider.py`
- Orchestrator graph and prompts: `packages/agents/orchestrator.py`, `packages/agents/prompts/`
- Rule grammar and overrides: `packages/core/rule_evaluator.py`, `packages/core/rules.json`
- API lifespan (schedulers, Redis, Postgres): `apps/api/main.py`
- Render API deploy: [`render.yaml`](render.yaml)
