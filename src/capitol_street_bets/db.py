"""SQLite cache. The file lives under data/cache and is gitignored."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS politicians (
    bioguide_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    chamber TEXT,
    party TEXT,
    state TEXT,
    district TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    terms_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    bioguide_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_member ON trades (bioguide_id);
CREATE TABLE IF NOT EXISTS member_sync (
    bioguide_id TEXT PRIMARY KEY,
    last_fetched_at TEXT,
    content_hash TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    price_date TEXT NOT NULL,
    close REAL NOT NULL,
    adjusted_close REAL,
    PRIMARY KEY (symbol, price_date)
);
CREATE TABLE IF NOT EXISTS price_sync (
    symbol TEXT PRIMARY KEY,
    last_fetched_at TEXT,
    last_bar TEXT,
    price_function TEXT
);
CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    function_name TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def requests_today(conn: sqlite3.Connection, day: date) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM request_log WHERE day = ?",
        (day.isoformat(),),
    ).fetchone()
    return int(row["n"])


def recent_request_times(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT ts FROM request_log ORDER BY id DESC LIMIT 400"
    ).fetchall()
    return [row["ts"] for row in rows]


def log_request(conn: sqlite3.Connection, day: date, function_name: str, status: str) -> None:
    conn.execute(
        "INSERT INTO request_log (ts, day, function_name, status) VALUES (?, ?, ?, ?)",
        (utcnow(), day.isoformat(), function_name, status),
    )


def upsert_politicians(conn: sqlite3.Connection, rows: list[dict]) -> None:
    now = utcnow()
    for row in rows:
        conn.execute(
            """
            INSERT INTO politicians (
                bioguide_id, name, chamber, party, state, district, is_current,
                terms_json, raw_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bioguide_id) DO UPDATE SET
                name = excluded.name,
                chamber = excluded.chamber,
                party = excluded.party,
                state = excluded.state,
                district = excluded.district,
                is_current = excluded.is_current,
                terms_json = excluded.terms_json,
                raw_json = excluded.raw_json,
                updated_at = excluded.updated_at
            """,
            (
                row["bioguide_id"],
                row["name"],
                row["chamber"],
                row["party"],
                row["state"],
                row["district"],
                1 if row["is_current"] else 0,
                json.dumps(row["terms"]),
                json.dumps(row["raw"]),
                now,
            ),
        )


def list_politicians(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM politicians
            ORDER BY is_current DESC, name
            """
        )
    )


def replace_member_trades(
    conn: sqlite3.Connection,
    bioguide_id: str,
    trades: list[dict],
    content_hash: str,
    fetched_at: str | None = None,
) -> None:
    conn.execute("DELETE FROM trades WHERE bioguide_id = ?", (bioguide_id,))
    for trade in trades:
        conn.execute(
            "INSERT INTO trades (trade_id, bioguide_id, payload_json) VALUES (?, ?, ?)",
            (trade["trade_id"], bioguide_id, json.dumps(trade["payload"])),
        )
    conn.execute(
        """
        INSERT INTO member_sync (bioguide_id, last_fetched_at, content_hash, status)
        VALUES (?, ?, ?, 'ok')
        ON CONFLICT(bioguide_id) DO UPDATE SET
            last_fetched_at = excluded.last_fetched_at,
            content_hash = excluded.content_hash,
            status = 'ok'
        """,
        (bioguide_id, fetched_at or utcnow(), content_hash),
    )


def member_fetched_on(conn: sqlite3.Connection, bioguide_id: str, day: date) -> bool:
    row = conn.execute(
        "SELECT last_fetched_at FROM member_sync WHERE bioguide_id = ?",
        (bioguide_id,),
    ).fetchone()
    if row is None or not row["last_fetched_at"]:
        return False
    return row["last_fetched_at"][:10] == day.isoformat()


def member_hash(conn: sqlite3.Connection, bioguide_id: str) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM member_sync WHERE bioguide_id = ?",
        (bioguide_id,),
    ).fetchone()
    return None if row is None else row["content_hash"]


def iter_trades(conn: sqlite3.Connection) -> list[tuple[str, dict]]:
    rows = conn.execute("SELECT bioguide_id, payload_json FROM trades").fetchall()
    return [(row["bioguide_id"], json.loads(row["payload_json"])) for row in rows]


def upsert_prices(conn: sqlite3.Connection, symbol: str, bars: list[tuple[str, float, float | None]]) -> int:
    inserted = 0
    for price_date, close, adjusted in bars:
        cursor = conn.execute(
            """
            INSERT INTO prices (symbol, price_date, close, adjusted_close)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, price_date) DO UPDATE SET
                close = excluded.close,
                adjusted_close = COALESCE(excluded.adjusted_close, prices.adjusted_close)
            WHERE prices.close != excluded.close
               OR IFNULL(prices.adjusted_close, -1) != IFNULL(excluded.adjusted_close, -1)
            """,
            (symbol, price_date, close, adjusted),
        )
        # INSERT OR update still counts as a write attempt. Track new dates only.
        existed = conn.execute(
            "SELECT 1 FROM prices WHERE symbol = ? AND price_date = ?",
            (symbol, price_date),
        ).fetchone()
        if existed:
            inserted += 0
        else:
            inserted += cursor.rowcount
    return inserted


def store_prices(conn: sqlite3.Connection, symbol: str, bars: dict[str, tuple[float, float | None]]) -> None:
    """Insert bars. Existing dates are left in place when the close is unchanged."""
    for price_date, (close, adjusted) in bars.items():
        conn.execute(
            """
            INSERT INTO prices (symbol, price_date, close, adjusted_close)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, price_date) DO UPDATE SET
                close = excluded.close,
                adjusted_close = COALESCE(excluded.adjusted_close, prices.adjusted_close)
            """,
            (symbol, price_date, close, adjusted),
        )


def last_bar(conn: sqlite3.Connection, symbol: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(price_date) AS last_bar FROM prices WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    if row is None:
        return None
    return row["last_bar"]


def mark_price_sync(conn: sqlite3.Connection, symbol: str, last: str | None, function_name: str) -> None:
    conn.execute(
        """
        INSERT INTO price_sync (symbol, last_fetched_at, last_bar, price_function)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            last_fetched_at = excluded.last_fetched_at,
            last_bar = excluded.last_bar,
            price_function = excluded.price_function
        """,
        (symbol, utcnow(), last, function_name),
    )


def load_price_book_rows(conn: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """symbol -> iso date -> close, preferring adjusted_close when present."""
    out: dict[str, dict[str, float]] = {}
    for row in conn.execute("SELECT symbol, price_date, close, adjusted_close FROM prices"):
        value = row["adjusted_close"] if row["adjusted_close"] is not None else row["close"]
        out.setdefault(row["symbol"], {})[row["price_date"]] = float(value)
    return out


def distinct_trade_symbols(conn: sqlite3.Connection) -> list[str]:
    symbols = set()
    for _bioguide, payload in iter_trades(conn):
        symbol = str(payload.get("symbol") or "").strip().upper()
        if symbol:
            symbols.add(symbol)
    return sorted(symbols)
