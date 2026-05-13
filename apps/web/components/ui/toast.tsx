"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, TriangleAlert, XCircle, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Lightweight, dependency-free toast system.
 *
 * Mirrors the API surface of `sonner` so swapping it out later is a
 * one-line change. Subscribe to the imperative `toast` singleton from
 * anywhere — server components excluded — without needing a provider
 * other than `<Toaster />`, which the root layout mounts once.
 */

export type ToastTone = "success" | "error" | "warn" | "info";

interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Auto-dismiss after this many ms. 0 = sticky. */
  durationMs?: number;
}

interface ToastRecord extends Required<Omit<ToastInput, "description">> {
  id: number;
  description?: string;
}

type Listener = (toasts: ToastRecord[]) => void;

class ToastBus {
  private toasts: ToastRecord[] = [];
  private listeners = new Set<Listener>();
  private nextId = 1;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.toasts);
    return () => {
      this.listeners.delete(listener);
    };
  }

  push(input: ToastInput): number {
    const id = this.nextId++;
    const record: ToastRecord = {
      id,
      title: input.title,
      tone: input.tone ?? "info",
      durationMs: input.durationMs ?? 4000,
      ...(input.description !== undefined && { description: input.description }),
    };
    this.toasts = [...this.toasts, record];
    this.emit();
    if (record.durationMs > 0) {
      window.setTimeout(() => this.dismiss(id), record.durationMs);
    }
    return id;
  }

  dismiss(id: number): void {
    const before = this.toasts.length;
    this.toasts = this.toasts.filter((t) => t.id !== id);
    if (this.toasts.length !== before) this.emit();
  }

  private emit(): void {
    for (const l of this.listeners) l(this.toasts);
  }
}

const bus = new ToastBus();

/** Imperative toast API — call from anywhere on the client. */
export const toast = {
  success: (title: string, description?: string) =>
    bus.push({ title, ...(description !== undefined && { description }), tone: "success" }),
  error: (title: string, description?: string) =>
    bus.push({ title, ...(description !== undefined && { description }), tone: "error" }),
  warn: (title: string, description?: string) =>
    bus.push({ title, ...(description !== undefined && { description }), tone: "warn" }),
  info: (title: string, description?: string) =>
    bus.push({ title, ...(description !== undefined && { description }), tone: "info" }),
  show: (input: ToastInput) => bus.push(input),
  dismiss: (id: number) => bus.dismiss(id),
};

const TONE_STYLES: Record<
  ToastTone,
  { ring: string; icon: React.ReactNode; iconColor: string }
> = {
  success: {
    ring: "ring-buy/30",
    icon: <CheckCircle2 className="h-4 w-4" />,
    iconColor: "text-buy",
  },
  error: {
    ring: "ring-sell/30",
    icon: <XCircle className="h-4 w-4" />,
    iconColor: "text-sell",
  },
  warn: {
    ring: "ring-warn/30",
    icon: <TriangleAlert className="h-4 w-4" />,
    iconColor: "text-warn",
  },
  info: {
    ring: "ring-gold/30",
    icon: <Info className="h-4 w-4" />,
    iconColor: "text-gold",
  },
};

export function Toaster() {
  const [items, setItems] = React.useState<ToastRecord[]>([]);
  React.useEffect(() => bus.subscribe(setItems), []);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
    >
      <AnimatePresence initial={false}>
        {items.map((t) => {
          const style = TONE_STYLES[t.tone];
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, x: 24, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, scale: 0.96 }}
              transition={{ type: "spring", stiffness: 380, damping: 28 }}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-xl border border-border bg-card/95 p-3 shadow-xl ring-1 ring-inset backdrop-blur",
                style.ring,
              )}
              role="status"
            >
              <span className={cn("mt-0.5 shrink-0", style.iconColor)}>
                {style.icon}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <p className="text-sm font-medium leading-snug text-foreground">
                  {t.title}
                </p>
                {t.description && (
                  <p className="text-xs leading-snug text-muted-foreground">
                    {t.description}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => bus.dismiss(t.id)}
                className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground"
                aria-label="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
