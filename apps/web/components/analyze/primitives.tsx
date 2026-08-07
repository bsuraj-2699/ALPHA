"use client";

import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useSpring,
  type MotionValue,
} from "framer-motion";
import { useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* GlassCard — glass panel with an optional pointer-driven 3D tilt.    */
/* ------------------------------------------------------------------ */
export function GlassCard({
  children,
  className,
  tilt = false,
  strong = false,
  glow,
}: {
  children: ReactNode;
  className?: string;
  tilt?: boolean;
  strong?: boolean;
  glow?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const rx = useSpring(useMotionValue(0), { stiffness: 250, damping: 22 });
  const ry = useSpring(useMotionValue(0), { stiffness: 250, damping: 22 });
  const gx = useMotionValue(50);
  const gy = useMotionValue(0);
  const sheen = useMotionTemplate`radial-gradient(600px circle at ${gx}% ${gy}%, rgba(255,255,255,0.06), transparent 40%)`;

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    if (!tilt || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    ry.set((px - 0.5) * 9);
    rx.set((0.5 - py) * 9);
    gx.set(px * 100);
    gy.set(py * 100);
  }
  function onLeave() {
    rx.set(0);
    ry.set(0);
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={tilt ? { rotateX: rx, rotateY: ry, transformStyle: "preserve-3d" } : undefined}
      className={cn(
        strong ? "glass-strong" : "glass",
        "ring-gradient relative overflow-hidden rounded-2xl",
        glow,
        className,
      )}
    >
      {tilt && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: sheen }}
        />
      )}
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* Radial gauge (SVG arc).                                            */
/* ------------------------------------------------------------------ */
export function Gauge({
  value,
  max = 100,
  size = 132,
  stroke = 10,
  color,
  label,
  sublabel,
}: {
  value: number;
  max?: number;
  size?: number;
  stroke?: number;
  color: string;
  label: ReactNode;
  sublabel?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value / max));
  const dash = c * pct;

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={stroke}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c - dash }}
          transition={{ duration: 1, ease: "easeOut" }}
          style={{ filter: `drop-shadow(0 0 6px ${color})` }}
        />
      </svg>
      <div className="absolute inset-0 grid place-content-center text-center">
        <div className="font-mono text-2xl font-semibold tabular-nums text-foreground">
          {label}
        </div>
        {sublabel && (
          <div className="mt-0.5 text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
            {sublabel}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* SignalOrb — a floating 3D-ish orb whose color reflects the signal. */
/* ------------------------------------------------------------------ */
export function SignalOrb({
  color,
  active = true,
  size = 120,
}: {
  color: string;
  active?: boolean;
  size?: number;
}) {
  return (
    <div
      className={cn("relative shrink-0", active && "animate-float")}
      style={{ width: size, height: size }}
    >
      <div
        className={cn("absolute inset-0 rounded-full blur-2xl", active && "animate-orb")}
        style={{ background: color, opacity: 0.35 }}
      />
      <div
        className={cn("absolute inset-[14%] rounded-full", active && "animate-spin-slow")}
        style={{
          background: `conic-gradient(from 0deg, ${color}, transparent 45%, ${color})`,
          opacity: 0.55,
          maskImage: "radial-gradient(circle, transparent 54%, #000 56%)",
          WebkitMaskImage: "radial-gradient(circle, transparent 54%, #000 56%)",
        }}
      />
      <div
        className="absolute inset-[24%] rounded-full"
        style={{
          background: `radial-gradient(circle at 35% 30%, color-mix(in oklab, ${color} 90%, white), ${color} 55%, color-mix(in oklab, ${color} 40%, black))`,
          boxShadow: `0 0 40px -6px ${color}, inset 0 -8px 20px rgba(0,0,0,0.5), inset 0 6px 14px rgba(255,255,255,0.25)`,
        }}
      />
      <div
        className="absolute rounded-full bg-white/70 blur-[2px]"
        style={{ width: size * 0.12, height: size * 0.12, left: "34%", top: "30%" }}
      />
    </div>
  );
}

export type { MotionValue };
