"use client";

import * as React from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from "@xyflow/react";
import { motion } from "framer-motion";
import { Play, RotateCcw } from "lucide-react";

import "@xyflow/react/dist/style.css";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  AGENT_META,
  type AgentNode as AgentNodeName,
  type AgentStatus,
  getAgentMeta,
} from "@/lib/agents";
import type { ReasoningStep, RunStatus } from "@/types/api";
import { cn } from "@/lib/utils";

import {
  AgentNode,
  type AgentFlowNode,
  type AgentNodeData,
} from "./agent-node";
import { AnimatedEdge, type FlowEdge } from "./animated-edge";

/* ------------------------------------------------------------ */
/* Topology — must match packages/agents/orchestrator.py         */
/* ------------------------------------------------------------ */

const NODE_W = 150;
const X_GAP = 32;
const Y = {
  parse: 0,
  context: 120,
  analysts: 250,
  debate: 400,
  judge: 520,
  decide: 640,
};

// Five analysts spread horizontally; CENTER node x is at the middle of
// the analyst row so all the centered nodes line up cleanly.
const ANALYST_X: Record<AgentNodeName, number> = {
  parse: 0,
  context_build: 0,
  fundamentals: 0,
  technicals: NODE_W + X_GAP,
  sentiment: 2 * (NODE_W + X_GAP),
  macro: 3 * (NODE_W + X_GAP),
  risk: 4 * (NODE_W + X_GAP),
  debate: 0,
  judge: 0,
  decide: 0,
};
const CENTER_X = ANALYST_X.sentiment; // middle analyst x-coord

const NODE_POS: Record<AgentNodeName, { x: number; y: number }> = {
  parse: { x: CENTER_X, y: Y.parse },
  context_build: { x: CENTER_X, y: Y.context },
  fundamentals: { x: ANALYST_X.fundamentals, y: Y.analysts },
  technicals: { x: ANALYST_X.technicals, y: Y.analysts },
  sentiment: { x: ANALYST_X.sentiment, y: Y.analysts },
  macro: { x: ANALYST_X.macro, y: Y.analysts },
  risk: { x: ANALYST_X.risk, y: Y.analysts },
  debate: { x: CENTER_X, y: Y.debate },
  judge: { x: CENTER_X, y: Y.judge },
  decide: { x: CENTER_X, y: Y.decide },
};

const EDGES: ReadonlyArray<readonly [AgentNodeName, AgentNodeName]> = [
  ["parse", "context_build"],
  ["context_build", "fundamentals"],
  ["context_build", "technicals"],
  ["context_build", "sentiment"],
  ["context_build", "macro"],
  ["context_build", "risk"],
  ["fundamentals", "debate"],
  ["technicals", "debate"],
  ["sentiment", "debate"],
  ["macro", "debate"],
  ["risk", "debate"],
  ["debate", "judge"],
  ["judge", "decide"],
];

/* ------------------------------------------------------------ */
/* Status derivation                                             */
/* ------------------------------------------------------------ */

interface NodeRuntime {
  status: AgentStatus;
  durationMs?: number;
  score?: number | null;
}

function makeInitialRuntime(): Record<AgentNodeName, NodeRuntime> {
  const out = {} as Record<AgentNodeName, NodeRuntime>;
  for (const m of AGENT_META) out[m.node] = { status: "pending" };
  return out;
}

function fromTrace(
  trace: ReasoningStep[] | undefined,
  reports?: Record<string, { score?: number } | undefined>,
): Record<AgentNodeName, NodeRuntime> {
  const out = makeInitialRuntime();
  if (!trace) return out;
  for (const step of trace) {
    const meta = getAgentMeta(step.agent);
    if (!meta) continue;
    out[meta.node] = {
      status: "complete",
      durationMs: step.duration_ms,
      score: meta.analystKey
        ? (reports?.[meta.analystKey]?.score ?? null)
        : null,
    };
  }
  return out;
}

function edgeMode(
  source: NodeRuntime,
  target: NodeRuntime,
): "idle" | "active" | "settled" {
  if (source.status !== "complete") return "idle";
  if (target.status === "running") return "active";
  if (target.status === "complete") return "settled";
  return "idle";
}

/* ------------------------------------------------------------ */
/* Replay scheduler                                              */
/*                                                                */
/* Walks the trace in execution order, marking nodes running      */
/* then complete with phase-aware delays so parallel analysts     */
/* light up simultaneously rather than serially.                  */
/* ------------------------------------------------------------ */

const PHASES: ReadonlyArray<readonly AgentNodeName[]> = [
  ["parse"],
  ["context_build"],
  ["fundamentals", "technicals", "sentiment", "macro", "risk"],
  ["debate"],
  ["judge"],
  ["decide"],
];

const RUN_MS = 700; // each phase's "running" hold time

function scheduleReplay(
  setRuntime: React.Dispatch<
    React.SetStateAction<Record<AgentNodeName, NodeRuntime>>
  >,
  finalRuntime: Record<AgentNodeName, NodeRuntime>,
): () => void {
  const timeouts: number[] = [];

  // Reset all to pending
  setRuntime(() => makeInitialRuntime());

  let cum = 200;
  for (const phase of PHASES) {
    const startAt = cum;
    const completeAt = cum + RUN_MS;
    timeouts.push(
      window.setTimeout(() => {
        setRuntime((s) => {
          const next = { ...s };
          for (const n of phase) next[n] = { ...next[n], status: "running" };
          return next;
        });
      }, startAt),
    );
    timeouts.push(
      window.setTimeout(() => {
        setRuntime((s) => {
          const next = { ...s };
          for (const n of phase) next[n] = finalRuntime[n] ?? { status: "complete" };
          return next;
        });
      }, completeAt),
    );
    cum += RUN_MS + 80;
  }

  return () => {
    for (const id of timeouts) window.clearTimeout(id);
  };
}

/* ------------------------------------------------------------ */
/* Component                                                     */
/* ------------------------------------------------------------ */

interface ExecutionDagProps {
  trace: ReasoningStep[] | undefined;
  status: RunStatus;
  analystReports?:
    | Record<string, { score?: number } | undefined>
    | undefined;
  className?: string;
}

const NODE_TYPES = { agent: AgentNode };
const EDGE_TYPES = { animated: AnimatedEdge };

function buildNodes(
  runtime: Record<AgentNodeName, NodeRuntime>,
): AgentFlowNode[] {
  return AGENT_META.map((meta) => {
    const rt = runtime[meta.node];
    const data: AgentNodeData = {
      meta,
      status: rt.status,
      score: rt.score ?? null,
      durationMs: rt.durationMs ?? null,
    };
    return {
      id: meta.node,
      type: "agent",
      position: NODE_POS[meta.node],
      data,
      draggable: false,
      selectable: true,
      connectable: false,
    } satisfies AgentFlowNode;
  });
}

function buildEdges(
  runtime: Record<AgentNodeName, NodeRuntime>,
): FlowEdge[] {
  return EDGES.map(([s, t]) => ({
    id: `${s}->${t}`,
    type: "animated",
    source: s,
    target: t,
    data: { mode: edgeMode(runtime[s], runtime[t]) },
  }));
}

function ExecutionDagInner({
  trace,
  status,
  analystReports,
  className,
}: ExecutionDagProps) {
  const finalRuntime = React.useMemo(
    () => fromTrace(trace, analystReports),
    [trace, analystReports],
  );

  const [runtime, setRuntime] = React.useState(finalRuntime);
  const [replayKey, setReplayKey] = React.useState(0);

  // Auto-play once the trace is loaded; on re-mount or "Replay" clicks,
  // restart the schedule.
  React.useEffect(() => {
    if (status !== "complete" || !trace || trace.length === 0) {
      setRuntime(finalRuntime);
      return;
    }
    const cancel = scheduleReplay(setRuntime, finalRuntime);
    return cancel;
  }, [status, trace, finalRuntime, replayKey]);

  const nodes = React.useMemo(() => buildNodes(runtime), [runtime]);
  const edges = React.useMemo(() => buildEdges(runtime), [runtime]);

  const completed = (Object.values(runtime) as NodeRuntime[]).filter(
    (r) => r.status === "complete",
  ).length;
  const total = AGENT_META.length;

  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-border pb-4">
        <div className="flex flex-col gap-0.5">
          <CardTitle className="flex items-center gap-2 text-base">
            <Play className="h-4 w-4 text-gold" />
            Execution graph
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            {status === "complete"
              ? `Replaying real durations · ${completed}/${total} nodes`
              : status === "running"
                ? "Live execution"
                : status === "interrupted"
                  ? "Paused for human review"
                  : status === "error"
                    ? "Errored"
                    : "Awaiting run"}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setReplayKey((k) => k + 1)}
          disabled={!trace || trace.length === 0}
          className="gap-1.5"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Replay
        </Button>
      </CardHeader>

      <CardContent className="p-0">
        <motion.div
          layout
          className="relative h-[640px] w-full overflow-hidden rounded-b-lg"
        >
          <ReactFlow
            nodes={nodes as Node[]}
            edges={edges as Edge[]}
            nodeTypes={NODE_TYPES}
            edgeTypes={EDGE_TYPES}
            fitView
            fitViewOptions={{ padding: 0.18, minZoom: 0.35, maxZoom: 1.4 }}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            panOnScroll={false}
            panOnDrag={false}
            preventScrolling={false}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={24}
              size={1}
              color="rgba(231,233,238,0.06)"
            />
          </ReactFlow>
        </motion.div>
      </CardContent>
    </Card>
  );
}

export function ExecutionDag(props: ExecutionDagProps) {
  return (
    <ReactFlowProvider>
      <ExecutionDagInner {...props} />
    </ReactFlowProvider>
  );
}
