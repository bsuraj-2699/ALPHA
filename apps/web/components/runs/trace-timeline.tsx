"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAgentMeta } from "@/lib/agents";
import type { ReasoningStep } from "@/types/api";
import { cn } from "@/lib/utils";

/**
 * Vertical timeline of reasoning steps. Pairs with the DAG above:
 * the DAG shows topology + execution timing, this shows the prose.
 */
export function TraceTimeline({ trace }: { trace: ReasoningStep[] | undefined }) {
  if (!trace || trace.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-sm text-muted-foreground">
          No trace yet — run an analysis to see step-by-step reasoning.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="space-y-0 border-b border-border pb-4">
        <CardTitle className="text-base">Reasoning trace</CardTitle>
        <p className="text-xs text-muted-foreground">
          {trace.length} steps · ordered by emission time
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <ol className="flex flex-col">
          {trace.map((step, i) => {
            const meta = getAgentMeta(step.agent);
            return (
              <motion.li
                key={`${step.agent}-${i}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04 }}
                className={cn(
                  "relative flex gap-3 border-b border-border px-5 py-4 last:border-b-0",
                )}
              >
                <div
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-xs font-semibold text-foreground/90"
                  style={{ background: meta?.avatar ?? "#1a1f29" }}
                >
                  {meta?.initial ?? "·"}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="font-display text-sm font-semibold">
                      {meta?.displayName ?? step.agent}
                    </span>
                    {typeof step.duration_ms === "number" && (
                      <Badge
                        variant="muted"
                        className="font-mono normal-case tracking-normal"
                      >
                        {step.duration_ms}ms
                      </Badge>
                    )}
                    {typeof step.tokens_in === "number" &&
                      typeof step.tokens_out === "number" &&
                      step.tokens_in + step.tokens_out > 0 && (
                        <Badge
                          variant="muted"
                          className="font-mono normal-case tracking-normal"
                        >
                          {step.tokens_in + step.tokens_out} tok
                        </Badge>
                      )}
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/85">
                    {step.output}
                  </p>
                </div>
              </motion.li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}
