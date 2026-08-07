"use client";

/**
 * Single source of truth for the Analyze screen.
 *
 * Robust against the two-stage backend: `getRun` polling is the backbone
 * (it exposes the decision + evaluation after the fast path, then adds
 * analyst_reports + bull/bear + judgment after enrichment), while SSE adds a
 * live event feed + stage timing on top. If SSE drops, polling still fills
 * everything in.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { toApiTicker } from "@/lib/tickers";
import type {
  AnalystReport,
  Decision,
  Market,
  Mode,
  RunDetail,
  RunStatus,
} from "@/types/api";

export interface EvaluationLike {
  composite_score?: number;
  data_coverage_pct?: number;
  pillar_scores?: Record<string, number>;
  final_signal_after_overrides?: string;
  active_overrides?: unknown[];
  [k: string]: unknown;
}

export interface LiveEvent {
  id: number;
  type: string;
  agent?: string;
  at: number;
}

export type StageState = "pending" | "active" | "done" | "error";
export interface Stage {
  id: string;
  label: string;
  kind: "core" | "analyst" | "synthesis";
  state: StageState;
  score?: number | null;
}

const ANALYST_STAGES: ReadonlyArray<{ id: string; label: string }> = [
  { id: "fundamentals", label: "Fundamentals" },
  { id: "technicals", label: "Technicals" },
  { id: "sentiment", label: "Sentiment" },
  { id: "macro", label: "Macro" },
  { id: "risk", label: "Risk" },
];

function isTerminal(s: RunStatus | "idle"): boolean {
  return s === "complete" || s === "error" || s === "interrupted";
}

export interface AnalysisState {
  runId: string | null;
  status: RunStatus | "idle";
  isRunning: boolean;
  isTerminal: boolean;
  decision: Decision | null;
  evaluation: EvaluationLike | null;
  analystReports: Record<string, AnalystReport>;
  bullCase: Record<string, unknown> | null;
  bearCase: Record<string, unknown> | null;
  judgment: Record<string, unknown> | null;
  interrupt: Record<string, unknown> | null;
  error: string | null;
  events: LiveEvent[];
  stages: Stage[];
  start: () => void;
  restart: () => void;
  resume: () => void;
}

export function useAnalysis(opts: {
  ticker: string;
  market: Market;
  mode?: Mode;
  autoStart?: boolean;
}): AnalysisState {
  const { ticker, market, mode = "long_term", autoStart = true } = opts;
  const qc = useQueryClient();

  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [activeAgents, setActiveAgents] = useState<Record<string, StageState>>({});
  const [resuming, setResuming] = useState(false);
  const evtSeq = useRef(0);

  const analyzeMut = useMutation({
    mutationFn: () => api.analyze({ ticker: toApiTicker(ticker, market), market, mode }),
    onSuccess: (res) => {
      setEvents([]);
      setActiveAgents({});
      setRunId(res.run_id);
    },
  });

  const start = useCallback(() => {
    if (!ticker) return;
    analyzeMut.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, market, mode]);

  // Auto-start when the ticker changes.
  useEffect(() => {
    if (autoStart && ticker) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, market, mode]);

  const runQuery = useQuery({
    queryKey: ["analysis-run", runId],
    queryFn: () => api.getRun(runId as string),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (s === "complete" || s === "error") return false;
      if (s === "interrupted" && !resuming) return false;
      return 1200;
    },
  });

  // Reset the resume flag once the resumed run settles.
  useEffect(() => {
    const s = runQuery.data?.status;
    if (resuming && (s === "complete" || s === "error")) setResuming(false);
  }, [runQuery.data?.status, resuming]);

  const resume = useCallback(() => setResuming(true), []);

  const run: RunDetail | undefined = runQuery.data;
  const status: RunStatus | "idle" = run?.status ?? (runId ? "pending" : "idle");

  // Live SSE feed — best-effort. Drives the event ticker + analyst stage timing.
  useEffect(() => {
    if (!runId) return;
    let closed = false;
    const es = new EventSource(api.runStreamUrl(runId));

    const onEvt = (e: MessageEvent) => {
      if (closed) return;
      let parsed: { type?: string; data?: Record<string, unknown> } = {};
      try {
        parsed = JSON.parse(e.data);
      } catch {
        return;
      }
      const type = parsed.type ?? "";
      const agent = (parsed.data?.agent as string | undefined) ?? undefined;

      evtSeq.current += 1;
      setEvents((prev) =>
        [...prev, { id: evtSeq.current, type, agent, at: Date.now() }].slice(-60),
      );

      if (agent) {
        if (type === "agent_start") {
          setActiveAgents((m) => ({ ...m, [agent]: "active" }));
        } else if (type === "agent_complete") {
          setActiveAgents((m) => ({ ...m, [agent]: "done" }));
        }
      }
      // A late poll picks up the authoritative snapshot on terminal events.
      if (type === "_terminal_" || type === "decision" || type === "error") {
        qc.invalidateQueries({ queryKey: ["analysis-run", runId] });
      }
    };

    es.onmessage = onEvt;
    es.onerror = () => {
      /* polling is the fallback; let EventSource retry silently */
    };

    return () => {
      closed = true;
      es.close();
    };
  }, [runId, qc]);

  const decision = run?.decision ?? null;
  const evaluation = (run?.evaluation as EvaluationLike | null) ?? null;
  const analystReports = run?.analyst_reports ?? {};

  const stages = useMemo<Stage[]>(() => {
    const decisionReady = !!decision;
    const core: Stage[] = [
      { id: "parse", label: "Parse", kind: "core", state: runId ? "done" : "pending" },
      {
        id: "context",
        label: "Market Data",
        kind: "core",
        state: decisionReady ? "done" : runId ? "active" : "pending",
      },
      {
        id: "rules",
        label: "Rule Engine",
        kind: "core",
        state: decisionReady ? "done" : "pending",
      },
      {
        id: "decision",
        label: "Decision",
        kind: "core",
        state: decisionReady ? "done" : "pending",
      },
    ];

    const analysts: Stage[] = ANALYST_STAGES.map((a) => {
      const report = analystReports[a.id];
      let state: StageState = activeAgents[a.id] ?? "pending";
      if (report) state = "done";
      else if (!decisionReady) state = "pending";
      else if (state === "pending" && !isTerminal(status)) state = "active";
      return {
        id: a.id,
        label: a.label,
        kind: "analyst",
        state,
        score: report?.score ?? null,
      };
    });

    const hasDebate = !!run?.bull_case || !!run?.bear_case;
    const hasJudge = !!run?.judgment;
    const synthesis: Stage[] = [
      {
        id: "debate",
        label: "Bull vs Bear",
        kind: "synthesis",
        state: hasDebate
          ? "done"
          : activeAgents["debate"] ?? (isTerminal(status) ? "done" : "pending"),
      },
      {
        id: "judge",
        label: "Judge",
        kind: "synthesis",
        state: hasJudge
          ? "done"
          : activeAgents["judge"] ?? (isTerminal(status) ? "done" : "pending"),
      },
    ];

    return [...core, ...analysts, ...synthesis];
  }, [runId, decision, analystReports, activeAgents, run, status]);

  return {
    runId,
    status,
    isRunning: !!runId && !isTerminal(status),
    isTerminal: isTerminal(status),
    decision,
    evaluation,
    analystReports,
    bullCase: run?.bull_case ?? null,
    bearCase: run?.bear_case ?? null,
    judgment: run?.judgment ?? null,
    interrupt: run?.interrupt ?? null,
    error: run?.error ?? (analyzeMut.error ? String(analyzeMut.error) : null),
    events,
    stages,
    start,
    restart: start,
    resume,
  };
}
