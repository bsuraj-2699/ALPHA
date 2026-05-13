import Link from "next/link";
import { TrendingUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { INDIAN_TICKERS } from "@/lib/tickers";

export default function AnalyzeIndexPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Analyze"
        title="Pick a ticker"
        description="Run the full multi-agent pipeline. Five analysts, two debaters, one judge — deterministic scoring, narrative-only LLMs."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-gold" />
            Quick picks
          </CardTitle>
          <CardDescription>
            Headline names from the NSE — click to jump straight into analysis.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {INDIAN_TICKERS.map(({ symbol, name }) => (
              <Button
                key={symbol}
                asChild
                variant="secondary"
                size="sm"
                title={name}
                className="rounded-xl border border-transparent font-mono text-xs transition-all hover:border-gold/40 hover:bg-secondary hover:shadow-[0_0_18px_-10px_rgba(201,168,76,0.6)]"
              >
                <Link href={`/analyze/${symbol}?auto=1`}>
                  <span className="text-muted-foreground">NSE</span>
                  <span className="ml-1.5">{symbol}</span>
                </Link>
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
