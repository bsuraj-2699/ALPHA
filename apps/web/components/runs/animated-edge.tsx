"use client";

import * as React from "react";
import {
  BaseEdge,
  getBezierPath,
  type EdgeProps,
  type Edge,
} from "@xyflow/react";

export type EdgeMode = "idle" | "active" | "settled";

export interface AnimatedEdgeData extends Record<string, unknown> {
  mode: EdgeMode;
}

export type FlowEdge = Edge<AnimatedEdgeData, "animated">;

/**
 * Custom edge:
 *   - `idle`     subtle border-color stroke, no animation
 *   - `active`   green stroke, traveling dot along the path
 *   - `settled`  solid green stroke, no dot (target finished)
 *
 * The traveling dot is an SVG <circle> using <animateMotion> referencing
 * the edge path by id. We render our own <path id={id}> alongside the
 * BaseEdge so the motion has a stable target — BaseEdge does the
 * pointer-events / hit-testing work, our path is purely visual.
 */
function AnimatedEdgeImpl(props: EdgeProps<FlowEdge>) {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    data,
    markerEnd,
  } = props;

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const mode: EdgeMode = data?.mode ?? "idle";

  const stroke =
    mode === "idle"
      ? "rgba(231, 233, 238, 0.16)"
      : mode === "active"
        ? "rgba(0, 229, 160, 0.85)"
        : "rgba(0, 229, 160, 0.55)";

  const dashArray = mode === "active" ? "6 4" : undefined;

  // A unique <path> for the motion's mpath reference.
  const motionPathId = `motion-${id}`;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke,
          strokeWidth: mode === "idle" ? 1 : 1.5,
          strokeDasharray: dashArray,
          transition: "stroke 200ms ease",
        }}
      />

      {/* Hidden path consumed by the <animateMotion> reference. */}
      <path id={motionPathId} d={edgePath} fill="none" stroke="none" />

      {mode === "active" && (
        <>
          <circle r="3" fill="#c9a84c">
            <animateMotion dur="1.4s" repeatCount="indefinite">
              <mpath xlinkHref={`#${motionPathId}`} />
            </animateMotion>
          </circle>
          <circle r="2" fill="rgba(0, 229, 160, 0.85)">
            <animateMotion
              dur="1.4s"
              repeatCount="indefinite"
              begin="0.6s"
            >
              <mpath xlinkHref={`#${motionPathId}`} />
            </animateMotion>
          </circle>
        </>
      )}
    </>
  );
}

export const AnimatedEdge = React.memo(AnimatedEdgeImpl);
AnimatedEdge.displayName = "AnimatedEdge";
