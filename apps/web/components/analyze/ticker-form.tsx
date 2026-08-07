"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Sparkles } from "lucide-react";

import { INDIAN_TICKERS, lookupTickerName, toDisplayTicker } from "@/lib/tickers";
import { cn } from "@/lib/utils";

import { GlassCard } from "./primitives";

export function TickerForm({
  current,
  running,
  onRerun,
}: {
  current?: string;
  running?: boolean;
  onRerun?: () => void;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);

  const matches = useMemo(() => {
    const s = q.trim().toUpperCase();
    if (!s) return INDIAN_TICKERS.slice(0, 8);
    return INDIAN_TICKERS.filter(
      (t) => t.symbol.toUpperCase().includes(s) || t.name.toUpperCase().includes(s),
    ).slice(0, 8);
  }, [q]);

  function go(symbol: string) {
    const clean = toDisplayTicker(symbol.trim().toUpperCase());
    if (!clean) return;
    setQ("");
    setOpen(false);
    router.push(`/analyze/${encodeURIComponent(clean)}`);
  }

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Ticker
        </div>
        <span className="rounded-md border border-white/[0.07] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">
          NSE · BSE
        </span>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          go(q || current || "");
        }}
        className="relative mt-3"
      >
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={current ? toDisplayTicker(current) : "Search NSE / BSE…"}
          spellCheck={false}
          autoComplete="off"
          className="w-full rounded-xl border border-white/[0.08] bg-white/[0.03] py-2.5 pl-9 pr-3 font-mono text-sm uppercase tracking-wide text-foreground placeholder:normal-case placeholder:tracking-normal placeholder:text-muted-foreground focus:border-accent1/40 focus:outline-none"
        />

        {open && matches.length > 0 && (
          <div className="glass-strong absolute z-30 mt-2 w-full overflow-hidden rounded-xl p-1">
            {matches.map((t) => (
              <button
                key={t.symbol}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => go(t.symbol)}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/[0.05]"
              >
                <span className="font-mono text-sm text-foreground">{t.symbol}</span>
                <span className="truncate pl-3 text-xs text-muted-foreground">{t.name}</span>
              </button>
            ))}
          </div>
        )}
      </form>

      {current && (
        <div className="mt-3 flex items-center justify-between gap-2">
          <div className="min-w-0 truncate text-xs text-muted-foreground">
            {lookupTickerName(current)}
          </div>
          <button
            type="button"
            onClick={onRerun}
            disabled={running}
            className={cn(
              "flex shrink-0 items-center gap-1.5 rounded-lg border border-accent1/30 bg-accent1/10 px-3 py-1.5 text-xs font-medium text-accent1 transition-colors hover:bg-accent1/20 disabled:opacity-50",
            )}
          >
            <Sparkles className={cn("h-3.5 w-3.5", running && "animate-spin")} />
            {running ? "Analyzing…" : "Re-run"}
          </button>
        </div>
      )}
    </GlassCard>
  );
}
