"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, History } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { OverrideBanner } from "@/components/analyze/override-banner";
import { DecisionCard } from "@/components/analyze/decision-card";
import { useRun } from "@/lib/queries";

import { ExecutionDag } from "./execution-dag";
import { TraceTimeline } from "./trace-timeline";

export function RunsView({ runId }: { runId: string }) {
  const detail = useRun(runId);

  if (detail.isError) {
    return (
      <div className="flex flex-col gap-8">
        <PageHeader
          eyebrow="Run"
          title={<span className="font-mono text-2xl">{runId}</span>}
        />
        <EmptyState
          icon={History}
          title="Run not found"
          description={detail.error?.message ?? "We couldn't load this run."}
          action={
            <Button asChild variant="outline" size="sm">
              <Link href="/runs">Back to runs</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const data = detail.data;
  const status = data?.status ?? "pending";
  const decision = data?.decision ?? null;
  const overrides = decision?.overrides_active ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={data ? `${data.market} · ${data.ticker}` : "Run"}
        title={<span className="font-mono text-2xl md:text-3xl">{runId}</span>}
        description="Replay every step of the multi-agent run. The graph below mirrors the LangGraph topology — nodes light up in real execution order, edges show data flow with traveling dots."
        actions={
          <div className="flex items-center gap-2">
            {data && (
              <Button asChild variant="ghost" size="sm">
                <Link href={`/analyze/${data.ticker}`} className="gap-1.5">
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back to analyze
                </Link>
              </Button>
            )}
            <Badge
              variant={
                status === "complete"
                  ? "buy"
                  : status === "error"
                    ? "sell"
                    : status === "interrupted"
                      ? "gold"
                      : "muted"
              }
            >
              {status}
            </Badge>
          </div>
        }
      />

      {overrides.length > 0 && decision && (
        <OverrideBanner overrides={overrides} signal={decision.signal} />
      )}

      <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
        <div className="flex flex-col gap-6">
          <ExecutionDag
            trace={data?.reasoning_trace}
            status={status}
            analystReports={data?.analyst_reports}
          />
          <TraceTimeline trace={data?.reasoning_trace} />
        </div>

        <aside className="flex flex-col gap-4">
          <DecisionCard decision={decision} pending={status === "running"} />
        </aside>
      </div>
    </div>
  );
}
