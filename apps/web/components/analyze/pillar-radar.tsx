"use client";

import * as React from "react";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYST_NODES, getAgentMeta } from "@/lib/agents";
import type { AnalystReport } from "@/types/api";
import type { AgentSlot } from "@/lib/run-stream";

interface PillarRadarProps {
  /** Loaded reports from GET /api/runs/{id} */
  reports: Record<string, AnalystReport> | undefined;
  /** Live agent slots from SSE — used as a fallback while reports are still loading */
  liveSlots: AgentSlot[];
}

interface RadarPoint {
  pillar: string;
  score: number;
  fullMark: 100;
}

function buildRadarData(
  reports: PillarRadarProps["reports"],
  liveSlots: AgentSlot[],
): RadarPoint[] {
  return ANALYST_NODES.map((node) => {
    const meta = getAgentMeta(node);
    const reportScore = reports?.[node]?.score;
    const liveScore =
      liveSlots.find((s) => s.meta.node === node)?.payload?.["score"];

    let score: number;
    if (typeof reportScore === "number") {
      score = reportScore;
    } else if (typeof liveScore === "number") {
      score = liveScore;
    } else {
      score = 0;
    }

    return {
      pillar: meta?.displayName ?? node,
      score: Math.max(0, Math.min(100, score)),
      fullMark: 100 as const,
    };
  });
}

export function PillarRadar({ reports, liveSlots }: PillarRadarProps) {
  const data = React.useMemo(
    () => buildRadarData(reports, liveSlots),
    [reports, liveSlots],
  );
  const total = data.reduce((acc, p) => acc + p.score, 0);
  const hasAny = total > 0;

  return (
    <Card>
      <CardHeader className="space-y-0 p-4 pb-1">
        <CardTitle className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">
          Pillar scores
        </CardTitle>
        {hasAny && (
          <p className="font-mono text-xs text-muted-foreground">
            avg {(total / data.length).toFixed(1)}
          </p>
        )}
      </CardHeader>
      <CardContent className="p-2 pt-0">
        {hasAny ? (
          <div className="h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart
                data={data}
                margin={{ top: 18, right: 22, left: 22, bottom: 12 }}
              >
                <PolarGrid stroke="rgba(231, 233, 238, 0.08)" />
                <PolarAngleAxis
                  dataKey="pillar"
                  tick={{
                    fill: "#8a93a3",
                    fontSize: 10,
                    fontFamily:
                      "var(--font-plex-sans), system-ui, sans-serif",
                  }}
                />
                <PolarRadiusAxis
                  angle={90}
                  domain={[0, 100]}
                  tick={false}
                  axisLine={false}
                />
                <Radar
                  name="score"
                  dataKey="score"
                  stroke="#c9a84c"
                  strokeWidth={1.5}
                  fill="#c9a84c"
                  fillOpacity={0.22}
                  isAnimationActive
                  animationDuration={700}
                  animationEasing="ease-out"
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-[240px] flex-col items-center justify-center gap-3 px-3">
            <Skeleton className="h-32 w-32 rounded-full" />
            <p className="text-center text-xs text-muted-foreground">
              Pillar scores appear as analysts complete.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
