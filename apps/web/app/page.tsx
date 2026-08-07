import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { DashboardHero } from "@/components/dashboard/hero";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";
import { StrategyButtons } from "@/components/strategy-buttons";

/** Small section heading with an optional right-hand affordance. */
function SectionHeading({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <div className="flex items-baseline gap-3">
        <h2 className="font-display text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          {title}
        </h2>
        {hint ? (
          <span className="text-[11px] text-muted-foreground/70">{hint}</span>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-12 pb-4">
      <DashboardHero />

      <section className="flex flex-col gap-4">
        <SectionHeading title="Strategies" hint="Auto-refreshed per bucket" />
        <StrategyButtons />
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Quick analyze"
          hint="Starts on arrival"
          action={
            <Link
              href="/analyze"
              className="group inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Open analyzer
              <ArrowRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
            </Link>
          }
        />
        <QuickAnalyze />
      </section>
    </div>
  );
}
