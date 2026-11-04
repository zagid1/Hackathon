"""Создание SQLite-БД из Dataset и хэши для проверки детерминированности.

* file_sha256 — побайтный хэш файла. Совпадает при одинаковом seed в одном окружении
  (одна и та же версия библиотеки SQLite пишется в заголовок файла).
* content_hash — хэш содержимого всех таблиц (не зависит от версии SQLite и ОС); его же
  удобно использовать на Этапе 2 для проверки «два прогона -> одинаковая таблица signals».
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .entities import Dataset

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(schema_sql())


def write_dataset(dataset: Dataset, db_path: Path) -> None:
    """Пишет набор данных в новый файл БД (через временный файл, атомарно)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".tmp")
    for p in (tmp, Path(str(tmp) + "-journal")):
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(tmp)
    try:
        create_schema(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        for model, rows in dataset.tables():
            if not rows:
                continue
            cols = model.columns()
            sql = f"INSERT INTO {model.TABLE} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            conn.executemany(sql, (r.to_row() for r in rows))
        conn.commit()
        bad = conn.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise ValueError(f"нарушены внешние ключи: {bad[:5]}")
    finally:
        conn.close()
    os.replace(tmp, db_path)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def content_hash(db_path: Path, tables: Optional[Iterable[str]] = None) -> str:
    """SHA-256 содержимого таблиц: имена колонок + строки, упорядоченные по всем колонкам."""
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        h = hashlib.sha256()
        for table in sorted(tables) if tables is not None else table_names(conn):
            cur = conn.execute(f"SELECT * FROM {table} ORDER BY " + ", ".join(
                str(i + 1) for i in range(len(conn.execute(f"PRAGMA table_info({table})").fetchall()))))
            cols = [d[0] for d in cur.description]
            h.update(json.dumps([table, cols], ensure_ascii=False).encode("utf-8"))
            for row in cur:
                h.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
                h.update(b"\n")
        return h.hexdigest()
    finally:
        conn.close()
