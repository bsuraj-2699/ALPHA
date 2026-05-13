"use client";

import * as React from "react";

/**
 * Animate a numeric display from its previous value to `target` over
 * `durationMs`, using requestAnimationFrame and an easeOutCubic curve.
 *
 * Returns the current animated value. Re-rendering the parent every
 * frame is fine for the few number cells we're animating.
 */
export function useCountUp(
  target: number,
  durationMs = 700,
): number {
  const [value, setValue] = React.useState(target);
  const fromRef = React.useRef(target);
  const startRef = React.useRef<number | null>(null);
  const rafRef = React.useRef<number | null>(null);

  React.useEffect(() => {
    fromRef.current = value;
    startRef.current = null;

    const tick = (now: number) => {
      if (startRef.current === null) startRef.current = now;
      const elapsed = now - startRef.current;
      const t = Math.min(1, elapsed / Math.max(1, durationMs));
      // easeOutCubic
      const eased = 1 - Math.pow(1 - t, 3);
      const next = fromRef.current + (target - fromRef.current) * eased;
      setValue(next);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // The animation should retrigger ONLY on target change, not on
    // intermediate `value` updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs]);

  return value;
}

/**
 * Reveal a string character by character at a fixed cadence.
 * Used by the typewriter effect in the reasoning stream.
 */
export function useTypewriter(
  text: string,
  charsPerSecond = 80,
): string {
  const [shown, setShown] = React.useState("");
  const targetRef = React.useRef(text);
  const idxRef = React.useRef(0);

  React.useEffect(() => {
    if (text !== targetRef.current) {
      // Text changed — restart from where we are if the new text starts
      // with the old prefix (avoids re-typing from scratch when a `thinking`
      // event arrives after we've already revealed something).
      targetRef.current = text;
      if (!text.startsWith(shown)) {
        idxRef.current = 0;
        setShown("");
      }
    }
    if (idxRef.current >= text.length) {
      setShown(text);
      return;
    }

    const intervalMs = Math.max(8, 1000 / charsPerSecond);
    const id = window.setInterval(() => {
      idxRef.current += 1;
      if (idxRef.current >= text.length) {
        setShown(text);
        window.clearInterval(id);
        return;
      }
      setShown(text.slice(0, idxRef.current));
    }, intervalMs);

    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, charsPerSecond]);

  return shown;
}
