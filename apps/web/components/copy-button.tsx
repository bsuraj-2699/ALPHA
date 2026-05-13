"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  value: string | number | null | undefined;
  /** Aria label override (default: "Copy"). */
  label?: string;
  className?: string;
}

/**
 * Small icon button with a confirm-tick affordance. Holds the copied
 * state for 1.4 s before reverting to the copy icon.
 */
export function CopyButton({ value, label = "Copy", className }: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);

  const onClick = React.useCallback(async () => {
    if (value === null || value === undefined) return;
    const text = String(value);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* swallow — clipboard might be denied; don't crash the UI. */
    }
  }, [value]);

  const disabled = value === null || value === undefined;

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "h-7 w-7 text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      <AnimatePresence mode="wait" initial={false}>
        {copied ? (
          <motion.span
            key="ok"
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.6, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex h-full w-full items-center justify-center"
          >
            <Check className="h-3.5 w-3.5 text-buy" />
          </motion.span>
        ) : (
          <motion.span
            key="copy"
            initial={{ scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.6, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex h-full w-full items-center justify-center"
          >
            <Copy className="h-3.5 w-3.5" />
          </motion.span>
        )}
      </AnimatePresence>
    </Button>
  );
}
