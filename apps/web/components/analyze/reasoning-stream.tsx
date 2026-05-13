"use client";

import * as React from "react";
import { Sparkles, Activity } from "lucide-react";
import { motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentRow } from "./agent-row";
import type { RunStreamState } from "@/lib/run-stream";
import type { AnalystReport, RunDetail } from "@/types/api";

interface ReasoningStreamProps {
  stream: RunStreamState;
  detail: RunDetail | undefined;
  /** Whether a run has been kicked off */
  hasRun: boolean;
}

export function ReasoningStream({ stream, detail, hasRun }: ReasoningStreamProps) {
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});

  const totalDuration = stream.agents.reduce(
    (acc, a) => acc + (a.durationMs ?? 0),
    0,
  );
  const completed = stream.agents.filter((a) => a.status === "complete").length;
  const total = stream.agents.length;

  const toggle = (node: string) =>
    setExpanded((s) => ({ ...s, [node]: !s[node] }));

  return (
    <Card className="flex h-full flex-col">
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-gold/15 ring-1 ring-inset ring-gold/40">
            <Sparkles className="h-4 w-4 text-gold" />
          </div>
          <div className="flex flex-col gap-0.5">
            <CardTitle className="text-base">Reasoning stream</CardTitle>
            <p className="text-xs text-muted-foreground">
              {hasRun
                ? stream.live
                  ? "Live · streaming events"
                  : stream.status === "complete"
                    ? "Complete"
                    : stream.status === "interrupted"
                      ? "Awaiting human review"
                      : stream.status === "error"
                        ? "Errored"
                        : "Idle"
                : "Pick a ticker and click Analyze to start"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {hasRun && (
            <Badge variant="muted" className="font-mono normal-case tracking-normal">
              {completed}/{total}
            </Badge>
          )}
          {totalDuration > 0 && (
            <Badge variant="muted" className="font-mono normal-case tracking-normal">
              {(totalDuration / 1000).toFixed(2)}s
            </Badge>
          )}
          {stream.live && (
            <Badge
              variant="warn"
              className="flex items-center gap-1 normal-case tracking-normal"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-warn animate-pulse" />
              live
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-y-auto p-4">
        {!hasRun ? (
          <div className="flex h-full min-h-[400px] flex-col items-center justify-center gap-3 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted/40 ring-1 ring-inset ring-border">
              <Activity className="h-5 w-5 text-muted-foreground" />
            </div>
            <p className="font-display text-lg">Ready to think.</p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Five analysts, two debaters, one judge — agent outputs will
              stream here in real-time.
            </p>
          </div>
        ) : (
          <motion.div layout className="flex flex-col gap-2">
            {stream.agents.map((slot) => {
              const report: AnalystReport | undefined = slot.meta.analystKey
                ? detail?.analyst_reports?.[slot.meta.analystKey]
                : undefined;
              return (
                <AgentRow
                  key={slot.meta.node}
                  slot={slot}
                  report={report ?? null}
                  expanded={Boolean(expanded[slot.meta.node])}
                  onToggle={() => toggle(slot.meta.node)}
                />
              );
            })}
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
