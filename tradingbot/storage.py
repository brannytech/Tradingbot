import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS candles (
 market TEXT NOT NULL, symbol TEXT NOT NULL, interval INTEGER NOT NULL,
 timestamp INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(market,symbol,interval,timestamp));
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
 kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, environment TEXT NOT NULL, state TEXT NOT NULL,
 payload TEXT NOT NULL, updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL);
INSERT OR IGNORE INTO schema_version VALUES(1);
"""


class Store:
    def __init__(self, path="data/paper.sqlite3"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def event(self, kind, payload):
        # Callers pass domain data only. Never pass requests or credential config.
        with self.lock, self.db:
            last = self.db.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            previous = last[0] if last else "0"*64
            stamp = int(time.time())
            data = json.dumps(payload, sort_keys=True, allow_nan=False)
            digest = hashlib.sha256(f"{stamp}|{kind}|{data}|{previous}".encode()).hexdigest()
            self.db.execute("INSERT INTO events(timestamp,kind,payload,previous_hash,hash) VALUES(?,?,?,?,?)",
                            (stamp, kind, data, previous, digest))

    def audit_valid(self):
        previous = "0"*64
        with self.lock:
            for stamp, kind, data, prev, digest in self.db.execute("SELECT timestamp,kind,payload,previous_hash,hash FROM events ORDER BY id"):
                if prev != previous or hashlib.sha256(f"{stamp}|{kind}|{data}|{prev}".encode()).hexdigest() != digest:
                    return False
                previous = digest
        return True

    def put_setting(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_candles(self, context):
        context.checked()
        from dataclasses import asdict
        with self.lock, self.db:
            self.db.executemany("INSERT OR REPLACE INTO candles VALUES(?,?,?,?,?)",
                [(context.market, context.instrument, context.interval, c.timestamp, json.dumps(asdict(c))) for c in context.candles])

    def reserve_order(self, key, environment, payload):
        if environment not in ("paper", "demo"):
            raise ValueError("Production order persistence disabled")
        with self.lock, self.db:
            try:
                self.db.execute("INSERT INTO orders VALUES(?,?,?,?,?)",
                    (key, environment, "PENDING", json.dumps(payload), int(time.time())))
            except sqlite3.IntegrityError:
                return False
        return True

    def update_order(self, key, state, payload):
        with self.lock, self.db:
            self.db.execute("UPDATE orders SET state=?,payload=?,updated=? WHERE id=?",
                (state, json.dumps(payload), int(time.time()), key))

    def orders(self):
        with self.lock:
            return [dict(id=i, environment=e, state=s, payload=json.loads(p), updated=t)
                    for i, e, s, p, t in self.db.execute("SELECT * FROM orders ORDER BY updated DESC")]

    def save_report(self, kind, payload):
        with self.lock, self.db:
            self.db.execute("INSERT INTO reports(kind,payload) VALUES(?,?)", (kind, json.dumps(payload, allow_nan=False)))

    def reports(self):
        with self.lock:
            return [dict(id=i, kind=k, payload=json.loads(p)) for i, k, p in self.db.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 20")]

    def events(self):
        with self.lock:
            return [dict(id=i,timestamp=t,kind=k,payload=json.loads(p),hash=h) for i,t,k,p,h in
                    self.db.execute("SELECT id,timestamp,kind,payload,hash FROM events ORDER BY id DESC LIMIT 30")]

    def close(self):
        self.db.close()
