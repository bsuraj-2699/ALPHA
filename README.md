<div align="center">

<img src="https://capsule-render.vercel.app/api?type=venom&color=0:0f172a,50:1e3a5f,100:6366f1&height=200&section=header&text=ALPHA&fontSize=58&fontColor=ffffff&fontAlignY=38&desc=Your%20AI%20Edge%20in%20Indian%20Markets%20%E2%80%94%20multi-agent%20equity%20analysis%20for%20NSE&descAlignY=62&descSize=14&descColor=a5b4fc&animation=fadeIn" width="100%" />

<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=18&duration=2800&pause=900&color=6366F1&center=true&vCenter=true&multiline=false&repeat=true&width=680&height=45&lines=7-node+LangGraph+pipeline+for+NSE+equities;Deterministic+rules+%2B+LLM+analysts+%2B+structured+debate;5+LLM+providers%2C+zero+vendor+lock-in;Auditable+decisions+%E2%80%94+no+LLM+touches+position+sizing" alt="Typing" />

<br/><br/>

[![Demo](https://img.shields.io/badge/Loom-Watch%20Demo-06b6d4?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/c41e9064730e477580ed14c7983f6ee7)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-FF6B35?style=for-the-badge&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)

<br/>

![Status](https://img.shields.io/badge/Status-Production-6366f1?style=flat-square)
![Market](https://img.shields.io/badge/Market-NSE%20%2F%20India-FF6B35?style=flat-square)
![Pipeline](https://img.shields.io/badge/Pipeline-7%20Node%20Graph-06b6d4?style=flat-square)
![Decision](https://img.shields.io/badge/Decision%20Layer-Deterministic-a5b4fc?style=flat-square)

</div>

---

## ⚡ What it does

> Multi-agent financial analysis for **Indian equities (NSE)**. Deterministic rule scoring meets LLM analysts, a structured bull/bear debate, and a final mechanical decision layer — exposed through a FastAPI backend with an optional Next.js dashboard.

| | Layer | Role |
|:---:|:---|:---|
| 📐 | **Rule engine** | `RuleEvaluator` + `rules.json` — **LLM-free**, deterministic scoring and overrides |
| 🤖 | **Pillar analysts** | Fundamental, Technical, Sentiment, Macro, Risk — run in parallel via LangGraph |
| ⚖️ | **Debate** | Structured bull vs. bear cases built from the analyst reports |
| 🧑‍⚖️ | **Judge** | Rules fire first; LLM adds narrative on top — optionally RAG-enriched |
| ✅ | **Decision** | Fully deterministic — position sizing, stop/target, human-review flags — **no LLM** |

---

## 🏗️ Architecture

```
                                 ┌──[ Fundamental Analyst ]──┐
                                 ├──[ Technical  Analyst  ]──┤
[ Parse ] ──► [ Context Build ] ─┼──[ Sentiment  Analyst  ]──┼──► [ Bull/Bear Debate ] ──► [ Judge ] ──► [ Decide ] ──► END
                                 ├──[ Macro      Analyst  ]──┤
                                 └──[ Risk       Analyst  ]──┘
```

**End-to-end run:**

1. **Client** calls `POST /api/analyze` with ticker, market (`IN`), optional mode + portfolio context
2. **Idempotency** — same ticker + market + UTC calendar day maps to a fixed `run_id`; duplicate POSTs return the existing run (`idempotent_hit=True`)
3. **RunManager** starts a LangGraph invocation on the shared **Orchestrator**, streaming lifecycle events on the event bus (Redis, or in-memory fallback)
4. **Context build** pulls OHLC, fundamentals, news/sentiment from configured providers; missing fields mark individual rules as *skipped* — separate from any LLM failure
5. **Analysts** call an `instructor` client backed by **LiteLLM**, so structured narratives work across OpenAI, Anthropic, Gemini, Mistral, or Groq
6. **Debate** runs bull/bear agents on those reports using the same LLM stack
7. **Judge** calls `RuleEvaluator.evaluate()` first — deterministic signals and overrides — then layers LLM narrative on top, optionally enriched by RAG
8. **Decision** (`DecisionAgent`) is fully deterministic — sizing bands, stop/target, `requires_human_review`, low-coverage caps — **no LLM in the loop**
9. **Persistence** — completed runs write to `run_logs`; Redis backs idempotency, SSE fan-out, LangGraph checkpoints, and Upstox token caching

**Scheduled & reactive paths** (same graph, different `run_id` prefix):

| Scheduler | Trigger |
|:---|:---|
| `IntradayScheduler` | Every 5 min during NSE hours (09:15–15:30 IST, Mon–Fri) |
| `DailyScheduler` | Once per business day, default 10:00 IST |
| `RetriggerSubscriber` | Reacts to Redis `retrigger:*` events with cooldowns |

---

## 📁 Repository Layout

| Path | Role |
|:---|:---|
| `apps/api` | HTTP API — analyze runs, SSE progress, watchlist/portfolio, buckets, schedulers, persistence |
| `apps/web` | Next.js dashboard — analyze flow, runs, watchlist, charts |
| `packages/core` | `RuleEvaluator` + `rules.json` — LLM-free scoring and overrides |
| `packages/data` | Market data providers (Upstox, Yahoo, screener.in) + `ContextBuilder` |
| `packages/agents` | LangGraph Orchestrator, pillar analysts, debate, judge, decision |
| `packages/rag` | Optional hybrid retrieval (Qdrant + BM25) for judge context |
| `packages/shared` | Schemas, mode config, observability helpers |
| `infra/` | Docker Compose for Postgres (Timescale), Redis, Qdrant only |
| `render.yaml` | Render Blueprint for deploying `apps/api` |
| `eval/` | Offline scenario / backtest harness |
| `scripts/` | Utilities — Excel export, context debug script |

---

## 🛠️ Tech Stack

<div align="center">

[![Skills](https://skillicons.dev/icons?i=python,fastapi,nextjs,nodejs,postgres,redis,docker&theme=dark)](https://skillicons.dev)

![LangGraph](https://img.shields.io/badge/LangGraph-FF6B35?style=for-the-badge&logoColor=white)
![LiteLLM](https://img.shields.io/badge/LiteLLM-1C3C3C?style=for-the-badge&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?style=for-the-badge&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)
![Anthropic](https://img.shields.io/badge/Anthropic-D4A27F?style=for-the-badge&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=white)
![Mistral](https://img.shields.io/badge/Mistral-FF7000?style=for-the-badge&logoColor=white)
![Upstox](https://img.shields.io/badge/Upstox-5B2C8D?style=for-the-badge&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)

</div>

---

## 🤖 LLMs — Multi-Provider

Chat flows (query parse, pillar analysts, debate, judge) run through `instructor` + `litellm`. Set **at least one** key:

| Variable | Provider |
|:---|:---|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini (AI Studio) |
| `MISTRAL_API_KEY` | Mistral |
| `GROQ_API_KEY` | Groq |

Resolution logic lives in `packages/agents/llm_provider.py`:

- `LLM_PROVIDER_PRIORITY` — comma-separated order, default `openai,anthropic,gemini,mistral,groq`. First provider with a configured key wins for every chat step.
- `LLM_MODEL` — force a single LiteLLM model id across all chat calls, e.g. `gpt-4o-mini`, `anthropic/claude-3-5-sonnet-20241022`, `gemini/gemini-2.0-flash`.
- `OPENAI_MODEL` — when OpenAI is active and `LLM_MODEL` is unset, selects the model (API default: `gpt-4o`).

> If no LLM key is set, narrators and the parse step fall back to **templated output** — no external calls. Optional RAG embeddings (`EMBEDDING_PROVIDER=openai`) still require `OPENAI_API_KEY` independently.

---

## ⚙️ Configuration

```bash
cp .env.example .env
```

| Area | Variables |
|:---|:---|
| **Data** | Upstox keys/tokens, optional `SCREENER_SESSION_COOKIE` |
| **Infra** | `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL` — unset falls back to in-memory where possible; `/health` reports what's active |
| **Frontend** | `NEXT_PUBLIC_API_URL` in `apps/web/.env.local` |
| **API tuning** | `AUTO_APPROVE_STRONG_SIGNALS`, `IDEMPOTENCY_TTL_HOURS`, `SSE_KEEPALIVE_SECONDS`, `ALLOW_ORIGINS` |

**Context vs. "rules skipped":** in logs/UI, *rules skipped* means the evaluator was missing required context fields — not that an LLM call failed. Recent hardening: NIFTY 50 OHLC resolves to the correct Upstox index symbol (`NSE_INDEX|Nifty 50`), and GDELT returns neutral sentiment on HTTP errors / 429s instead of skipping all sentiment rules.

**Local debugging:** `scripts/debug_context.py` loads `.env` and builds a default context for a ticker (default `TCS` / `IN`) to inspect which keys reached the evaluator.

---

## 🚀 Commands

**Prerequisites:** Python ≥ 3.11 · [`uv`](https://docs.astral.sh/uv/) · Node.js + npm · Docker

```bash
# one-shot setup (Python deps + tooling)
make setup                 # = uv sync --all-extras

# infrastructure — Postgres : 5432 · Redis : 6379 · Qdrant : 6333/6334
make docker-up              # = docker compose -f infra/docker-compose.yml up -d
make docker-down

# API — from repo root, so apps/ and packages/ resolve
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
# docs: http://localhost:8000/docs   ·   health: GET /health

# frontend
cd apps/web && npm install && npm run dev
# production build: npm run build && npm run start

# tests
make test                   # core rule smoke script + pytest

# optional: run history export to Excel (needs DATABASE_URL)
uv run python scripts/export_runs_to_excel.py --out exports/runs_export.xlsx
```

---

## ☁️ Deployment — Render + Vercel

> The FastAPI agent (`apps/api`) doesn't fit Vercel's serverless model — execution time limits, no long-lived process for schedulers, Redis-backed checkpoints need an always-on host. The Next.js UI (`apps/web`) is a great fit for Vercel.

### 1. API on Render

1. Push the repo to GitHub
2. Render Dashboard → **New → Blueprint** → select repo → confirms `alpha-api` web service from `render.yaml`
3. Add environment variables under **Environment** (mark LLM keys, `UPSTOX_*`, `DATABASE_URL` as **Secret**)
4. Set `ALLOW_ORIGINS` to your frontend origin(s), e.g. `https://your-app.vercel.app`
5. Optional: spin up Render Postgres + Render Key Value (Redis) in the same region, wire `DATABASE_URL` / `REDIS_URL`

**Blueprint knobs** (`render.yaml`): `region` defaults to `singapore` (low latency to India); `plan` defaults to `starter` (stays awake — needed for SSE + schedulers; `free` sleeps on idle).

**Build/start:** `pip install .` from repo root, then `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT --workers 1`. Health check: `GET /health`.

### 2. Frontend on Vercel

1. Import the GitHub repo
2. **Root Directory:** `apps/web` — critical, don't use the monorepo root
3. Build: default `npm run build`
4. Env var: `NEXT_PUBLIC_API_URL` = your Render API URL, no trailing slash (e.g. `https://alpha-api.onrender.com`)

### 3. Smoke test

Open `https://<your-vercel-app>.vercel.app/analyze`, run a ticker. If analyze fails, check Network tab for CORS/404 and the API logs.

---

## 🔄 Typical Local Workflow

```bash
make docker-up
cp .env.example .env                          # + apps/web/.env.local if needed
make setup

# Terminal A
uv run uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal B
cd apps/web && npm install && npm run dev
```

Open the UI, run an analysis, or call `POST /api/analyze` directly from `http://localhost:8000/docs`.

---

## 📚 Further Reading

| Topic | File |
|:---|:---|
| Multi-provider LLM resolution | `packages/agents/llm_provider.py` |
| Orchestrator graph & prompts | `packages/agents/orchestrator.py`, `packages/agents/prompts/` |
| Rule grammar & overrides | `packages/core/rule_evaluator.py`, `packages/core/rules.json` |
| API lifespan (schedulers, Redis, Postgres) | `apps/api/main.py` |
| Render API deploy | [`render.yaml`](render.yaml) |

---

<div align="center">

*Deterministic where it matters. AI where it helps. Built for NSE.*

<br/>

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:6366f1,100:06b6d4&height=120&section=footer&text=signal%20over%20noise&fontSize=15&fontColor=e2e8f0&fontAlignY=68" width="100%" />

</div>
