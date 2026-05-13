"use client";

import * as React from "react";
import { Check, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cn } from "@/lib/utils";
import { INDIAN_TICKERS, toDisplayTicker, type TickerOption } from "@/lib/tickers";

interface TickerMultiSelectProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (symbols: string[]) => void | Promise<void>;
  /** Tickers already in the bucket — pre-selected and disabled. */
  alreadyAdded?: ReadonlyArray<string>;
  /** Hard cap on how many can be selected per call (default: 5). */
  maxSelect?: number;
  /** Override the option list — defaults to INDIAN_TICKERS. */
  options?: ReadonlyArray<TickerOption>;
  title?: string;
  description?: string;
  confirmLabel?: string;
  /** Show a busy state on the confirm button. */
  busy?: boolean;
}

/**
 * Premium multi-select picker with a 5-symbol cap. Designed for the
 * Runs page "Add ticker" flow but reused anywhere a bounded ticker
 * batch needs to be chosen.
 */
export function TickerMultiSelect({
  open,
  onClose,
  onConfirm,
  alreadyAdded = [],
  maxSelect = 5,
  options = INDIAN_TICKERS,
  title = "Add tickers",
  description,
  confirmLabel,
  busy = false,
}: TickerMultiSelectProps) {
  const alreadySet = React.useMemo(
    () => new Set(alreadyAdded.map((t) => toDisplayTicker(t))),
    [alreadyAdded],
  );
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (open) {
      setSelected(new Set());
      setQuery("");
    }
  }, [open]);

  const filtered = React.useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.symbol.toUpperCase().includes(q) ||
        o.name.toUpperCase().includes(q),
    );
  }, [options, query]);

  const remaining = Math.max(0, maxSelect - selected.size);
  const atCap = remaining === 0;

  const toggle = (sym: string) => {
    if (alreadySet.has(sym)) return;
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(sym)) {
        next.delete(sym);
      } else if (!atCap) {
        next.add(sym);
      }
      return next;
    });
  };

  const handleConfirm = async () => {
    if (selected.size === 0) return;
    await onConfirm(Array.from(selected));
  };

  const finalDescription =
    description ??
    `Pick up to ${maxSelect} symbols. ${remaining} of ${maxSelect} remaining.`;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      description={finalDescription}
      maxWidthClass="max-w-xl"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="gold"
            size="sm"
            onClick={handleConfirm}
            disabled={selected.size === 0 || busy}
          >
            {busy
              ? "Adding…"
              : (confirmLabel ?? `Add ${selected.size || ""} ticker${selected.size === 1 ? "" : "s"}`)}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="relative flex items-center">
          <Search className="pointer-events-none absolute left-3 h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search tickers"
            spellCheck={false}
            autoCapitalize="characters"
            autoComplete="off"
            className={cn(
              "h-10 w-full rounded-xl border border-input bg-background pl-9 pr-3 font-mono text-sm uppercase tracking-tight outline-none transition-colors",
              "placeholder:text-muted-foreground/50 placeholder:normal-case placeholder:tracking-normal placeholder:font-sans",
              "focus:border-gold focus:ring-1 focus:ring-gold/40",
            )}
          />
        </label>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {filtered.map((opt) => {
            const sym = opt.symbol;
            const isAlready = alreadySet.has(sym);
            const isPicked = selected.has(sym);
            const disabled = isAlready || (!isPicked && atCap);
            return (
              <button
                key={sym}
                type="button"
                onClick={() => toggle(sym)}
                disabled={disabled && !isPicked}
                className={cn(
                  "group relative flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-left transition-all",
                  "border-border bg-card/40",
                  "hover:bg-card hover:border-gold/30",
                  isPicked &&
                    "border-gold/60 bg-gold/10 ring-1 ring-inset ring-gold/40",
                  isAlready &&
                    "cursor-not-allowed opacity-50 hover:border-border hover:bg-card/40",
                  !isPicked &&
                    !isAlready &&
                    atCap &&
                    "cursor-not-allowed opacity-40",
                )}
              >
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-mono text-sm font-medium">{sym}</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    {opt.name}
                  </span>
                </div>
                {isPicked && (
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gold/20 ring-1 ring-inset ring-gold/40">
                    <Check className="h-3 w-3 text-gold" />
                  </span>
                )}
                {isAlready && (
                  <span className="text-[9px] uppercase tracking-[0.16em] text-muted-foreground">
                    added
                  </span>
                )}
              </button>
            );
          })}
          {filtered.length === 0 && (
            <p className="col-span-full py-6 text-center text-xs text-muted-foreground">
              No tickers match &ldquo;{query}&rdquo;.
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
