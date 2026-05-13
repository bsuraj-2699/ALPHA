"use client";

import * as React from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import type { AgentMeta, AgentStatus } from "@/lib/agents";

export interface AgentNodeData extends Record<string, unknown> {
  meta: AgentMeta;
  status: AgentStatus;
  score?: number | null;
  durationMs?: number | null;
}

export type AgentFlowNode = Node<AgentNodeData, "agent">;

const STATUS_RING: Record<AgentStatus, string> = {
  pending: "ring-border",
  running: "ring-warn/70",
  complete: "ring-buy/60",
  error: "ring-sell/70",
};

const STATUS_GLOW: Record<AgentStatus, string> = {
  pending: "",
  running: "shadow-[0_0_24px_rgba(245,166,35,0.35)]",
  complete: "shadow-[0_0_24px_rgba(0,229,160,0.30)]",
  error: "shadow-[0_0_24px_rgba(255,77,109,0.30)]",
};

const STATUS_LABEL: Record<AgentStatus, string> = {
  pending: "queued",
  running: "running",
  complete: "complete",
  error: "error",
};

const STATUS_LABEL_TONE: Record<AgentStatus, string> = {
  pending: "text-muted-foreground",
  running: "text-warn",
  complete: "text-buy",
  error: "text-sell",
};

/**
 * Custom react-flow node for an orchestrator agent. Status drives the
 * ring color, glow, and a small running/complete indicator. Tap-targets
 * are on the node (parent will handle click via react-flow's onNodeClick).
 */
function AgentNodeImpl({ data }: NodeProps<AgentFlowNode>) {
  const { meta, status, score, durationMs } = data;
  const isRunning = status === "running";

  return (
    <motion.div
      layout
      transition={{ type: "spring", stiffness: 320, damping: 36 }}
      className={cn(
        "relative w-[150px] rounded-lg border border-border bg-card/85 px-3 py-2.5 ring-1 ring-inset transition-colors backdrop-blur-sm",
        STATUS_RING[status],
        STATUS_GLOW[status],
        status === "pending" && "opacity-70",
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />

      {/* Running pulse: outer halo */}
      {isRunning && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-lg ring-2 ring-warn/40 animate-pulse"
        />
      )}

      <div className="flex items-center gap-2">
        <div
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold text-foreground/90",
            status === "pending" && "opacity-60",
          )}
          style={{ background: meta.avatar }}
        >
          {meta.initial}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate font-display text-sm font-semibold leading-tight">
            {meta.displayName}
          </span>
          <span
            className={cn(
              "text-[10px] uppercase tracking-[0.14em]",
              STATUS_LABEL_TONE[status],
            )}
          >
            {STATUS_LABEL[status]}
          </span>
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between">
        {meta.hasPillarScore && typeof score === "number" ? (
          <span className="font-mono text-xs tabular-nums text-foreground/85">
            {score.toFixed(1)}
          </span>
        ) : (
          <span className="text-[10px] text-muted-foreground">{meta.phase}</span>
        )}
        {typeof durationMs === "number" && status === "complete" && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {durationMs}ms
          </span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-1.5 !w-1.5 !border-0 !bg-border"
      />
    </motion.div>
  );
}

export const AgentNode = React.memo(AgentNodeImpl);
AgentNode.displayName = "AgentNode";
