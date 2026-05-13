import * as React from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 border-b border-border pb-6",
        className,
      )}
    >
      <div className="flex items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          {eyebrow && (
            <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              {eyebrow}
            </span>
          )}
          <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
            {title}
          </h1>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {description && (
        <p className="max-w-3xl text-sm text-muted-foreground">{description}</p>
      )}
    </div>
  );
}
