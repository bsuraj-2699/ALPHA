"""Master ticker registry for Indian equity market.

Internal format: bare NSE symbol (RELIANCE, TCS, INFY)
Provider adapters convert to their required format:
  Yahoo Finance  → symbol + ".NS"
  Screener.in    → symbol as-is
  Upstox         → NSE_EQ|ISIN  (from this registry)
  NSE provider   → symbol as-is

For tickers NOT in this registry:
  Yahoo/Screener → fallback works automatically (append .NS)
  Upstox         → symbol-based key fallback (NSE_EQ|SYMBOL)
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Master registry — Nifty 50 + Nifty Next 50
# Format: { "SYMBOL": {"name": ..., "upstox": "NSE_EQ|ISIN", "sector": ...} }
# ─────────────────────────────────────────────────────────────────────────────

IN_TICKERS: dict[str, dict] = {
    # ── Nifty 50 ─────────────────────────────────────────────────────────────
    "RELIANCE":    {"name": "Reliance Industries",        "upstox": "NSE_EQ|INE002A01018", "sector": "energy"},
    "TCS":         {"name": "Tata Consultancy Services",  "upstox": "NSE_EQ|INE467B01029", "sector": "technology"},
    "HDFCBANK":    {"name": "HDFC Bank",                  "upstox": "NSE_EQ|INE040A01034", "sector": "financials"},
    "ICICIBANK":   {"name": "ICICI Bank",                 "upstox": "NSE_EQ|INE090A01021", "sector": "financials"},
    "INFY":        {"name": "Infosys",                    "upstox": "NSE_EQ|INE009A01021", "sector": "technology"},
    "HINDUNILVR":  {"name": "Hindustan Unilever",         "upstox": "NSE_EQ|INE030A01027", "sector": "consumer_defensive"},
    "ITC":         {"name": "ITC Limited",                "upstox": "NSE_EQ|INE154A01025", "sector": "consumer_defensive"},
    "SBIN":        {"name": "State Bank of India",        "upstox": "NSE_EQ|INE062A01020", "sector": "financials"},
    "BHARTIARTL":  {"name": "Bharti Airtel",              "upstox": "NSE_EQ|INE397D01024", "sector": "technology"},
    "KOTAKBANK":   {"name": "Kotak Mahindra Bank",        "upstox": "NSE_EQ|INE237A01028", "sector": "financials"},
    "LT":          {"name": "Larsen & Toubro",            "upstox": "NSE_EQ|INE018A01030", "sector": "industrials"},
    "HCLTECH":     {"name": "HCL Technologies",           "upstox": "NSE_EQ|INE860A01027", "sector": "technology"},
    "AXISBANK":    {"name": "Axis Bank",                  "upstox": "NSE_EQ|INE238A01034", "sector": "financials"},
    "ASIANPAINT":  {"name": "Asian Paints",               "upstox": "NSE_EQ|INE021A01026", "sector": "materials"},
    "MARUTI":      {"name": "Maruti Suzuki",              "upstox": "NSE_EQ|INE585B01010", "sector": "consumer_cyclical"},
    "SUNPHARMA":   {"name": "Sun Pharmaceutical",         "upstox": "NSE_EQ|INE044A01036", "sector": "healthcare"},
    "TITAN":       {"name": "Titan Company",              "upstox": "NSE_EQ|INE280A01028", "sector": "consumer_cyclical"},
    "BAJFINANCE":  {"name": "Bajaj Finance",              "upstox": "NSE_EQ|INE296A01024", "sector": "financials"},
    "WIPRO":       {"name": "Wipro",                      "upstox": "NSE_EQ|INE075A01022", "sector": "technology"},
    "ULTRACEMCO":  {"name": "UltraTech Cement",           "upstox": "NSE_EQ|INE481G01011", "sector": "materials"},
    "ONGC":        {"name": "ONGC",                       "upstox": "NSE_EQ|INE213A01029", "sector": "energy"},
    "NTPC":        {"name": "NTPC",                       "upstox": "NSE_EQ|INE733E01010", "sector": "utilities"},
    "POWERGRID":   {"name": "Power Grid Corp",            "upstox": "NSE_EQ|INE752E01010", "sector": "utilities"},
    "TATAMOTORS":  {"name": "Tata Motors",                "upstox": "NSE_EQ|INE155A01022", "sector": "consumer_cyclical"},
    "TATASTEEL":   {"name": "Tata Steel",                 "upstox": "NSE_EQ|INE081A01012", "sector": "materials"},
    "NESTLEIND":   {"name": "Nestle India",               "upstox": "NSE_EQ|INE239A01016", "sector": "consumer_defensive"},
    "TECHM":       {"name": "Tech Mahindra",              "upstox": "NSE_EQ|INE669C01036", "sector": "technology"},
    "HDFCLIFE":    {"name": "HDFC Life Insurance",        "upstox": "NSE_EQ|INE795G01014", "sector": "financials"},
    "SBILIFE":     {"name": "SBI Life Insurance",         "upstox": "NSE_EQ|INE123W01016", "sector": "financials"},
    "INDUSINDBK":  {"name": "IndusInd Bank",              "upstox": "NSE_EQ|INE095A01012", "sector": "financials"},
    "BAJAJFINSV":  {"name": "Bajaj Finserv",              "upstox": "NSE_EQ|INE918I01026", "sector": "financials"},
    "HINDALCO":    {"name": "Hindalco Industries",        "upstox": "NSE_EQ|INE038A01020", "sector": "materials"},
    "ADANIENT":    {"name": "Adani Enterprises",          "upstox": "NSE_EQ|INE423A01024", "sector": "industrials"},
    "ADANIPORTS":  {"name": "Adani Ports",                "upstox": "NSE_EQ|INE742F01042", "sector": "industrials"},
    "COALINDIA":   {"name": "Coal India",                 "upstox": "NSE_EQ|INE522F01014", "sector": "energy"},
    "CIPLA":       {"name": "Cipla",                      "upstox": "NSE_EQ|INE059A01026", "sector": "healthcare"},
    "DRREDDY":     {"name": "Dr. Reddy's Laboratories",  "upstox": "NSE_EQ|INE089A01031", "sector": "healthcare"},
    "EICHERMOT":   {"name": "Eicher Motors",              "upstox": "NSE_EQ|INE066A01013", "sector": "consumer_cyclical"},
    "HEROMOTOCO":  {"name": "Hero MotoCorp",              "upstox": "NSE_EQ|INE158A01026", "sector": "consumer_cyclical"},
    "APOLLOHOSP":  {"name": "Apollo Hospitals",           "upstox": "NSE_EQ|INE437A01024", "sector": "healthcare"},
    "TATACONSUM":  {"name": "Tata Consumer Products",    "upstox": "NSE_EQ|INE192A01025", "sector": "consumer_defensive"},
    "BRITANNIA":   {"name": "Britannia Industries",       "upstox": "NSE_EQ|INE216A01030", "sector": "consumer_defensive"},
    "BPCL":        {"name": "BPCL",                       "upstox": "NSE_EQ|INE029A01011", "sector": "energy"},
    "SHREECEM":    {"name": "Shree Cement",               "upstox": "NSE_EQ|INE070A01015", "sector": "materials"},
    "JSWSTEEL":    {"name": "JSW Steel",                  "upstox": "NSE_EQ|INE019A01038", "sector": "materials"},
    "DIVISLAB":    {"name": "Divi's Laboratories",        "upstox": "NSE_EQ|INE361B01024", "sector": "healthcare"},
    "GRASIM":      {"name": "Grasim Industries",          "upstox": "NSE_EQ|INE047A01021", "sector": "materials"},
    "M&M":         {"name": "Mahindra & Mahindra",        "upstox": "NSE_EQ|INE101A01026", "sector": "consumer_cyclical"},
    "BAJAJ-AUTO":  {"name": "Bajaj Auto",                 "upstox": "NSE_EQ|INE917I01010", "sector": "consumer_cyclical"},
    "SBICARD":     {"name": "SBI Cards",                  "upstox": "NSE_EQ|INE018E01016", "sector": "financials"},

    # ── Nifty Next 50 (commonly traded) ──────────────────────────────────────
    "VEDL":        {"name": "Vedanta",                    "upstox": "NSE_EQ|INE205A01025", "sector": "materials"},
    "TATAPOWER":   {"name": "Tata Power",                 "upstox": "NSE_EQ|INE245A01021", "sector": "utilities"},
    "IOC":         {"name": "Indian Oil Corp",            "upstox": "NSE_EQ|INE242A01010", "sector": "energy"},
    "HDFCAMC":     {"name": "HDFC AMC",                   "upstox": "NSE_EQ|INE127D01025", "sector": "financials"},
    "PIDILITIND":  {"name": "Pidilite Industries",        "upstox": "NSE_EQ|INE318A01026", "sector": "materials"},
    "SIEMENS":     {"name": "Siemens India",              "upstox": "NSE_EQ|INE003A01024", "sector": "industrials"},
    "HAVELLS":     {"name": "Havells India",              "upstox": "NSE_EQ|INE176B01034", "sector": "industrials"},
    "BERGEPAINT":  {"name": "Berger Paints",              "upstox": "NSE_EQ|INE463A01038", "sector": "materials"},
    "MUTHOOTFIN":  {"name": "Muthoot Finance",            "upstox": "NSE_EQ|INE414G01012", "sector": "financials"},
    "ICICIPRULI":  {"name": "ICICI Prudential Life",      "upstox": "NSE_EQ|INE726G01019", "sector": "financials"},
    "BANKBARODA":  {"name": "Bank of Baroda",             "upstox": "NSE_EQ|INE028A01039", "sector": "financials"},
    "PNB":         {"name": "Punjab National Bank",       "upstox": "NSE_EQ|INE160A01022", "sector": "financials"},
    "MARICO":      {"name": "Marico",                     "upstox": "NSE_EQ|INE196A01026", "sector": "consumer_defensive"},
    "GODREJCP":    {"name": "Godrej Consumer Products",  "upstox": "NSE_EQ|INE102D01028", "sector": "consumer_defensive"},
    "DABUR":       {"name": "Dabur India",                "upstox": "NSE_EQ|INE016A01026", "sector": "consumer_defensive"},
    "COLPAL":      {"name": "Colgate-Palmolive India",   "upstox": "NSE_EQ|INE259A01022", "sector": "consumer_defensive"},
    "TORNTPHARM":  {"name": "Torrent Pharmaceuticals",   "upstox": "NSE_EQ|INE685A01028", "sector": "healthcare"},
    "LUPIN":       {"name": "Lupin",                      "upstox": "NSE_EQ|INE326A01037", "sector": "healthcare"},
    "AUROBINDO":   {"name": "Aurobindo Pharma",           "upstox": "NSE_EQ|INE406A01037", "sector": "healthcare"},
    "BOSCHLTD":    {"name": "Bosch",                      "upstox": "NSE_EQ|INE323A01026", "sector": "consumer_cyclical"},
    "AMBUJACEM":   {"name": "Ambuja Cements",             "upstox": "NSE_EQ|INE079A01024", "sector": "materials"},
    "ACC":         {"name": "ACC",                        "upstox": "NSE_EQ|INE012A01025", "sector": "materials"},
    "CONCOR":      {"name": "Container Corp of India",   "upstox": "NSE_EQ|INE111A01025", "sector": "industrials"},
    "INDIGO":      {"name": "IndiGo (InterGlobe Aviation)","upstox":"NSE_EQ|INE646L01027", "sector": "industrials"},
    "ZOMATO":      {"name": "Zomato",                     "upstox": "NSE_EQ|INE758T01015", "sector": "consumer_cyclical"},
    "NYKAA":       {"name": "Nykaa (FSN E-Commerce)",    "upstox": "NSE_EQ|INE388Y01029", "sector": "consumer_cyclical"},
    "PAYTM":       {"name": "Paytm (One 97 Communications)","upstox":"NSE_EQ|INE982J01020","sector": "technology"},
    "DMART":       {"name": "Avenue Supermarts (DMart)", "upstox": "NSE_EQ|INE192R01011", "sector": "consumer_defensive"},
    "IRCTC":       {"name": "IRCTC",                      "upstox": "NSE_EQ|INE335Y01020", "sector": "consumer_cyclical"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Adapter functions
# ─────────────────────────────────────────────────────────────────────────────

def normalize(ticker: str) -> str:
    """Strip exchange suffixes → canonical bare symbol.

    RELIANCE.NS → RELIANCE
    INFY.BO     → INFY
    TCS         → TCS
    """
    return ticker.split(".")[0].upper().strip()


def to_yahoo(ticker: str) -> str:
    """Bare symbol → Yahoo Finance ticker.

    RELIANCE → RELIANCE.NS  (works for ALL listed NSE stocks)
    """
    bare = normalize(ticker)
    return f"{bare}.NS"


def to_screener(ticker: str) -> str:
    """Bare symbol → Screener.in symbol (no change needed).

    RELIANCE → RELIANCE
    """
    return normalize(ticker)


def to_upstox(ticker: str) -> str:
    """Bare symbol → Upstox instrument key.

    RELIANCE → NSE_EQ|INE002A01018

    Falls back to NSE_EQ|SYMBOL for tickers not in registry.
    This fallback works for most liquid NSE stocks.
    """
    bare = normalize(ticker)
    entry = IN_TICKERS.get(bare)
    if entry:
        return entry["upstox"]
    # Fallback: symbol-based key (works for most NSE stocks on Upstox)
    return f"NSE_EQ|{bare}"


def get_sector(ticker: str) -> str | None:
    """Return sector for a ticker if known."""
    bare = normalize(ticker)
    entry = IN_TICKERS.get(bare)
    return entry["sector"] if entry else None


def is_known(ticker: str) -> bool:
    """Return True if ticker is in the registry."""
    return normalize(ticker) in IN_TICKERS


__all__ = [
    "IN_TICKERS",
    "normalize",
    "to_yahoo",
    "to_screener",
    "to_upstox",
    "get_sector",
    "is_known",
]
