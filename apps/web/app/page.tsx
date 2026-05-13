import { ArrowRight, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { StrategyButtons } from "@/components/strategy-buttons";
import { INDIAN_TICKER_SYMBOLS } from "@/lib/tickers";

const QUICK_ANALYZE_LIMIT = 8;

export default function DashboardPage() {
  const quickPicks = INDIAN_TICKER_SYMBOLS.slice(0, QUICK_ANALYZE_LIMIT);

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Dashboard"
        title={
          <>
            Welcome, Trader.{" "}
            <span className="italic text-gold">Markets await.</span>
          </>
        }
        description="Your AI edge in Indian markets."
        actions={
          <Button asChild variant="gold" size="lg" className="rounded-xl">
            <Link href="/analyze/RELIANCE?auto=1">
              <Sparkles className="mr-1 h-4 w-4" />
              New analysis
            </Link>
          </Button>
        }
      />

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Strategies
          </h2>
          <span className="text-[11px] text-muted-foreground">
            Auto-refreshes every 5 min
          </span>
        </div>
        <StrategyButtons />
      </section>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="flex flex-col gap-1">
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-gold" />
              Quick analyze
            </CardTitle>
            <CardDescription>
              Jump straight into an analysis without leaving the dashboard.
            </CardDescription>
          </div>
          <Button asChild variant="outline" size="sm" className="rounded-xl">
            <Link href="/analyze" className="gap-1">
              Open analyzer <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2 pt-2">
            {quickPicks.map((sym) => (
              <Button
                key={sym}
                asChild
                variant="secondary"
                size="sm"
                className="rounded-xl border border-transparent font-mono text-xs transition-all hover:border-gold/40 hover:bg-secondary hover:shadow-[0_0_18px_-10px_rgba(201,168,76,0.6)]"
              >
                <Link href={`/analyze/${sym}?auto=1`}>{sym}</Link>
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
