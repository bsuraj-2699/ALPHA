# fin-agent · web

Next.js 15 App Router frontend for the multi-agent financial analysis system.

## Stack

- **Next.js 15** + React 19 + TypeScript strict
- **Tailwind CSS 4** (with `@theme inline` design tokens in `app/globals.css`)
- **shadcn/ui** primitives — slate base, written by hand for Tailwind 4 compat. New components can still be added via `npx shadcn@latest add <component>` (see `components.json`).
- **Framer Motion** for layout animations
- **TanStack Query** for server-state caching
- **Zustand** for purely-UI client state
- **Lightweight Charts** (TradingView OSS) for OHLC
- **Recharts** for everything else

## Design

Dark mode only. Background `#0a0c0f`. Brand accents:

| token       | hex       | Tailwind utility |
|-------------|-----------|------------------|
| `--buy`     | `#00e5a0` | `bg-buy`, `text-buy` |
| `--sell`    | `#ff4d6d` | `bg-sell`, `text-sell` |
| `--neutral` | `#f5a623` | `bg-warn`, `text-warn` (renamed to avoid clashing with Tailwind's built-in `neutral` palette) |
| `--gold`    | `#c9a84c` | `bg-gold`, `text-gold` |

Typography: **Playfair Display** for display headings, **IBM Plex Sans** for body, **IBM Plex Mono** for any number / ticker / code.

## Layout

`components/layout/shell.tsx` wraps every page with:

- a left sidebar (`sidebar.tsx`) with persistent collapse state in Zustand

## Pages

| route | file | what lives here |
|---|---|---|
| `/`              | `app/page.tsx`                        | dashboard cards + quick analyze |
| `/analyze/[ticker]` | `app/analyze/[ticker]/page.tsx`    | full analysis view (live trace) |
| `/runs/[id]`     | `app/runs/[id]/page.tsx`              | run inspector / trace timeline |
| `/watchlist`     | `app/watchlist/page.tsx`              | watchlist manager |
| `/portfolio`     | `app/portfolio/page.tsx`              | positions + live P&L |

All pages currently scaffold an empty-state — the API client at `lib/api.ts` and the typed wire models at `types/api.ts` are ready to wire in.

## Dev

```bash
cp .env.example .env.local
# point NEXT_PUBLIC_API_URL at your local FastAPI

npm install
npm run dev
```

Run the API in another terminal:

```bash
uvicorn apps.api.main:app --reload
```

## Build

```bash
npm run build
npm start
```
