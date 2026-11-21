"""SQLite kalicilik katmani (Python standart kutuphanesi; ek bagimlilik yok).

WAL modu: Android'in sureci aniden oldurmesine karsi daha dayanikli.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,           -- long | short
    status          TEXT NOT NULL,           -- open | closed
    qty             REAL NOT NULL,           -- kontrat adedi (borsa birimi)
    contract_size   REAL NOT NULL,
    entry_price     REAL NOT NULL,
    initial_sl      REAL NOT NULL,
    sl              REAL NOT NULL,
    tp              REAL NOT NULL,
    risk_usdt       REAL NOT NULL,
    notional_usdt   REAL NOT NULL,
    liq_price       REAL,
    opened_at       INTEGER NOT NULL,        -- ms
    opened_bar_ts   INTEGER NOT NULL,        -- sinyal mumunun acilis ms
    sl_order_id     TEXT,
    tp_order_id     TEXT,
    breakeven_done  INTEGER NOT NULL DEFAULT 0,
    closed_at       INTEGER,
    exit_price      REAL,
    pnl_usdt        REAL,
    fees_usdt       REAL,
    exit_reason     TEXT,
    meta            TEXT
);
CREATE INDEX IF NOT EXISTS ix_trades_status ON trades(status);
CREATE TABLE IF NOT EXISTS oi_snapshots (
    symbol  TEXT NOT NULL,
    ts      INTEGER NOT NULL,
    oi_usd  REAL NOT NULL,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS signals (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      INTEGER NOT NULL,
    symbol  TEXT NOT NULL,
    side    TEXT,
    action  TEXT NOT NULL,
    detail  TEXT
);
"""


@dataclass
class Trade:
    mode: str
    exchange: str
    symbol: str
    side: str
    qty: float
    contract_size: float
    entry_price: float
    initial_sl: float
    sl: float
    tp: float
    risk_usdt: float
    notional_usdt: float
    opened_at: int
    opened_bar_ts: int
    status: str = "open"
    liq_price: Optional[float] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    breakeven_done: int = 0
    closed_at: Optional[int] = None
    exit_price: Optional[float] = None
    pnl_usdt: Optional[float] = None
    fees_usdt: Optional[float] = None
    exit_reason: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None

    @property
    def base_qty(self) -> float:
        return self.qty * self.contract_size

    @property
    def direction(self) -> int:
        return 1 if self.side == "long" else -1


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- kv ----------
    def get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def set(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    # ---------- trades ----------
    def insert_trade(self, t: Trade) -> int:
        d = asdict(t)
        d.pop("id")
        d["meta"] = json.dumps(d["meta"])
        cols = ",".join(d)
        q = ",".join("?" for _ in d)
        cur = self.conn.execute(f"INSERT INTO trades({cols}) VALUES({q})", tuple(d.values()))
        self.conn.commit()
        t.id = int(cur.lastrowid)
        return t.id

    def update_trade(self, t: Trade) -> None:
        if t.id is None:
            raise ValueError("id'siz trade guncellenemez")
        d = asdict(t)
        tid = d.pop("id")
        d["meta"] = json.dumps(d["meta"])
        sets = ",".join(f"{k}=?" for k in d)
        self.conn.execute(f"UPDATE trades SET {sets} WHERE id=?", (*d.values(), tid))
        self.conn.commit()

    @staticmethod
    def _row_to_trade(r: sqlite3.Row) -> Trade:
        d = dict(r)
        d["meta"] = json.loads(d["meta"] or "{}")
        return Trade(**d)

    def open_trades(self) -> List[Trade]:
        rows = self.conn.execute("SELECT * FROM trades WHERE status='open' ORDER BY id").fetchall()
        return [self._row_to_trade(r) for r in rows]

    def closed_trades(self, since_ms: int = 0, mode: Optional[str] = None) -> List[Trade]:
        q = "SELECT * FROM trades WHERE status='closed' AND closed_at>=?"
        args: list = [since_ms]
        if mode:
            q += " AND mode=?"
            args.append(mode)
        rows = self.conn.execute(q + " ORDER BY closed_at", args).fetchall()
        return [self._row_to_trade(r) for r in rows]

    # ---------- OI ----------
    def add_oi(self, symbol: str, ts: int, oi_usd: float) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO oi_snapshots(symbol,ts,oi_usd) VALUES(?,?,?)", (symbol, ts, oi_usd)
        )
        cutoff = ts - 14 * 24 * 3600 * 1000
        self.conn.execute("DELETE FROM oi_snapshots WHERE ts<?", (cutoff,))
        self.conn.commit()

    def prev_oi(self, symbol: str, before_ts: int) -> Optional[float]:
        row = self.conn.execute(
            "SELECT oi_usd FROM oi_snapshots WHERE symbol=? AND ts<? ORDER BY ts DESC LIMIT 1",
            (symbol, before_ts),
        ).fetchone()
        return None if row is None else float(row["oi_usd"])

    # ---------- signals ----------
    def log_signal(self, symbol: str, side: Optional[str], action: str, detail: Any = None) -> None:
        self.conn.execute(
            "INSERT INTO signals(ts,symbol,side,action,detail) VALUES(?,?,?,?,?)",
            (int(time.time() * 1000), symbol, side, action, json.dumps(detail, default=str)),
        )
        self.conn.commit()
