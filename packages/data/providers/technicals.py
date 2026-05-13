"""Compute the trend / momentum fields RuleEvaluator expects from an OHLC frame.

Pure-Python (uses pandas because yfinance/dhan return DataFrames anyway). All
functions are sync — wrap in asyncio.to_thread when called from async code.

Emits both ``rsi_14`` (14-period) and ``rsi_3`` (3-period). For live
``intraday`` runs only, :mod:`packages.data.context_builder` overwrites
``rsi_14`` with ``rsi_3`` before rule evaluation so ``rules.json`` stays on
``rsi_14`` while momentum uses the fast oscillator.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Given a daily OHLC DataFrame with columns Open/High/Low/Close/Volume,
    return the technical-analysis subset of the RuleEvaluator context."""
    if df is None or df.empty or len(df) < 30:
        return {}

    df = df.sort_index()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    out: dict[str, Any] = {}
    last = close.iloc[-1]
    out["current_price"] = float(last)

    # 52-week range
    window = close.tail(252) if len(close) >= 252 else close
    out["high_52w"] = float(window.max())
    out["low_52w"] = float(window.min())

    # Moving averages — only emit if we have enough history
    if len(close) >= 200:
        ma_50 = close.rolling(50).mean()
        ma_200 = close.rolling(200).mean()
        out["ma_50"] = float(ma_50.iloc[-1])
        out["ma_200"] = float(ma_200.iloc[-1])
        if len(close) >= 205:
            out["ma_50_prev_5d"] = float(ma_50.iloc[-6])
            out["ma_200_prev_5d"] = float(ma_200.iloc[-6])

    # EMA ribbon
    if len(close) >= 55:
        emas = {n: close.ewm(span=n, adjust=False).mean() for n in (8, 13, 21, 34, 55)}
        for n, series in emas.items():
            out[f"ema_{n}"] = float(series.iloc[-1])
        # ribbon compression: spread between fastest and slowest as % of price
        latest = [emas[n].iloc[-1] for n in (8, 13, 21, 34, 55)]
        spread = max(latest) - min(latest)
        out["ribbon_compression_pct"] = float(spread / last * 100) if last else 0.0

    # RSI 14 (canonical for short_term / long_term and for intraday display
    # of the slower oscillator unless ContextBuilder overwrites rsi_14).
    if len(close) >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - 100 / (1 + rs)
        out["rsi_14"] = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0
        # bearish/bullish divergence detection requires multi-peak analysis;
        # leave absent so the rule's neutral fallback applies.
        out["rsi_divergence_bearish"] = False
        out["rsi_divergence_bullish"] = False

    # RSI 3 — fast oscillator; ContextBuilder maps it onto rsi_14 for intraday
    # only so rules.json keeps a single rsi_14 surface.
    if len(close) >= 4:
        delta3 = close.diff()
        g3 = delta3.clip(lower=0).rolling(3).mean()
        l3 = (-delta3.clip(upper=0)).rolling(3).mean()
        rs3 = g3 / l3.replace(0, pd.NA)
        rsi3 = 100 - 100 / (1 + rs3)
        out["rsi_3"] = float(rsi3.iloc[-1]) if pd.notna(rsi3.iloc[-1]) else 50.0

    # MACD 12/26/9
    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        out["macd_line"] = float(macd.iloc[-1])
        out["macd_signal"] = float(signal.iloc[-1])
        out["macd_histogram"] = float(hist.iloc[-1])
        if len(hist) >= 2:
            out["macd_histogram_prev"] = float(hist.iloc[-2])

    # Stochastic 14/3/3
    if len(close) >= 17:
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        denom = (high14 - low14).replace(0, pd.NA)
        k_raw = (close - low14) / denom * 100
        k = k_raw.rolling(3).mean()
        d = k.rolling(3).mean()
        if pd.notna(k.iloc[-1]) and pd.notna(d.iloc[-1]):
            out["stoch_k"] = float(k.iloc[-1])
            out["stoch_d"] = float(d.iloc[-1])
            if len(k) >= 2 and pd.notna(k.iloc[-2]) and pd.notna(d.iloc[-2]):
                out["stoch_k_prev"] = float(k.iloc[-2])
                out["stoch_d_prev"] = float(d.iloc[-2])

    # Bollinger Bands 20, 2σ
    if len(close) >= 20:
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std(ddof=0)
        out["bb_middle"] = float(sma20.iloc[-1])
        out["bb_upper"] = float(sma20.iloc[-1] + 2 * std20.iloc[-1])
        out["bb_lower"] = float(sma20.iloc[-1] - 2 * std20.iloc[-1])
        # squeeze: bandwidth in lowest decile of last 6 months
        bandwidth = (sma20 + 2 * std20 - (sma20 - 2 * std20)) / sma20
        recent_bw = bandwidth.tail(120).dropna()
        if not recent_bw.empty:
            cutoff = recent_bw.quantile(0.1)
            out["bb_squeeze"] = bool(bandwidth.iloc[-1] <= cutoff)

    # Volume confirmation
    if len(volume) >= 20:
        vol_today = float(volume.iloc[-1])
        vol_avg_20d = float(volume.tail(20).mean())
        out["volume_today"] = vol_today
        out["volume_avg_20d"] = vol_avg_20d
        if len(close) >= 2:
            prev = float(close.iloc[-2])
            out["price_change_today_pct"] = (last - prev) / prev * 100 if prev else 0.0
        # is_breakout: today closes above prior 20d high
        prior_high = float(high.iloc[-21:-1].max()) if len(high) >= 21 else float(high.max())
        out["is_breakout"] = bool(last > prior_high)

    # Support/resistance — pivot-based, last 60 days
    if len(close) >= 60:
        window60_low = float(low.tail(60).min())
        window60_high = float(high.tail(60).max())
        out["nearest_support"] = window60_low
        out["nearest_resistance"] = window60_high
        # bounce / breakdown today: did price touch support and recover, or close
        # below it on heavy volume?
        today_low = float(low.iloc[-1])
        today_close = float(close.iloc[-1])
        out["bounced_off_support_today"] = bool(
            today_low <= window60_low * 1.01 and today_close > window60_low * 1.01
        )
        out["broke_support_today"] = bool(today_close < window60_low)

    return out
