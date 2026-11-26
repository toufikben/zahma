"""طابور محلي دائم — مقاومة انقطاع الشبكة.

المشكلة: عينة حركة فاتت لا تُستعاد. لكن ما جُلب يجب ألا يُفقد.
الحل: كل نتيجة تُكتب محلياً أولاً (SQLite WAL)، ثم تُرفع لـPostgres.
إن انقطع الاتصال، يبقى الطابور وينتظر.

التصميم:
- جدول واحد `pending` يحتوي النتيجة كاملة (JSON) + محاولات + حالة.
- إدراج idempotent في Postgres بمفتاح (segment_id, source, ts_bucket).
- حذف من الطابور فقط بعد نجاح الإدراج.
- حد أقصى للمحاولات، ثم يُنقل إلى `dead` للمراجعة اليدوية.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from zahma.config import ROOT

QUEUE_PATH = ROOT / "data" / "queue.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- segments|routes|incidents|meta
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    next_try_at TEXT
);
CREATE INDEX IF NOT EXISTS pending_source_idx ON pending (source, id);

CREATE TABLE IF NOT EXISTS dead (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    failed_at   TEXT NOT NULL,
    attempts    INTEGER NOT NULL,
    last_error  TEXT
);

CREATE TABLE IF NOT EXISTS heartbeat (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    ts    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(QUEUE_PATH, timeout=30.0)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def push(source: str, kind: str, payload: dict[str, Any] | list[Any]) -> int:
    """يضيف عنصراً للطابور. يعيد المعرّف."""
    with conn() as c:
        cur = c.execute(
            "INSERT INTO pending (source, kind, payload, created_at, next_try_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, kind, json.dumps(payload, ensure_ascii=False), _now(), _now()),
        )
        return int(cur.lastrowid)


def push_many(source: str, kind: str, payloads: list[Any]) -> int:
    if not payloads:
        return 0
    now = _now()
    with conn() as c:
        c.executemany(
            "INSERT INTO pending (source, kind, payload, created_at, next_try_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(source, kind, json.dumps(p, ensure_ascii=False), now, now) for p in payloads],
        )
    return len(payloads)


def claim(limit: int = 500, source: str | None = None) -> list[tuple[int, str, str, str]]:
    """يأخذ دفعة جاهزة للمعالجة (next_try_at <= الآن)."""
    now = _now()
    with conn() as c:
        if source:
            rows = c.execute(
                "SELECT id, source, kind, payload FROM pending "
                "WHERE next_try_at <= ? AND source = ? ORDER BY id LIMIT ?",
                (now, source, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, source, kind, payload FROM pending "
                "WHERE next_try_at <= ? ORDER BY id LIMIT ?",
                (now, limit),
            ).fetchall()
    return [(int(r[0]), r[1], r[2], r[3]) for r in rows]


def ack(ids: list[int]) -> int:
    """حذف بعد نجاح الإدراج."""
    if not ids:
        return 0
    with conn() as c:
        c.executemany("DELETE FROM pending WHERE id = ?", [(i,) for i in ids])
    return len(ids)


def nack(item_id: int, error: str, max_attempts: int = 5) -> str:
    """فشل: زيادة المحاولات وتأجيل. يعيد 'retry' أو 'dead'."""
    with conn() as c:
        row = c.execute(
            "SELECT source, kind, payload, created_at, attempts FROM pending WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return "missing"

        attempts = int(row[4]) + 1
        if attempts >= max_attempts:
            c.execute(
                "INSERT INTO dead (source, kind, payload, created_at, failed_at, attempts, last_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3], _now(), attempts, error[:1000]),
            )
            c.execute("DELETE FROM pending WHERE id = ?", (item_id,))
            return "dead"

        # backoff أسّي: 2^n دقيقة، بحد 60
        delay_min = min(2**attempts, 60)
        from datetime import timedelta

        nxt = (datetime.now(UTC) + timedelta(minutes=delay_min)).isoformat()
        c.execute(
            "UPDATE pending SET attempts = ?, last_error = ?, next_try_at = ? WHERE id = ?",
            (attempts, error[:1000], nxt, item_id),
        )
        return "retry"


def stats() -> dict[str, Any]:
    with conn() as c:
        pending = c.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        dead = c.execute("SELECT COUNT(*) FROM dead").fetchone()[0]
        by_source = c.execute(
            "SELECT source, COUNT(*) FROM pending GROUP BY source"
        ).fetchall()
        oldest = c.execute("SELECT MIN(created_at) FROM pending").fetchone()[0]
    return {
        "pending": pending,
        "dead": dead,
        "by_source": {r[0]: r[1] for r in by_source},
        "oldest": oldest,
    }


def heartbeat(key: str, value: str = "") -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO heartbeat (key, value, ts) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, ts = excluded.ts",
            (key, value, _now()),
        )


def get_heartbeat(key: str) -> dict[str, str] | None:
    with conn() as c:
        r = c.execute("SELECT value, ts FROM heartbeat WHERE key = ?", (key,)).fetchone()
    return {"value": r[0], "ts": r[1]} if r else None
