"""SQLite storage for live snapshots and paper trades."""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  ts REAL, asset TEXT, duration TEXT, start_ts INTEGER, t INTEGER, spot REAL,
  up_bid REAL, up_ask REAL, dn_bid REAL, dn_ask REAL,
  up_bids TEXT, up_asks TEXT, dn_bids TEXT, dn_asks TEXT);
CREATE INDEX IF NOT EXISTS snap_mkt ON snapshots(asset, duration, start_ts, t);
CREATE TABLE IF NOT EXISTS markets(
  asset TEXT, duration TEXT, start_ts INTEGER, slug TEXT, strike_est REAL, basis REAL,
  strike REAL, final REAL, outcome_up INTEGER, PRIMARY KEY(asset, duration, start_ts));
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, strategy TEXT, asset TEXT, start_ts INTEGER, side TEXT,
  kind TEXT, t_decision INTEGER, t_fill INTEGER, ts_fill REAL, price REAL, size REAL, fee REAL,
  prob REAL, mkt_price REAL, tag TEXT, outcome_up INTEGER, payout REAL, pnl REAL);
CREATE TABLE IF NOT EXISTS scans(
  ts REAL, kind TEXT, event TEXT, n_outcomes INTEGER, cost REAL, edge REAL, size REAL, detail TEXT);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.executescript(SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")

    def snapshot(self, ts, asset, duration, start_ts, t, spot, books):
        ub, ua = books["UP"]
        db_, da = books["DOWN"]
        f = lambda x: x[0][0] if x else None  # noqa: E731
        self.db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts, asset, duration, start_ts, t, spot, f(ub), f(ua), f(db_), f(da),
                         json.dumps(ub), json.dumps(ua), json.dumps(db_), json.dumps(da)))

    def market(self, asset, duration, start_ts, slug, strike_est, basis):
        self.db.execute("INSERT OR IGNORE INTO markets(asset,duration,start_ts,slug,strike_est,basis) VALUES(?,?,?,?,?,?)",
                        (asset, duration, start_ts, slug, strike_est, basis))

    def resolve(self, asset, duration, start_ts, strike, final, outcome_up):
        self.db.execute("UPDATE markets SET strike=?, final=?, outcome_up=? WHERE asset=? AND duration=? AND start_ts=?",
                        (strike, final, outcome_up, asset, duration, start_ts))

    def add_trade(self, tr, ts_fill) -> int:
        cur = self.db.execute(
            "INSERT INTO trades(strategy,asset,start_ts,side,kind,t_decision,t_fill,ts_fill,price,size,fee,prob,mkt_price,tag)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tr.strategy, tr.asset, tr.start_ts, tr.side, tr.kind, tr.t_decision, tr.t_fill, ts_fill, tr.price,
             tr.size, tr.fee, tr.prob, tr.mkt_price, tr.tag))
        return cur.lastrowid

    def settle_trade(self, trade_id, outcome_up, payout, pnl):
        self.db.execute("UPDATE trades SET outcome_up=?, payout=?, pnl=? WHERE id=?", (outcome_up, payout, pnl, trade_id))

    def commit(self):
        self.db.commit()
