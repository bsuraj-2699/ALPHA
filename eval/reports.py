"""HTML report generator for backtest results.

The output is a single self-contained ``.html`` file:

  * inline CSS only - opens in any browser, no network deps
  * SVG-rendered equity curve (strategy + 2 benchmarks) - no JS, no
    external chart libraries
  * decision log + trades tables, scrollable
  * summary cards with the headline metrics

The visual language matches the web app: same dark surface, gold/buy/
sell accents, IBM Plex / Playfair fonts where available (falls back to
system stack).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from eval.benchmarks import BenchmarkResult
from eval.metrics import PerformanceSummary, summarise
from eval.portfolio import DecisionLog, EquityPoint, Trade
from eval.runner import BacktestResult


# ---------------------------------------------------------------------------
# Tiny SVG helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Series:
    name: str
    color: str
    points: list[EquityPoint]


def _equity_curve_svg(
    series: list[_Series],
    width: int = 900,
    height: int = 360,
    pad: int = 36,
) -> str:
    """Render up to N equity-curve series on a single SVG.

    All series are normalised to start at 100 so visual comparison is
    fair regardless of starting capital differences.
    """
    if not series:
        return f'<svg viewBox="0 0 {width} {height}" class="chart"></svg>'

    # Normalise each series to start = 100
    norm: list[tuple[_Series, list[tuple[date, float]]]] = []
    for s in series:
        if not s.points:
            continue
        base = s.points[0].total
        if base <= 0:
            continue
        pts = [(p.date, 100.0 * p.total / base) for p in s.points]
        norm.append((s, pts))

    if not norm:
        return f'<svg viewBox="0 0 {width} {height}" class="chart"></svg>'

    all_dates = sorted({d for _, pts in norm for d, _ in pts})
    all_values = [v for _, pts in norm for _, v in pts]
    if not all_dates or not all_values:
        return f'<svg viewBox="0 0 {width} {height}" class="chart"></svg>'

    d_min, d_max = all_dates[0], all_dates[-1]
    v_min, v_max = min(all_values), max(all_values)
    # Padded value range so the lines don't kiss the frame
    span = max(v_max - v_min, 1.0)
    v_min_pad = v_min - span * 0.05
    v_max_pad = v_max + span * 0.05

    def _x(d: date) -> float:
        if d_max == d_min:
            return pad
        ord_total = (d_max - d_min).days
        ord_cur = (d - d_min).days
        return pad + (width - 2 * pad) * (ord_cur / ord_total)

    def _y(v: float) -> float:
        if v_max_pad == v_min_pad:
            return height / 2
        return (
            height
            - pad
            - (height - 2 * pad) * ((v - v_min_pad) / (v_max_pad - v_min_pad))
        )

    # Build axis lines + 4 horizontal gridlines
    grid_lines = []
    for i in range(5):
        v = v_min_pad + (v_max_pad - v_min_pad) * (i / 4)
        y = _y(v)
        grid_lines.append(
            f'<line x1="{pad}" y1="{y:.1f}" x2="{width - pad}" y2="{y:.1f}" '
            f'stroke="rgba(231,233,238,0.05)" stroke-width="1"/>'
            f'<text x="{pad - 6:.1f}" y="{y + 3:.1f}" text-anchor="end" '
            f'font-size="10" fill="rgba(231,233,238,0.5)">{v:.1f}</text>'
        )
    # Date markers at start / mid / end
    date_markers = []
    for d in (d_min, all_dates[len(all_dates) // 2], d_max):
        x = _x(d)
        date_markers.append(
            f'<text x="{x:.1f}" y="{height - 8:.1f}" text-anchor="middle" '
            f'font-size="10" fill="rgba(231,233,238,0.5)">{d.isoformat()}</text>'
        )

    # Lines per series
    series_paths = []
    legend_items = []
    for s, pts in norm:
        if len(pts) < 2:
            continue
        d_attr = "M " + " L ".join(f"{_x(d):.1f},{_y(v):.1f}" for d, v in pts)
        series_paths.append(
            f'<path d="{d_attr}" fill="none" stroke="{s.color}" '
            f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{s.color}"></span>'
            f"{html.escape(s.name)}</span>"
        )

    legend = f'<div class="legend">{"".join(legend_items)}</div>'
    svg = (
        f'<svg viewBox="0 0 {width} {height}" class="chart" '
        'xmlns="http://www.w3.org/2000/svg">'
        + "".join(grid_lines)
        + "".join(series_paths)
        + "".join(date_markers)
        + "</svg>"
    )
    return svg + legend


# ---------------------------------------------------------------------------
# Summary card rendering
# ---------------------------------------------------------------------------


def _fmt_pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v * 100:.2f}%"


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def _fmt_num(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}"


def _summary_card(label: str, value: str, tone: str = "muted") -> str:
    return (
        f'<div class="card"><span class="card-label">{html.escape(label)}</span>'
        f'<span class="card-value tone-{tone}">{html.escape(value)}</span></div>'
    )


def _render_summary(summary: PerformanceSummary) -> str:
    tr_tone = "buy" if summary.total_return > 0 else "sell"
    cards = [
        _summary_card("Starting", _fmt_money(summary.starting_capital)),
        _summary_card("Ending", _fmt_money(summary.ending_value), tone=tr_tone),
        _summary_card("Total return", _fmt_pct(summary.total_return), tone=tr_tone),
        _summary_card("CAGR", _fmt_pct(summary.cagr)),
        _summary_card("Sharpe", _fmt_num(summary.sharpe)),
        _summary_card("Sortino", _fmt_num(summary.sortino)),
        _summary_card("Max drawdown", _fmt_pct(-summary.max_drawdown), tone="sell"),
        _summary_card("Trades", str(summary.trades.n_trades)),
        _summary_card(
            "Hit rate", f"{summary.trades.hit_rate * 100:.1f}%", tone="gold"
        ),
        _summary_card(
            "Avg hold",
            f"{summary.trades.avg_holding_days:.1f}d",
        ),
    ]
    return '<div class="cards">' + "".join(cards) + "</div>"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _render_trades(trades: Iterable[Trade]) -> str:
    rows = []
    for t in trades:
        tone = "buy" if t.pnl > 0 else "sell" if t.pnl < 0 else "muted"
        ovr = ", ".join(t.overrides_active) if t.overrides_active else "—"
        rows.append(
            "<tr>"
            f"<td class='mono'>{html.escape(t.ticker)}</td>"
            f"<td class='mono'>{t.entry_date.isoformat()}</td>"
            f"<td class='mono'>{t.exit_date.isoformat()}</td>"
            f"<td class='mono num'>${t.entry_price:.2f}</td>"
            f"<td class='mono num'>${t.exit_price:.2f}</td>"
            f"<td class='mono num tone-{tone}'>{_fmt_pct(t.pnl_pct)}</td>"
            f"<td class='mono num tone-{tone}'>{_fmt_money(t.pnl)}</td>"
            f"<td class='mono'>{t.holding_days}d</td>"
            f"<td>{html.escape(t.exit_reason)}</td>"
            f"<td>{html.escape(t.decision_signal)}</td>"
            f"<td class='mono'>{html.escape(ovr)}</td>"
            "</tr>"
        )
    if not rows:
        rows = ["<tr><td colspan='11' class='empty'>No trades.</td></tr>"]
    return (
        "<table class='data'>"
        "<thead><tr>"
        "<th>Ticker</th><th>Entry</th><th>Exit</th>"
        "<th>Entry $</th><th>Exit $</th>"
        "<th>P&L %</th><th>P&L</th>"
        "<th>Hold</th><th>Why</th><th>Signal</th><th>Overrides</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_decision_log(log: Iterable[DecisionLog]) -> str:
    rows = []
    for d in log:
        ovr = ", ".join(d.overrides_active) if d.overrides_active else "—"
        tone = (
            "buy"
            if d.signal in ("BUY", "STRONG_BUY")
            else "sell"
            if d.signal in ("SELL", "STRONG_SELL")
            else "muted"
        )
        rows.append(
            "<tr>"
            f"<td class='mono'>{d.date.isoformat()}</td>"
            f"<td class='mono'>{html.escape(d.ticker)}</td>"
            f"<td class='mono tone-{tone}'>{html.escape(d.signal)}</td>"
            f"<td class='mono num'>{d.confidence:.1f}</td>"
            f"<td class='mono num'>{d.position_size_pct:.1f}%</td>"
            f"<td class='mono num'>{f'${d.entry_price:.2f}' if d.entry_price else '—'}</td>"
            f"<td class='mono num'>{f'${d.stop_loss:.2f}' if d.stop_loss else '—'}</td>"
            f"<td class='mono num'>{f'${d.target_price:.2f}' if d.target_price else '—'}</td>"
            f"<td>{html.escape(d.action_taken)}</td>"
            f"<td class='mono'>{html.escape(ovr)}</td>"
            "</tr>"
        )
    if not rows:
        rows = ["<tr><td colspan='10' class='empty'>No decisions emitted.</td></tr>"]
    return (
        "<table class='data'>"
        "<thead><tr>"
        "<th>Date</th><th>Ticker</th><th>Signal</th><th>Conf</th>"
        "<th>Size</th><th>Entry</th><th>Stop</th><th>Target</th>"
        "<th>Action</th><th>Overrides</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Top-level renderer
# ---------------------------------------------------------------------------


def render_html(result: BacktestResult, *, title: str | None = None) -> str:
    spec_label = ", ".join(
        f"{s.ticker} ({s.market}) {s.start_date}→{s.end_date}" for s in result.specs
    )
    title = title or f"Backtest · {spec_label}"

    summary = result.summary or summarise(result.equity_curve, result.trades)

    series: list[_Series] = []
    if result.equity_curve:
        series.append(
            _Series(name="Strategy (agent)", color="#c9a84c", points=result.equity_curve)
        )
    if result.benchmark_basket and result.benchmark_basket.equity_curve:
        series.append(
            _Series(
                name=f"Buy & Hold (basket)",
                color="#00e5a0",
                points=result.benchmark_basket.equity_curve,
            )
        )
    if result.benchmark_index and result.benchmark_index.equity_curve:
        series.append(
            _Series(
                name=f"Buy & Hold ({result.benchmark_index.name})",
                color="#8a93a3",
                points=result.benchmark_index.equity_curve,
            )
        )

    chart_html = _equity_curve_svg(series)

    # Bench summary table (apples-to-apples comparison)
    bench_rows = []
    bench_rows.append(_bench_row("Strategy (agent)", summary))
    if result.benchmark_basket and result.benchmark_basket.equity_curve:
        bench_rows.append(
            _bench_row(
                "Buy & Hold (basket)",
                summarise(result.benchmark_basket.equity_curve, []),
            )
        )
    if result.benchmark_index and result.benchmark_index.equity_curve:
        bench_rows.append(
            _bench_row(
                f"Buy & Hold ({result.benchmark_index.name})",
                summarise(result.benchmark_index.equity_curve, []),
            )
        )
    bench_table = (
        "<table class='data'>"
        "<thead><tr><th>Strategy</th><th>Total return</th><th>CAGR</th>"
        "<th>Sharpe</th><th>Max DD</th><th>Ending</th></tr></thead><tbody>"
        + "".join(bench_rows)
        + "</tbody></table>"
    )

    # CSS — kept inline so the file is portable
    css = _CSS

    body = f"""
<header class="hero">
  <span class="eyebrow">fin-agent · backtest</span>
  <h1>{html.escape(title)}</h1>
  <p class="meta">
    {len(result.specs)} ticker(s) · {result.decisions_emitted} decision(s) emitted ·
    {result.decisions_skipped} skipped · cadence every {result.config.decision_cadence_days} trading day(s)
  </p>
</header>

<section>
  <h2>Performance</h2>
  {_render_summary(summary)}
</section>

<section>
  <h2>Equity curve <span class="muted">(normalised to 100)</span></h2>
  {chart_html}
</section>

<section>
  <h2>Strategy vs benchmarks</h2>
  {bench_table}
</section>

<section>
  <h2>Trades <span class="muted">({summary.trades.n_trades})</span></h2>
  {_render_trades(result.trades)}
</section>

<section>
  <h2>Decision log <span class="muted">({len(result.decision_log)})</span></h2>
  {_render_decision_log(result.decision_log)}
</section>

<footer>
  Generated by <code>eval/reports.py</code> · self-contained HTML, opens anywhere.
</footer>
"""

    return f"""<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8"/>
  <title>{html.escape(title)}</title>
  <style>{css}</style>
</head><body>
<main>{body}</main>
</body></html>"""


def _bench_row(name: str, summary: PerformanceSummary) -> str:
    tr_tone = "buy" if summary.total_return > 0 else "sell"
    return (
        "<tr>"
        f"<td>{html.escape(name)}</td>"
        f"<td class='mono num tone-{tr_tone}'>{_fmt_pct(summary.total_return)}</td>"
        f"<td class='mono num'>{_fmt_pct(summary.cagr)}</td>"
        f"<td class='mono num'>{_fmt_num(summary.sharpe)}</td>"
        f"<td class='mono num tone-sell'>{_fmt_pct(-summary.max_drawdown)}</td>"
        f"<td class='mono num'>{_fmt_money(summary.ending_value)}</td>"
        "</tr>"
    )


def write_report(result: BacktestResult, path: Path, *, title: str | None = None) -> Path:
    """Render and write the report to ``path``. Returns the absolute path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(result, title=title), encoding="utf-8")
    return path.resolve()


# ---------------------------------------------------------------------------
# CSS (inline)
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
:root {
  --bg: #0a0c0f;
  --fg: #e7e9ee;
  --muted: #8a93a3;
  --card: #11141a;
  --border: rgba(231,233,238,0.08);
  --buy: #00e5a0;
  --sell: #ff4d6d;
  --warn: #f5a623;
  --gold: #c9a84c;
  --mono: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  --sans: -apple-system, "Segoe UI", "IBM Plex Sans", system-ui, sans-serif;
  --display: "Playfair Display", Georgia, serif;
}
html, body { background: var(--bg); color: var(--fg); margin: 0; padding: 0; font-family: var(--sans); }
main { max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }
header.hero { border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 32px; }
.eyebrow { display: block; font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
h1 { font-family: var(--display); font-size: 32px; margin: 0 0 6px; }
h2 { font-family: var(--display); font-size: 20px; margin: 0 0 12px; font-weight: 600; }
.meta, .muted { color: var(--muted); }
.muted { font-weight: 400; font-size: 0.9em; }
section { margin-bottom: 36px; }

.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }
.card-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.16em; color: var(--muted); }
.card-value { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 20px; font-weight: 600; }

.tone-buy { color: var(--buy); }
.tone-sell { color: var(--sell); }
.tone-warn { color: var(--warn); }
.tone-gold { color: var(--gold); }
.tone-muted { color: var(--muted); }

.chart { width: 100%; max-height: 360px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.legend { display: flex; gap: 16px; padding: 8px 12px; color: var(--muted); font-size: 12px; flex-wrap: wrap; }
.legend-item { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }

table.data { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
table.data thead th { background: rgba(231,233,238,0.04); text-align: left; padding: 10px 12px; font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); }
table.data tbody td { padding: 9px 12px; border-top: 1px solid var(--border); vertical-align: middle; }
table.data tbody tr:hover { background: rgba(231,233,238,0.025); }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.num { text-align: right; }
.empty { text-align: center; color: var(--muted); padding: 24px !important; }

footer { color: var(--muted); font-size: 12px; padding-top: 32px; border-top: 1px solid var(--border); }
code { font-family: var(--mono); background: rgba(231,233,238,0.05); padding: 1px 4px; border-radius: 3px; }
"""


__all__ = ["render_html", "write_report"]
