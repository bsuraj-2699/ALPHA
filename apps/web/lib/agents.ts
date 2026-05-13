/**
 * Agent metadata: ordering, display names, accent colors.
 *
 * Node names match the orchestrator's LangGraph node IDs exactly — see
 * `packages/agents/orchestrator.py`. This is the authoritative list of
 * what can appear in a `reasoning_trace` entry or an SSE event.
 */

export type AgentNode =
  | "parse"
  | "context_build"
  | "fundamentals"
  | "technicals"
  | "sentiment"
  | "macro"
  | "risk"
  | "debate"
  | "judge"
  | "decide";

export type AgentPhase = "intake" | "analyst" | "synthesis" | "decision";

export interface AgentMeta {
  node: AgentNode;
  /** UI label */
  displayName: string;
  /** One-line role description for tooltips / expanded views */
  blurb: string;
  /** Single-letter monogram in the avatar */
  initial: string;
  /** Hex avatar background — keep low-saturation so the gold accent pops */
  avatar: string;
  /** Phase grouping used for layout in the DAG and the stream timeline */
  phase: AgentPhase;
  /** Whether this agent emits a numeric pillar score */
  hasPillarScore: boolean;
  /** Public key under `analyst_reports` for agents with pillar scores */
  analystKey?: "fundamentals" | "technicals" | "sentiment" | "macro" | "risk";
}

export const AGENT_META: ReadonlyArray<AgentMeta> = [
  {
    node: "parse",
    displayName: "Parser",
    blurb: "Identifies ticker + market from the natural-language query.",
    initial: "P",
    avatar: "#3b4a6b",
    phase: "intake",
    hasPillarScore: false,
  },
  {
    node: "context_build",
    displayName: "Context",
    blurb: "Assembles market data, fundamentals and macro snapshots.",
    initial: "C",
    avatar: "#2c5168",
    phase: "intake",
    hasPillarScore: false,
  },
  {
    node: "fundamentals",
    displayName: "Fundamentals",
    blurb: "Earnings, balance sheet, growth, valuation deltas.",
    initial: "F",
    avatar: "#6b5a2c",
    phase: "analyst",
    hasPillarScore: true,
    analystKey: "fundamentals",
  },
  {
    node: "technicals",
    displayName: "Technicals",
    blurb: "Trend, momentum, MA crossovers, breadth.",
    initial: "T",
    avatar: "#2c6b65",
    phase: "analyst",
    hasPillarScore: true,
    analystKey: "technicals",
  },
  {
    node: "sentiment",
    displayName: "Sentiment",
    blurb: "News flow, social, analyst-rating drift.",
    initial: "S",
    avatar: "#4f2c6b",
    phase: "analyst",
    hasPillarScore: true,
    analystKey: "sentiment",
  },
  {
    node: "macro",
    displayName: "Macro",
    blurb: "Rates, FX, sector rotation, regime.",
    initial: "M",
    avatar: "#6b3f2c",
    phase: "analyst",
    hasPillarScore: true,
    analystKey: "macro",
  },
  {
    node: "risk",
    displayName: "Risk",
    blurb: "Volatility, drawdown, position-size constraints.",
    initial: "R",
    avatar: "#6b2c4d",
    phase: "analyst",
    hasPillarScore: true,
    analystKey: "risk",
  },
  {
    node: "debate",
    displayName: "Debate",
    blurb: "Bull and bear cases stated to their strongest form.",
    initial: "D",
    avatar: "#5c3b1f",
    phase: "synthesis",
    hasPillarScore: false,
  },
  {
    node: "judge",
    displayName: "Judge",
    blurb: "Synthesizes deterministic scores + narratives. No decisions.",
    initial: "J",
    avatar: "#2c5a3f",
    phase: "synthesis",
    hasPillarScore: false,
  },
  {
    node: "decide",
    displayName: "Decision",
    blurb: "Emits the final signal, position size, entry/stop/target.",
    initial: "✓",
    avatar: "#6f5621",
    phase: "decision",
    hasPillarScore: false,
  },
];

const META_BY_NODE: Record<AgentNode, AgentMeta> = AGENT_META.reduce(
  (acc, m) => {
    acc[m.node] = m;
    return acc;
  },
  {} as Record<AgentNode, AgentMeta>,
);

export function getAgentMeta(node: string): AgentMeta | undefined {
  return META_BY_NODE[node as AgentNode];
}

export const ANALYST_NODES: ReadonlyArray<AgentNode> = [
  "fundamentals",
  "technicals",
  "sentiment",
  "macro",
  "risk",
];

export type AgentStatus = "pending" | "running" | "complete" | "error";
