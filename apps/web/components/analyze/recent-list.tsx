"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, Clock } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useUIStore } from "@/lib/store";
import { cn } from "@/lib/utils";

/**
 * Recently-viewed tickers, persisted via Zustand. Empty state stays
 * styled like the rest of the page rather than a hard "nothing here".
 */
export function RecentList({ activeTicker }: { activeTicker: string }) {
  const recent = useUIStore((s) => s.recentTickers);

  // Suppress hydration mismatch warnings when the persisted store hasn't
  // populated yet on first render.
  const [hydrated, setHydrated] = React.useState(false);
  React.useEffect(() => setHydrated(true), []);
  const items = hydrated ? recent : [];

  return (
    <Card>
      <CardHeader className="space-y-0 p-4 pb-2">
        <CardTitle className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
          <Clock className="h-3.5 w-3.5" />
          Recent
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 p-2">
        {items.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            Run an analysis — recent tickers show up here.
          </p>
        ) : (
          items.map((sym) => (
            <Link
              key={sym}
              href={`/analyze/${sym}`}
              className={cn(
                "group flex items-center justify-between rounded-md px-2 py-1.5 text-sm transition-colors",
                sym === activeTicker
                  ? "bg-accent/60 text-foreground"
                  : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
              )}
            >
              <span className="font-mono text-xs">{sym}</span>
              <ArrowUpRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
            </Link>
          ))
        )}
      </CardContent>
    </Card>
  );
}
