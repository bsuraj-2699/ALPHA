"use client";

import * as React from "react";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface DebateCase {
  thesis?: string;
  confidence?: number;
  key_points?: string[];
  cited_pillars?: string[];
}

interface DebatePanelProps {
  bull: DebateCase | null;
  bear: DebateCase | null;
  /** Whether a run is in progress and we expect these to populate */
  pending: boolean;
}

function CaseSkeleton({ side }: { side: "bull" | "bear" }) {
  return (
    <Card className={cn("border", side === "bull" ? "border-buy/20" : "border-sell/20")}>
      <CardContent className="flex flex-col gap-3 p-5">
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-5 w-12" />
        </div>
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </CardContent>
    </Card>
  );
}

function CaseCard({
  side,
  data,
}: {
  side: "bull" | "bear";
  data: DebateCase;
}) {
  const accent = side === "bull" ? "buy" : "sell";
  const Icon = side === "bull" ? ArrowUpRight : ArrowDownRight;
  const label = side === "bull" ? "Bull case" : "Bear case";

  const confidence =
    typeof data.confidence === "number" ? data.confidence : null;

  return (
    <motion.div
      initial={{ opacity: 0, x: side === "bull" ? -16 : 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
    >
      <Card
        className={cn(
          "h-full",
          side === "bull"
            ? "border-buy/30 bg-gradient-to-br from-buy/[0.05] to-transparent"
            : "border-sell/30 bg-gradient-to-bl from-sell/[0.05] to-transparent",
        )}
      >
        <CardContent className="flex h-full flex-col gap-3 p-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "flex h-7 w-7 items-center justify-center rounded-md",
                  side === "bull"
                    ? "bg-buy/15 text-buy ring-1 ring-inset ring-buy/30"
                    : "bg-sell/15 text-sell ring-1 ring-inset ring-sell/30",
                )}
              >
                <Icon className="h-4 w-4" />
              </div>
              <span className="font-display text-base font-semibold">{label}</span>
            </div>
            {confidence !== null && (
              <Badge variant={accent} className="font-mono normal-case tracking-normal">
                {confidence.toFixed(0)}%
              </Badge>
            )}
          </div>

          {data.thesis && (
            <p className="text-sm leading-relaxed text-foreground/90">
              {data.thesis}
            </p>
          )}

          {data.key_points && data.key_points.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {data.key_points.slice(0, 4).map((p, i) => (
                <li
                  key={i}
                  className="flex gap-2 text-xs text-muted-foreground"
                >
                  <span
                    className={
                      side === "bull"
                        ? "mt-1 h-1 w-1 shrink-0 rounded-full bg-buy"
                        : "mt-1 h-1 w-1 shrink-0 rounded-full bg-sell"
                    }
                  />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          )}

          {data.cited_pillars && data.cited_pillars.length > 0 && (
            <div className="mt-auto flex flex-wrap gap-1.5 pt-2">
              {data.cited_pillars.map((p) => (
                <span
                  key={p}
                  className="rounded bg-muted/40 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
                >
                  {p}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}

export function DebatePanel({ bull, bear, pending }: DebatePanelProps) {
  const ready = bull !== null || bear !== null;
  if (!ready && !pending) return null;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <AnimatePresence mode="wait">
        {bull ? (
          <CaseCard key="bull" side="bull" data={bull as DebateCase} />
        ) : (
          <CaseSkeleton key="bull-skel" side="bull" />
        )}
      </AnimatePresence>
      <AnimatePresence mode="wait">
        {bear ? (
          <CaseCard key="bear" side="bear" data={bear as DebateCase} />
        ) : (
          <CaseSkeleton key="bear-skel" side="bear" />
        )}
      </AnimatePresence>
    </div>
  );
}
