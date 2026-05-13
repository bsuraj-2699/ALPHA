"use client";

import * as React from "react";
import {
  ColorType,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { usePrice } from "@/lib/queries";
import { formatPrice } from "@/lib/format";
import { toApiTicker } from "@/lib/tickers";
import { cn } from "@/lib/utils";
import type { Market, PriceBar } from "@/types/api";

interface PriceChartProps {
  ticker: string;
  market?: Market;
}

const MA50_LOOKBACK = 50;
const MA200_LOOKBACK = 200;

function simpleMovingAverage(
  bars: ReadonlyArray<PriceBar>,
  period: number,
): LineData<UTCTimestamp>[] {
  if (bars.length < period) return [];
  const out: LineData<UTCTimestamp>[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i]!.close;
    if (i >= period) sum -= bars[i - period]!.close;
    if (i >= period - 1) {
      out.push({
        time: bars[i]!.time as UTCTimestamp,
        value: Number((sum / period).toFixed(2)),
      });
    }
  }
  return out;
}

export function PriceChart({ ticker, market = "IN" }: PriceChartProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const chartRef = React.useRef<IChartApi | null>(null);
  const candleSeriesRef = React.useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ma50SeriesRef = React.useRef<ISeriesApi<"Line"> | null>(null);
  const ma200SeriesRef = React.useRef<ISeriesApi<"Line"> | null>(null);

  // Backend expects the suffixed form for IN tickers.
  const apiTicker = React.useMemo(
    () => toApiTicker(ticker, market),
    [ticker, market],
  );

  const priceQuery = usePrice(apiTicker, {
    market,
    interval: "1d",
    lookbackDays: 220,
  });
  const data = priceQuery.data;
  const bars = data?.bars ?? [];
  const currency = data?.currency ?? (market === "IN" ? "INR" : "USD");
  const isLoading = priceQuery.isLoading && !data;
  const isError = priceQuery.isError;
  const isStale = data?.stale === true;
  const source = data?.source ?? null;

  // Mount the chart once.
  React.useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8a93a3",
        fontFamily:
          "var(--font-plex-mono), ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(231, 233, 238, 0.04)" },
        horzLines: { color: "rgba(231, 233, 238, 0.06)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
        vertLine: { color: "#c9a84c", labelBackgroundColor: "#c9a84c" },
        horzLine: { color: "#c9a84c", labelBackgroundColor: "#c9a84c" },
      },
      handleScroll: false,
      handleScale: false,
    });

    const candle = chart.addCandlestickSeries({
      upColor: "#00e5a0",
      downColor: "#ff4d6d",
      borderUpColor: "#00e5a0",
      borderDownColor: "#ff4d6d",
      wickUpColor: "rgba(0, 229, 160, 0.7)",
      wickDownColor: "rgba(255, 77, 109, 0.7)",
    });

    const ma50 = chart.addLineSeries({
      color: "#c9a84c",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const ma200 = chart.addLineSeries({
      color: "rgba(231, 233, 238, 0.45)",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candle;
    ma50SeriesRef.current = ma50;
    ma200SeriesRef.current = ma200;

    return () => {
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ma50SeriesRef.current = null;
      ma200SeriesRef.current = null;
    };
  }, []);

  // Push data whenever the response changes.
  React.useEffect(() => {
    const candle = candleSeriesRef.current;
    const ma50 = ma50SeriesRef.current;
    const ma200 = ma200SeriesRef.current;
    const chart = chartRef.current;
    if (!candle || !ma50 || !ma200 || !chart) return;

    if (bars.length === 0) {
      candle.setData([]);
      ma50.setData([]);
      ma200.setData([]);
      return;
    }

    const candleData: CandlestickData<UTCTimestamp>[] = bars.map((b) => ({
      time: b.time as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));

    candle.setData(candleData);
    ma50.setData(simpleMovingAverage(bars, MA50_LOOKBACK));
    ma200.setData(simpleMovingAverage(bars, MA200_LOOKBACK));

    chart.timeScale().fitContent();
  }, [bars]);

  // Header price + change.
  const headerPrice =
    data?.quote?.price ??
    (bars.length > 0 ? bars[bars.length - 1]!.close : null);
  const headerChange =
    data?.quote?.change_pct ??
    (bars.length >= 2
      ? ((bars[bars.length - 1]!.close - bars[bars.length - 2]!.close) /
          bars[bars.length - 2]!.close) *
        100
      : null);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 p-4 pb-2">
        <div className="flex flex-col gap-0.5">
          <CardTitle className="text-sm font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Price
          </CardTitle>
          {isLoading ? (
            <Skeleton className="h-7 w-32" />
          ) : headerPrice !== null ? (
            <p className="font-mono text-xl font-medium">
              {formatPrice(headerPrice, market)}
              {headerChange !== null && (
                <span
                  className={cn(
                    "ml-2 text-xs",
                    headerChange >= 0 ? "text-buy" : "text-sell",
                  )}
                >
                  {headerChange >= 0 ? "+" : ""}
                  {headerChange.toFixed(2)}%
                </span>
              )}
            </p>
          ) : (
            <p className="font-mono text-xl font-medium text-muted-foreground">
              —
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex items-center gap-1.5 text-[10px]">
            <Badge variant="gold" className="font-mono normal-case tracking-normal">
              MA50
            </Badge>
            <Badge variant="muted" className="font-mono normal-case tracking-normal">
              MA200
            </Badge>
          </div>
          {isStale && (
            <Badge variant="warn" className="font-mono normal-case tracking-normal">
              estimate
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-2">
        <div className="relative h-[220px] w-full">
          <div ref={containerRef} className="h-full w-full" />
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <Skeleton className="h-full w-full rounded-md" />
            </div>
          )}
          {isError && !isLoading && bars.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-center">
              <p className="text-xs text-sell">Price feed unavailable</p>
              <p className="text-[10px] text-muted-foreground">
                {priceQuery.error?.message ?? "Try again in a moment."}
              </p>
            </div>
          )}
        </div>
        <p className="mt-2 px-2 text-[10px] text-muted-foreground">
          {bars.length > 0
            ? `${bars.length}-day OHLC · ${currency}${source ? ` · ${source}` : ""}${isStale ? " · placeholder" : ""}`
            : isLoading
              ? "Fetching live OHLC…"
              : "No data"}
        </p>
      </CardContent>
    </Card>
  );
}
