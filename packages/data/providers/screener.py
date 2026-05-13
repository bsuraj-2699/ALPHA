"""Screener.in adapter for Indian fundamentals.

Scrapes the consolidated company page (``/company/<symbol>/consolidated/``)
and derives every rule-engine field either directly from confirmed raw-HTML
labels or via financial formula.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RAW HTML SECTIONS (confirmed present, no JS required)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ul#top-ratios       Market Cap, Current Price, Stock P/E, Book Value,
                      Dividend Yield, ROCE, ROE, Debt to equity, Face Value
  section#profit-loss Sales, Net Profit, Operating Profit, Interest,
                      Depreciation, EPS in Rs, Dividend Payout %, OPM %
                      (annual columns + TTM column)
  section#quarters    Sales, Net Profit, EPS in Rs, Operating Profit
                      (quarterly, newest column = leftmost after label)
  section#balance-sheet
                      Share Capital, Reserves, Borrowings, Other Liabilities,
                      Total Liabilities, Fixed Assets, CWIP, Investments,
                      Cash Equivalents, Trade Receivables, Inventories,
                      Loans n Advances, Other Assets, Total Assets
  section#cash-flow   Cash from Operating Activity,
                      Cash from Investing Activity,
                      Cash from Financing Activity, Free Cash Flow
  section#ratios      Debtor Days, Inventory Days, Days Payable,
                      Cash Conversion Cycle, Working Capital Days, ROCE %

NOT DIRECTLY PRESENT → computed via formula:
  current_ratio       (Cash+Receivables+Inventory+Advances+Other) /
                      (TotalLiabilities - Equity - LT-Borrowings)
  quick_ratio         (Cash + Receivables) / Current Liabilities
  roa_pct             Net Profit TTM / Total Assets × 100
  pb_ratio            Current Price / Book Value  (both in top-ratios)
  interest_coverage   Operating Profit TTM / Interest TTM
  peg_ratio           Stock P/E / eps_yoy_pct
  ev_ebitda           (Market Cap + Borrowings - Cash) /
                      (Operating Profit + Depreciation)
  forward_pe          Current Price / (EPS_TTM × (1 + eps_yoy/100))
  debt_to_equity_yoy_change  Δ(Borrowings/Equity) year-on-year

NOT COMPUTABLE from Screener (peer/JS data) → left absent:
  sector_pe_avg, pe_5y_avg, industry_ev_ebitda_median,
  industry_avg_margin, company_age_years
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from packages.data.providers.cache import RedisCache

logger = logging.getLogger(__name__)

_BASE = "https://www.screener.in"
_TIMEOUT = 20.0
_TTL = 60 * 60

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# Maps anchor label (lowercase) → Screener HTML section id.
_LABEL_TO_SECTION_ID: dict[str, str] = {
    "profit & loss":        "profit-loss",
    "profit and loss":      "profit-loss",
    "quarterly results":    "quarters",
    "quarters":             "quarters",
    "balance sheet":        "balance-sheet",
    "cash flows":           "cash-flow",
    "cash flow":            "cash-flow",
    "ratios":               "ratios",
    "shareholding pattern": "shareholding",
}


# ─────────────────────────────────────────────────────────────────────────────
# HTML parsing primitives
# ─────────────────────────────────────────────────────────────────────────────

def _clean_text(x: Any) -> str:
    if x is None:
        return ""
    return " ".join(
        str(x)
        .replace("\n", " ").replace("\t", " ")
        .replace("+", "").replace("-", "")
        .split()
    ).strip()


def _parse_number(s: Any) -> float | None:
    if s is None:
        return None
    cleaned = (
        str(s)
        .replace(",", "").replace("₹", "").replace("%", "")
        .replace("\xa0", "").strip()
    )
    if cleaned in ("", "-", "—", "–", "N/A"):
        return None
    cleaned = re.sub(r"\s*(Cr|Lac|Lakh)\s*$", "", cleaned, flags=re.I).strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_ratios_block(soup: Any) -> dict[str, float | None]:
    """Parse ``<ul id="top-ratios">`` → {label: float|None}."""
    out: dict[str, float | None] = {}
    ul = soup.find("ul", {"id": "top-ratios"})
    if not ul:
        return out
    for li in ul.find_all("li"):
        name_el = li.find("span", class_="name")
        val_el  = li.find("span", class_="number")
        if not (name_el and val_el):
            continue
        key = _clean_text(name_el.text)
        out[key] = _parse_number(val_el.text)
    return out


def _table_to_rows(table: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def _parse_section_table(soup: Any, anchor_labels: list[str]) -> list[list[str]]:
    """Find a table by section-id (primary) then heading-text (fallback)."""
    for label in anchor_labels:
        sec_id = _LABEL_TO_SECTION_ID.get(label.lower())
        if sec_id:
            section = soup.find("section", {"id": sec_id})
            if section:
                table = section.find("table")
                if table:
                    return _table_to_rows(table)
    for header in soup.find_all(["h2", "h3"]):
        title = header.get_text(strip=True)
        if any(lbl.lower() in title.lower() for lbl in anchor_labels):
            table = header.find_next("table")
            if table:
                return _table_to_rows(table)
    return []


def _ttm_col(table: list[list[str]]) -> int | None:
    """Return the 1-based column index of the TTM column, or None."""
    if not table:
        return None
    hdr = [_clean_text(c).upper() for c in table[0]]
    return hdr.index("TTM") if "TTM" in hdr else None


def _row_series(table: list[list[str]], names: list[str]) -> list[float]:
    """All numeric values from the first matching row, newest-first.

    Excludes the TTM column so each value = one full fiscal year.
    """
    target  = [n.lower() for n in names]
    ttm_idx = _ttm_col(table)
    for row in table:
        if not row:
            continue
        if any(n in _clean_text(row[0]).lower() for n in target):
            vals: list[float] = []
            for i, cell in enumerate(row[1:], start=1):
                if ttm_idx is not None and i == ttm_idx:
                    continue
                v = _parse_number(cell)
                if v is not None:
                    vals.append(v)
            return vals
    return []


def _row_ttm(table: list[list[str]], names: list[str]) -> float | None:
    """TTM value of a row, or most-recent annual when no TTM column."""
    target  = [n.lower() for n in names]
    ttm_idx = _ttm_col(table)
    for row in table:
        if not row:
            continue
        if any(n in _clean_text(row[0]).lower() for n in target):
            if ttm_idx is not None and ttm_idx < len(row):
                v = _parse_number(row[ttm_idx])
                if v is not None:
                    return v
            for cell in reversed(row[1:]):
                v = _parse_number(cell)
                if v is not None:
                    return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Arithmetic helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def _consec_negative(series: list[float]) -> int:
    """Count leading negative values (series[0] = most recent)."""
    n = 0
    for v in series:
        if v < 0:
            n += 1
        else:
            break
    return n


def _consec_decline(series: list[float]) -> int:
    """Count consecutive periods where series[i] < series[i+1]."""
    n = 0
    for i in range(len(series) - 1):
        if series[i] < series[i + 1]:
            n += 1
        else:
            break
    return n


def _count_phrases(text: str, phrases: list[str]) -> int:
    return sum(text.count(p) for p in phrases)


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────

class ScreenerProvider:
    """Screener.in fundamentals adapter (IN equities only)."""

    name = "screener"

    def __init__(
        self,
        session_cookie: str | None = None,
        cache: RedisCache | None = None,
    ) -> None:
        self.session_cookie = session_cookie or os.getenv("SCREENER_SESSION_COOKIE")
        self.cache = cache if cache is not None else RedisCache()

    async def _fetch_html(self, symbol: str) -> str | None:
        bare    = symbol.split(".")[0].upper()
        cookies = {"sessionid": self.session_cookie} if self.session_cookie else None
        for url in (
            f"{_BASE}/company/{bare}/consolidated/",
            f"{_BASE}/company/{bare}/",
        ):
            try:
                async with httpx.AsyncClient(
                    timeout=_TIMEOUT, headers=_HEADERS, cookies=cookies
                ) as c:
                    resp = await c.get(url)
            except (httpx.HTTPError, OSError) as e:
                logger.warning("screener fetch %s: %s", url, e)
                continue
            if resp.status_code == 200:
                return resp.text
            if resp.status_code != 404:
                logger.warning("screener %s → %d", url, resp.status_code)
        return None

    async def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        bare      = symbol.split(".")[0].upper()
        cache_key = f"screener:fund3:{bare}"
        cached    = await self.cache.get(cache_key)
        if cached:
            import json as _j
            return _j.loads(cached)

        html = await self._fetch_html(bare)
        if not html:
            return {}

        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise RuntimeError("beautifulsoup4 required for ScreenerProvider") from e

        soup = BeautifulSoup(html, "html.parser")
        out  = self._extract(soup)

        import json as _j
        await self.cache.set(cache_key, _j.dumps(out, default=str), _TTL)
        return out

    # ─────────────────────────────────────────────────────────────────────────
    def _extract(self, soup: Any) -> dict[str, Any]:  # noqa: C901
        out: dict[str, Any] = {}

        # ── 1. Top-ratios ─────────────────────────────────────────────────────
        tr = _parse_ratios_block(soup)

        cmp        = tr.get("Current Price")     # ₹ per share
        mktcap     = tr.get("Market Cap")        # ₹ Cr
        book_val   = tr.get("Book Value")        # ₹ per share
        pe_trail   = tr.get("Stock P/E")
        div_yield  = tr.get("Dividend Yield")    # %
        roe        = tr.get("ROE")               # %
        debt_eq_tr = tr.get("Debt to equity")    # ratio (from top-ratios)

        # Direct assignments
        out["pe_ratio"]           = pe_trail
        out["dividend_yield_pct"] = div_yield
        out["roe_pct"]            = roe
        # Prefer computed D/E from balance sheet (more precise); top-ratios
        # value kept as fallback written later if B/S computation fails.
        _debt_eq_topratios        = debt_eq_tr

        # pb_ratio = Current Price / Book Value per share
        # Both confirmed directly in top-ratios block — no table needed.
        out["pb_ratio"] = _safe_div(cmp, book_val)

        # ── 2. Annual Profit & Loss ───────────────────────────────────────────
        pl = _parse_section_table(soup, ["Profit & Loss", "Profit and Loss"])

        # Revenue  (docx confirmed label: "Sales")
        sales_s   = _row_series(pl, ["Sales", "Revenue", "Net Sales"])
        sales_ttm = _row_ttm(pl,    ["Sales", "Revenue", "Net Sales"])

        # Net Profit
        np_s   = _row_series(pl, ["Net Profit"])
        np_ttm = _row_ttm(pl,    ["Net Profit"])

        # Operating Profit (docx: EBIT = "Operating Profit")
        op_ttm  = _row_ttm(pl, ["Operating Profit", "Financing Profit"])

        # Interest Expense (docx: Interest Expense = "Interest")
        int_ttm = _row_ttm(pl, ["Interest"])

        # Depreciation (needed for EBITDA)
        dep_ttm = _row_ttm(pl, ["Depreciation"])

        # EPS  (docx confirmed label: "EPS in Rs")
        eps_s   = _row_series(pl, ["EPS in Rs", "EPS"])
        eps_ttm = _row_ttm(pl,    ["EPS in Rs", "EPS"])

        # Payout / OPM
        out["payout_ratio_pct"]     = _row_ttm(pl, ["Dividend Payout %", "Dividend Payout"])
        out["operating_margin_pct"] = _row_ttm(pl, ["OPM %", "Operating Profit Margin"])

        # Revenue YoY %  — fix: key was previously stored as revenue_growth_pct_yoy
        if len(sales_s) >= 2:
            out["revenue_yoy_pct"] = _pct_change(sales_s[0], sales_s[1])

        # EPS YoY %  — fix: key was previously stored as eps_growth_pct_yoy
        if len(eps_s) >= 2:
            out["eps_yoy_pct"] = _pct_change(eps_s[0], eps_s[1])

        # Earnings declining: latest EPS < EPS 2 full years back
        if len(eps_s) >= 3:
            out["earnings_declining"] = bool(eps_s[0] < eps_s[2])
        elif len(eps_s) >= 2:
            out["earnings_declining"] = bool(eps_s[0] < eps_s[1])

        # Net margin current (TTM)
        nm_current = _safe_div(np_ttm, sales_ttm)
        if nm_current is not None:
            out["net_margin_current"] = nm_current * 100.0

        # Interest coverage = Operating Profit / Interest
        # Formula: EBIT / Interest Expense
        if op_ttm is not None and int_ttm is not None and int_ttm > 0:
            out["interest_coverage_ratio"] = abs(op_ttm / int_ttm)

        # Dividend series — cut detection and 5-year growth
        div_s = _row_series(pl, ["Dividend Payout %", "Dividend Payout"])
        out["dividend_cut_announced"] = bool(len(div_s) >= 2 and div_s[0] < div_s[1])
        if len(div_s) >= 5:
            out["dividend_growth_5y_pct"] = _pct_change(div_s[0], div_s[4])

        # ── 3. Quarterly Results ──────────────────────────────────────────────
        # FIX: heading is "Quarterly Results" not "Quarters"
        qpl = _parse_section_table(soup, ["Quarterly Results", "Quarters"])

        # EPS QoQ %
        eps_q = _row_series(qpl, ["EPS in Rs", "EPS"])
        if len(eps_q) >= 2:
            out["eps_qoq_pct"] = _pct_change(eps_q[0], eps_q[1])

        # Revenue decline consecutive quarters
        sales_q = _row_series(qpl, ["Sales", "Revenue", "Net Sales"])
        if sales_q:
            out["revenue_decline_quarters_consecutive"] = _consec_decline(sales_q)

        # Net margin 2 quarters ago
        np_q = _row_series(qpl, ["Net Profit"])
        if len(np_q) >= 3 and len(sales_q) >= 3 and sales_q[2] != 0:
            out["net_margin_2q_ago"] = (np_q[2] / sales_q[2]) * 100.0

        # ── 4. Balance Sheet ──────────────────────────────────────────────────
        bs = _parse_section_table(soup, ["Balance Sheet"])

        share_cap_s  = _row_series(bs, ["Share Capital", "Equity Capital"])
        reserves_s   = _row_series(bs, ["Reserves"])
        borrowings_s = _row_series(bs, ["Borrowings"])
        fixed_assets = _row_ttm(bs,    ["Fixed Assets", "Net Block"]) or 0.0
        cwip         = _row_ttm(bs,    ["CWIP", "Capital Work in Progress"]) or 0.0
        investments  = _row_ttm(bs,    ["Investments"]) or 0.0
        total_assets = _row_ttm(bs,    ["Total Assets"])
        total_liab   = _row_ttm(bs,    ["Total Liabilities"])
        cash_bs      = _row_ttm(bs,    ["Cash Equivalents", "Cash Bank", "Cash"])
        receivables  = _row_ttm(bs,    ["Trade Receivables", "Debtors"]) or 0.0
        inventories  = _row_ttm(bs,    ["Inventories", "Inventory"]) or 0.0
        loans_adv    = _row_ttm(bs,    ["Loans n Advances", "Loans and Advances",
                                        "Loans & Advances"]) or 0.0
        other_assets = _row_ttm(bs,    ["Other Assets", "Other asset items"]) or 0.0

        borrowings_latest = borrowings_s[0] if borrowings_s else None
        borrowings_prev   = borrowings_s[1] if len(borrowings_s) >= 2 else None

        # Shareholders' equity = Share Capital + Reserves
        def _equity(idx: int) -> float | None:
            sc = share_cap_s[idx] if len(share_cap_s) > idx else None
            rv = reserves_s[idx]  if len(reserves_s)  > idx else None
            if sc is None and rv is None:
                return None
            return (sc or 0.0) + (rv or 0.0)

        equity_latest = _equity(0)
        equity_prev   = _equity(1)

        # D/E computed from B/S — more granular than top-ratios scalar
        de_latest = _safe_div(borrowings_latest, equity_latest)
        de_prev   = _safe_div(borrowings_prev,   equity_prev)

        if de_latest is not None:
            out["debt_to_equity"] = de_latest           # override top-ratios
        elif _debt_eq_topratios is not None:
            out["debt_to_equity"] = _debt_eq_topratios  # fallback

        if de_latest is not None and de_prev is not None:
            delta = de_latest - de_prev
            out["debt_to_equity_yoy_change"] = delta
            out["debt_to_equity_change_yoy"] = delta    # alias used by FUND-004

        # Current Assets (sum of liquid/short-term balance sheet items)
        current_assets = (
            (cash_bs     or 0.0) +
            receivables  +
            inventories  +
            loans_adv    +
            other_assets
        ) if any(v is not None for v in [cash_bs, receivables, inventories]) else None

        # Current Liabilities = Total Liabilities - Equity - Long-term Borrowings
        # (captures trade payables, short-term provisions, other current liabilities)
        current_liab: float | None = None
        if (
            total_liab      is not None and
            equity_latest   is not None and
            borrowings_latest is not None
        ):
            cl = total_liab - equity_latest - borrowings_latest
            current_liab = max(cl, 1.0)   # floor at 1 Cr to avoid div-by-zero

        # Current Ratio = Current Assets / Current Liabilities
        if current_assets is not None and current_liab is not None and current_liab > 0:
            out["current_ratio"] = current_assets / current_liab

        # Quick Ratio = (Cash + Receivables) / Current Liabilities
        # Excludes inventories, loans & advances, other assets
        if cash_bs is not None and current_liab is not None and current_liab > 0:
            out["quick_ratio"] = (cash_bs + receivables) / current_liab

        # ROA = Net Profit TTM / Total Assets × 100
        if np_ttm is not None and total_assets is not None and total_assets > 0:
            out["roa_pct"] = (np_ttm / total_assets) * 100.0

        # ── 5. Cash Flow ──────────────────────────────────────────────────────
        cf = _parse_section_table(soup, ["Cash Flows", "Cash Flow"])

        fcf_s = _row_series(cf, ["Free Cash Flow"])

        if fcf_s and mktcap and mktcap > 0:
            out["fcf_yield_pct"] = (fcf_s[0] / mktcap) * 100.0

        out["fcf_negative_quarters_consecutive"] = _consec_negative(fcf_s)

        # ── 6. Multi-source computed ratios ──────────────────────────────────

        # EV/EBITDA
        # EV = Market Cap + Borrowings - Cash  (all ₹ Cr)
        # EBITDA = Operating Profit + Depreciation  (TTM, ₹ Cr)
        if (
            mktcap            is not None and
            borrowings_latest is not None and
            cash_bs           is not None and
            op_ttm            is not None
        ):
            ev     = mktcap + borrowings_latest - cash_bs
            ebitda = (op_ttm or 0.0) + (dep_ttm or 0.0)
            if ebitda > 0:
                out["ev_ebitda"] = ev / ebitda

        # PEG = Stock P/E / EPS YoY growth rate
        # Only valid when growth is positive (negative PEG is meaningless)
        eps_yoy = out.get("eps_yoy_pct")
        if pe_trail is not None and eps_yoy is not None and eps_yoy > 0:
            out["peg_ratio"] = pe_trail / eps_yoy

        # Forward P/E (estimated) = Price / (EPS_TTM × (1 + trailing_growth))
        # Uses recent EPS growth as best available proxy for near-term earnings.
        if cmp is not None and eps_ttm is not None and eps_ttm > 0 and eps_yoy is not None:
            est_next_eps = eps_ttm * (1.0 + eps_yoy / 100.0)
            if est_next_eps > 0:
                out["forward_pe"] = cmp / est_next_eps

        # ── 7. Shareholding ───────────────────────────────────────────────────
        sh = _parse_section_table(soup, ["Shareholding Pattern"])
        promoter_s = _row_series(sh, ["Promoters", "Promoter holding"])
        if promoter_s:
            out["promoter_holding_pct"] = promoter_s[0]

        # ── 8. Text heuristics ────────────────────────────────────────────────
        text = soup.get_text(" ", strip=True).lower()
        out["has_fraud_allegation"] = any(
            kw in text for kw in (
                "fraud", "scam", "sebi probe", "forensic audit",
                "falsification", "misappropriation",
            )
        )
        out["guidance_revisions_up_q"] = _count_phrases(
            text,
            ["raised guidance", "upward guidance", "guidance raised", "upgraded guidance"],
        )

        # ── 9. Derived boolean flags ──────────────────────────────────────────
        # revenue_growing
        if len(sales_s) >= 2:
            out["revenue_growing"] = bool(sales_s[0] > sales_s[1])

        # margin_improving: current TTM net margin vs prior year
        if (
            len(np_s) >= 2 and
            len(sales_s) >= 2 and
            sales_s[1] != 0 and
            "net_margin_current" in out
        ):
            margin_prev = (np_s[1] / sales_s[1]) * 100.0
            out["margin_improving"] = bool(out["net_margin_current"] > margin_prev)

        # is_growth_stock: either EPS or revenue growing >= 15% YoY
        rev_yoy = out.get("revenue_yoy_pct")
        if eps_yoy is not None or rev_yoy is not None:
            out["is_growth_stock"] = bool(
                (eps_yoy is not None and eps_yoy >= 15.0) or
                (rev_yoy is not None and rev_yoy >= 15.0)
            )

        # is_financial_sector: keyword heuristic from near-top page text
        out["is_financial_sector"] = any(
            kw in text[:3000] for kw in (
                "bank", "nbfc", "insurance", "financial services", "housing finance",
            )
        )

        # ── 10. Fixed defaults ────────────────────────────────────────────────
        out["eps_misses_consecutive"] = 0  # no analyst estimate data in Screener

        # ── 11. NOT COMPUTABLE — confirmed absent, leave unset ────────────────
        # sector_pe_avg, pe_5y_avg, industry_ev_ebitda_median,
        # industry_avg_margin, company_age_years
        # Rule engine skips any rule whose data_required fields are absent.

        # Strip None — ContextBuilder uses "key in ctx", not truthiness.
        return {k: v for k, v in out.items() if v is not None}


__all__ = ["ScreenerProvider"]
