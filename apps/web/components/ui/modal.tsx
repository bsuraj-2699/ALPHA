"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  /** Footer slot — usually action buttons. */
  footer?: React.ReactNode;
  className?: string;
  /** Optional max-width tailwind class — defaults to `max-w-lg`. */
  maxWidthClass?: string;
}

/**
 * Lightweight, dependency-free modal.
 *
 * Renders into a portal anchored at `<body>`, traps `Escape`, and
 * mounts only when `open` flips true so SSR stays clean. We intentionally
 * skip a full Radix-Dialog dep — the surface here is small and the
 * existing Tailwind animation utilities cover the motion budget.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
  maxWidthClass = "max-w-lg",
}: ModalProps) {
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
        >
          <motion.div
            className="absolute inset-0 bg-background/70 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
          />

          <motion.div
            className={cn(
              "relative z-10 w-full overflow-hidden rounded-xl border border-border bg-card shadow-2xl ring-1 ring-inset ring-border",
              maxWidthClass,
              className,
            )}
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 320, damping: 28 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-border p-5 pb-4">
              <div className="flex min-w-0 flex-col gap-1">
                {title && (
                  <h2 className="font-display text-lg font-semibold leading-tight text-foreground">
                    {title}
                  </h2>
                )}
                {description && (
                  <p className="text-xs text-muted-foreground">{description}</p>
                )}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto p-5">{children}</div>

            {footer && (
              <div className="flex items-center justify-end gap-2 border-t border-border bg-background/40 px-5 py-3">
                {footer}
              </div>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
