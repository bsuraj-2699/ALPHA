"use client";

import * as React from "react";

import { getIndiaStatus, type MarketStatus } from "@/lib/market-hours";
import { cn } from "@/lib/utils";

const IST_TIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * Live NSE session pill. Renders nothing on the server pass so the
 * clock can never disagree with the client's first paint.
 */
export function MarketClock({ className }: { className?: string }) {
  const [now, setNow] = React.useState<Date | null>(null);

  React.useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const status: MarketStatus | null = now ? getIndiaStatus(now) : null;
  const open = status?.isOpen ?? false;

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2.5 rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5",
        "text-[11px] font-medium tracking-wide text-muted-foreground backdrop-blur-sm",
        className,
      )}
    >
      <span className="relative flex h-2 w-2">
        {open ? (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-buy opacity-70" />
        ) : null}
        <span
          className={cn(
            "relative inline-flex h-2 w-2 rounded-full",
            open ? "bg-buy" : "bg-muted-foreground/50",
          )}
        />
      </span>
      <span className={open ? "text-foreground" : undefined}>
        NSE {open ? "open" : "closed"}
      </span>
      <span aria-hidden className="text-white/15">
        |
      </span>
      <span className="font-mono tabular-nums">
        {now ? `${IST_TIME.format(now)} IST` : "--:-- IST"}
      </span>
    </div>
  );
}
