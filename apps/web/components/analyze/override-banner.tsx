"use client";

import * as React from "react";
import { ShieldAlert } from "lucide-react";
import { motion } from "framer-motion";

interface OverrideBannerProps {
  overrides: string[];
  signal: string;
}

/**
 * Red banner shown when one or more override rules (OVR-*) fired during
 * the run. These are deterministic "stop the press" rules — for example
 * fraud signals that force STRONG_SELL regardless of the composite score.
 *
 * Visually distinct from everything else on the page: pulsing border,
 * uppercase text, no card chrome.
 */
export function OverrideBanner({ overrides, signal }: OverrideBannerProps) {
  if (!overrides || overrides.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="relative overflow-hidden rounded-lg border border-sell/40 bg-sell/[0.06] p-4"
    >
      <span
        aria-hidden
        className="absolute inset-0 bg-sell/[0.04] [mask-image:linear-gradient(90deg,transparent,black,transparent)]"
      />
      <div className="relative flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-sell/15 ring-1 ring-inset ring-sell/40">
          <ShieldAlert className="h-4 w-4 text-sell" />
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="font-display text-base font-semibold text-sell">
              Override active · {signal}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-sell/80">
              {overrides.length} rule{overrides.length === 1 ? "" : "s"}
            </span>
          </div>
          <p className="text-sm text-foreground/85">
            One or more deterministic override rules fired and forced the
            final signal. Composite score and analyst narratives are
            informational; the decision is rule-driven.
          </p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {overrides.map((id) => (
              <span
                key={id}
                className="rounded bg-sell/15 px-2 py-0.5 font-mono text-[11px] text-sell ring-1 ring-inset ring-sell/30"
              >
                {id}
              </span>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
