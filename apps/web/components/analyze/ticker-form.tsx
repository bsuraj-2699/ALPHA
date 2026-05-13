"use client";

import * as React from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { Market } from "@/types/api";

interface TickerFormProps {
  ticker: string;
  market: Market;
  isRunning: boolean;
  onChange: (next: { ticker: string; market: Market }) => void;
  onSubmit: () => void;
}

const TICKER_RE = /^[A-Z][A-Z0-9]*(\.[A-Z]{2})?$/;

export function TickerForm({
  ticker,
  isRunning,
  onChange,
  onSubmit,
}: TickerFormProps) {
  const [local, setLocal] = React.useState(ticker);
  React.useEffect(() => setLocal(ticker), [ticker]);

  const normalized = local.trim().toUpperCase();
  const valid = TICKER_RE.test(normalized);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!valid || isRunning) return;
    onChange({ ticker: normalized, market: "IN" });
    onSubmit();
  };

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4">
        <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              Ticker
            </span>
            <input
              autoFocus
              spellCheck={false}
              autoCapitalize="characters"
              autoComplete="off"
              value={local}
              onChange={(e) => setLocal(e.target.value)}
              placeholder="RELIANCE"
              className={cn(
                "h-10 w-full rounded-xl border border-input bg-background px-3 font-mono text-base uppercase tracking-tight outline-none ring-0 transition-colors",
                "placeholder:text-muted-foreground/50",
                "focus:border-gold focus:ring-1 focus:ring-gold/40",
                !valid && local.length > 0 && "border-sell/60",
              )}
            />
          </label>

          <div
            className={cn(
              "flex h-9 items-center justify-center rounded-md border border-border bg-card",
              "text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground",
            )}
          >
            NSE / BSE
          </div>

          <Button
            type="submit"
            variant="gold"
            size="lg"
            disabled={!valid || isRunning}
            className="w-full font-medium"
          >
            <Sparkles className="h-4 w-4" />
            {isRunning ? "Analyzing…" : "Analyze"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
