"""Bundled ticker groups for the Tech Bro badge.

Alpha Vantage trade rows do not include a sector. This list is a playful,
hand-maintained set of widely held technology names. It is not a GICS feed.
Unlisted tickers simply do not count as tech, which keeps the badge from
firing on an unknown book.
"""

TECH_TICKERS = {
    "AAPL",
    "ADBE",
    "ADI",
    "ADSK",
    "AMAT",
    "AMD",
    "AMZN",
    "ANET",
    "ARM",
    "ASML",
    "AVGO",
    "CDNS",
    "CRM",
    "CRWD",
    "CSCO",
    "DDOG",
    "DELL",
    "FTNT",
    "GOOG",
    "GOOGL",
    "HPE",
    "HPQ",
    "IBM",
    "INTC",
    "INTU",
    "KLAC",
    "LRCX",
    "MDB",
    "META",
    "MRVL",
    "MSFT",
    "MU",
    "NET",
    "NFLX",
    "NOW",
    "NVDA",
    "NXPI",
    "ON",
    "ORCL",
    "PANW",
    "PLTR",
    "PYPL",
    "QCOM",
    "SHOP",
    "SMCI",
    "SNOW",
    "SNPS",
    "SQ",
    "TEAM",
    "TSLA",
    "TSM",
    "TXN",
    "UBER",
    "WDAY",
    "ZS",
}


def is_tech(symbol: str) -> bool:
    return symbol.upper() in TECH_TICKERS
