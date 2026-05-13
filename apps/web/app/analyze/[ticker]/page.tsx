import { AnalyzeView } from "@/components/analyze/analyze-view";
import { toDisplayTicker } from "@/lib/tickers";
import type { Market } from "@/types/api";

interface PageProps {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ auto?: string }>;
}

export default async function AnalyzePage({ params, searchParams }: PageProps) {
  const { ticker } = await params;
  const { auto } = await searchParams;
  // Always normalize to display form (no `.NS`) — the AnalyzeView
  // re-suffixes when calling the API.
  const symbol = toDisplayTicker(decodeURIComponent(ticker));
  const market: Market = "IN";
  const autoStart = auto === "1" || auto === "true";

  return (
    <AnalyzeView
      initialTicker={symbol}
      initialMarket={market}
      autoStart={autoStart}
    />
  );
}
