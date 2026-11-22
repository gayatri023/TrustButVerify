"""SQLite results store. Keyed by (agent, task, repeat, attempt) so runs are idempotent."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  agent TEXT, task TEXT, repeat INTEGER, attempt INTEGER,
  split TEXT, task_type TEXT, difficulty TEXT,
  status TEXT, claimed_done INTEGER, final_message TEXT,
  steps INTEGER, tokens_in INTEGER, tokens_out INTEGER, run_seconds REAL,
  gate_overall TEXT, gate_seconds REAL, extraction_method TEXT,
  completed_correctly INTEGER, hidden_only_ok INTEGER, visible_ok INTEGER,
  tampered INTEGER, taxonomy TEXT,
  model TEXT, config_hash TEXT, gate_version INTEGER, fixture INTEGER DEFAULT 0, created_at REAL,
  PRIMARY KEY(agent, task, repeat, attempt));
CREATE TABLE IF NOT EXISTS claims(
  agent TEXT, task TEXT, repeat INTEGER, attempt INTEGER, idx INTEGER,
  type TEXT, polarity TEXT, verdict TEXT, reason TEXT, span TEXT, implicit INTEGER);
CREATE TABLE IF NOT EXISTS verifiers(
  agent TEXT, task TEXT, repeat INTEGER, attempt INTEGER, name TEXT, status TEXT, runtime_s REAL);
CREATE TABLE IF NOT EXISTS tamper(
  agent TEXT, task TEXT, repeat INTEGER, attempt INTEGER, rule_id TEXT, severity TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS test_lock(
  id INTEGER PRIMARY KEY CHECK(id=1), config_hash TEXT, locked_at REAL);
CREATE TABLE IF NOT EXISTS quota(
  model TEXT, day TEXT, used INTEGER, PRIMARY KEY(model, day));
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=DELETE")
        self.con.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.con:  # commits on success, rolls back on error
            yield self.con

    def has_run(self, agent: str, task: str, repeat: int, attempt: int) -> bool:
        row = self.con.execute(
            "SELECT 1 FROM runs WHERE agent=? AND task=? AND repeat=? AND attempt=?",
            (agent, task, repeat, attempt),
        ).fetchone()
        return row is not None

    def insert(self, table: str, values: dict[str, object]) -> None:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        with self.tx() as c:
            c.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(values.values()))  # noqa: S608

    def lock_test_config(self, config_hash: str) -> None:
        """First TEST evaluation records the config hash; later ones must use the same hash."""
        row = self.con.execute("SELECT config_hash FROM test_lock WHERE id=1").fetchone()
        if row is None:
            with self.tx() as c:
                c.execute("INSERT INTO test_lock VALUES(1, ?, ?)", (config_hash, time.time()))
        elif row["config_hash"] != config_hash:
            raise TestSplitGuard(
                "gate/agent config changed after the first TEST evaluation; refusing to run"
            )

    def add_quota(self, model: str, day: str, n: int = 1) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO quota VALUES(?,?,?) ON CONFLICT(model,day) DO UPDATE SET used=used+?",
                (model, day, n, n),
            )

    def used_quota(self, model: str, day: str) -> int:
        row = self.con.execute(
            "SELECT used FROM quota WHERE model=? AND day=?", (model, day)
        ).fetchone()
        return int(row["used"]) if row else 0

    def close(self) -> None:
        self.con.close()


class TestSplitGuard(RuntimeError):
    __test__ = False  # not a pytest class
