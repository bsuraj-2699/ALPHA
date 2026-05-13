"use client";

import * as React from "react";

import { api } from "@/lib/api";
import {
  AGENT_META,
  type AgentMeta,
  type AgentNode,
  type AgentStatus,
  getAgentMeta,
} from "@/lib/agents";
import type { Decision, ReasoningStep } from "@/types/api";

/**
 * Per-run streaming state derived from the SSE feed.
 *
 * Each agent has its own slot keyed by node name. As events arrive we
 * fold them into per-agent rows: agent_start -> running, thinking ->
 * accumulate streaming text, agent_complete -> complete, error -> error.
 *
 * The hook itself is dumb about visualisation — the UI components decide
 * how to render the typewriter / collapse states from this snapshot.
 */

export interface AgentSlot {
  meta: AgentMeta;
  status: AgentStatus;
  /** ISO timestamp of the agent_start event */
  startedAt?: string;
  /** Wall time the node took, from agent_complete.duration_ms */
  durationMs?: number;
  /** One-line summary the orchestrator produced */
  summary?: string;
  /** Full reasoning text from the `thinking` event */
  reasoning?: string;
  /** Full payload dict from agent_complete (e.g. { score, narrative, ... }) */
  payload?: Record<string, unknown>;
  /** Error message, if status === "error" */
  error?: string;
}

export interface RunStreamState {
  status: "idle" | "connecting" | "running" | "complete" | "error" | "interrupted";
  /** All known agents, in canonical execution order */
  agents: AgentSlot[];
  /** The final Decision if any decision event has fired */
  decision: Decision | null;
  /** Last error, if any */
  error: string | null;
  /** Whether the SSE connection is open right now */
  live: boolean;
  /** Total events received (useful for debug overlays) */
  eventCount: number;
}

type Action =
  | { type: "connect" }
  | { type: "agent_start"; node: string; ts: string }
  | {
      type: "agent_complete";
      node: string;
      summary?: string;
      duration_ms?: number;
      payload?: Record<string, unknown>;
    }
  | { type: "thinking"; step: ReasoningStep }
  | { type: "decision"; decision: Decision }
  | {
      type: "error";
      node?: string;
      error: string;
    }
  | { type: "interrupted"; payload?: Record<string, unknown> }
  | { type: "close"; reason?: string }
  | { type: "reset" };

function makeInitialAgents(): AgentSlot[] {
  return AGENT_META.map((meta) => ({ meta, status: "pending" }));
}

function initialState(): RunStreamState {
  return {
    status: "idle",
    agents: makeInitialAgents(),
    decision: null,
    error: null,
    live: false,
    eventCount: 0,
  };
}

function patchAgent(
  agents: AgentSlot[],
  node: string,
  patch: Partial<AgentSlot>,
): AgentSlot[] {
  const meta = getAgentMeta(node);
  if (!meta) return agents;
  return agents.map((a) =>
    a.meta.node === node ? { ...a, ...patch } : a,
  );
}

function reduce(state: RunStreamState, action: Action): RunStreamState {
  switch (action.type) {
    case "reset":
      return initialState();

    case "connect":
      return { ...state, status: "connecting", live: true };

    case "agent_start":
      return {
        ...state,
        status: state.status === "idle" || state.status === "connecting"
          ? "running"
          : state.status,
        eventCount: state.eventCount + 1,
        agents: patchAgent(state.agents, action.node, {
          status: "running",
          startedAt: action.ts,
        }),
      };

    case "agent_complete":
      return {
        ...state,
        eventCount: state.eventCount + 1,
        agents: patchAgent(state.agents, action.node, {
          status: "complete",
          summary: action.summary,
          durationMs: action.duration_ms,
          payload: action.payload,
        }),
      };

    case "thinking": {
      // ReasoningStep carries the full free-form output for that node.
      // We store it on the matching agent slot so the row can render
      // the full text on expand.
      const node = action.step.agent;
      return {
        ...state,
        eventCount: state.eventCount + 1,
        agents: patchAgent(state.agents, node, {
          reasoning: action.step.output,
        }),
      };
    }

    case "decision":
      return {
        ...state,
        status: "complete",
        eventCount: state.eventCount + 1,
        decision: action.decision,
        live: false,
      };

    case "error":
      return {
        ...state,
        status: "error",
        eventCount: state.eventCount + 1,
        error: action.error,
        agents: action.node
          ? patchAgent(state.agents, action.node, {
              status: "error",
              error: action.error,
            })
          : state.agents,
        live: false,
      };

    case "interrupted":
      return {
        ...state,
        status: "interrupted",
        eventCount: state.eventCount + 1,
        live: false,
      };

    case "close":
      return { ...state, live: false };
  }
}

interface Envelope {
  type: string;
  data: Record<string, unknown>;
  ts?: string;
}

function parseEnvelope(raw: string): Envelope | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "type" in parsed &&
      "data" in parsed
    ) {
      return parsed as Envelope;
    }
  } catch {
    /* fallthrough */
  }
  return null;
}

/**
 * Subscribe to /api/runs/{runId}/stream as Server-Sent Events.
 *
 * Pass `null` for runId to stay disconnected. Returns the live derived
 * state plus a `reset` callback used when the user kicks off another run.
 */
export function useRunStream(runId: string | null): RunStreamState & {
  reset: () => void;
} {
  const [state, dispatch] = React.useReducer(reduce, undefined, initialState);

  // Clear stale "complete" / agents before paint when `runId` changes so
  // parents do not read the previous run's terminal state on the first render
  // of a new analysis.
  React.useLayoutEffect(() => {
    dispatch({ type: "reset" });
  }, [runId]);

  React.useEffect(() => {
    if (!runId) {
      return;
    }

    dispatch({ type: "connect" });

    const url = api.runStreamUrl(runId);
    const source = new EventSource(url, { withCredentials: false });

    const onAgentStart = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) return;
      const node = (env.data as { node?: string }).node ?? "";
      dispatch({ type: "agent_start", node, ts: env.ts ?? "" });
    };

    const onAgentComplete = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) return;
      const data = env.data as {
        node?: string;
        summary?: string;
        duration_ms?: number;
        payload?: Record<string, unknown>;
      };
      dispatch({
        type: "agent_complete",
        node: data.node ?? "",
        summary: data.summary,
        duration_ms: data.duration_ms,
        payload: data.payload,
      });
    };

    const onThinking = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) return;
      // env.data IS the ReasoningStep dump
      dispatch({ type: "thinking", step: env.data as unknown as ReasoningStep });
    };

    const onDecision = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) return;
      dispatch({
        type: "decision",
        decision: env.data as unknown as Decision,
      });
      // The server closes after a decision, but be explicit:
      source.close();
    };

    const onErrorEvent = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) {
        dispatch({ type: "error", error: "Stream error" });
        source.close();
        return;
      }
      const data = env.data as { node?: string; error?: string };
      dispatch({
        type: "error",
        node: data.node,
        error: data.error ?? "Unknown error",
      });
      source.close();
    };

    const onInterrupted = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      dispatch({
        type: "interrupted",
        payload: env?.data ?? {},
      });
      source.close();
    };

    // Register handlers for each named SSE event we know about. Anything
    // we don't recognise is harmless; EventSource just discards it.
    source.addEventListener("agent_start", onAgentStart);
    source.addEventListener("agent_complete", onAgentComplete);
    source.addEventListener("thinking", onThinking);
    source.addEventListener("decision", onDecision);
    source.addEventListener("error", onErrorEvent);
    source.addEventListener("interrupted", onInterrupted);

    // Default `message` event covers any provider that didn't set the
    // event name explicitly.
    source.onmessage = (e: MessageEvent) => {
      const env = parseEnvelope(e.data);
      if (!env) return;
      switch (env.type) {
        case "agent_start":
          onAgentStart(e);
          break;
        case "agent_complete":
          onAgentComplete(e);
          break;
        case "thinking":
          onThinking(e);
          break;
        case "decision":
          onDecision(e);
          break;
        case "error":
          onErrorEvent(e);
          break;
        case "interrupted":
          onInterrupted(e);
          break;
      }
    };

    source.onerror = () => {
      // EventSource auto-reconnects on transient errors; if it permanently
      // failed, readyState will be CLOSED. We surface that as a closed
      // stream but don't promote to a fatal error — the run might be
      // legitimately complete and the server-side stream has just shut.
      if (source.readyState === EventSource.CLOSED) {
        dispatch({ type: "close" });
      }
    };

    return () => {
      source.close();
      dispatch({ type: "close" });
    };
  }, [runId]);

  const reset = React.useCallback(() => dispatch({ type: "reset" }), []);

  return React.useMemo(() => ({ ...state, reset }), [state, reset]);
}

/**
 * Build the same per-agent slot shape from a completed run's
 * `reasoning_trace`, so the trace inspector can render an identical
 * timeline / DAG without subscribing to SSE.
 */
export function deriveAgentsFromTrace(
  trace: ReasoningStep[] | undefined,
): AgentSlot[] {
  const slots = makeInitialAgents();
  if (!trace) return slots;

  const byNode: Map<AgentNode, ReasoningStep> = new Map();
  for (const step of trace) {
    const meta = getAgentMeta(step.agent);
    if (!meta) continue;
    byNode.set(meta.node, step);
  }

  return slots.map((slot) => {
    const step = byNode.get(slot.meta.node);
    if (!step) return slot;
    return {
      ...slot,
      status: "complete" as const,
      reasoning: step.output,
      durationMs: step.duration_ms,
      startedAt: step.timestamp,
    };
  });
}
