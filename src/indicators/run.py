"""Прогон всех индикаторов -> таблица signals: `python -m src.indicators.run [--db PATH]`.

* Сигналы сортируются по (индикатор, тип объекта, объект, служащий, группа) и нумеруются заново.
* Решение проверяющего (status, reviewer_comment) при повторном прогоне сохраняется
  по ключу (indicator, object_type, object_id, employee_id, peer_group).
* signals_hash — хэш вычисляемых колонок (без статуса и комментария) для проверки
  «два прогона -> одинаковый результат».
* Итог по решению — список сработавших индикаторов с весами из конфига (decision_summary);
  единого «индекса человека» нет.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings

from . import i1_concentration, i2_affiliation, i3_competition, i4_price, i7_authority
from .base import Context, Signal, weights

INDICATORS = (i1_concentration, i2_affiliation, i3_competition, i4_price, i7_authority)
COMPUTED_COLUMNS = ("id", "indicator", "object_type", "object_id", "employee_id", "value", "threshold",
                    "peer_group", "explanation", "evidence_fragment_ids")


def compute_signals(conn: sqlite3.Connection, cfg: dict) -> list[Signal]:
    ctx = Context(conn, cfg)
    signals: list[Signal] = []
    for module in INDICATORS:
        signals += module.compute(ctx)
    signals.sort(key=Signal.sort_key)
    return signals


def _key(indicator, object_type, object_id, employee_id, peer_group) -> tuple:
    return (indicator, object_type, object_id, employee_id or 0, peer_group or "")


def write_signals(conn: sqlite3.Connection, signals: list[Signal]) -> None:
    reviews = {_key(*r[:5]): (r[5], r[6]) for r in conn.execute(
        "SELECT indicator, object_type, object_id, employee_id, peer_group, status, reviewer_comment FROM signals")}
    rows = []
    for i, s in enumerate(signals, start=1):
        status, comment = reviews.get(s.sort_key(), ("NEW", None))
        rows.append((i, s.indicator, s.object_type, s.object_id, s.employee_id, s.value, s.threshold, s.peer_group,
                     s.explanation, json.dumps(sorted(set(s.evidence))), status, comment))
    with conn:
        conn.execute("DELETE FROM signals")
        conn.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def signals_hash(conn: sqlite3.Connection) -> str:
    h = hashlib.sha256()
    for row in conn.execute(f"SELECT {', '.join(COMPUTED_COLUMNS)} FROM signals ORDER BY id"):
        h.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def decision_summary(conn: sqlite3.Connection, cfg: dict) -> dict[tuple[str, int], dict]:
    """По каждому решению (контракт/закупка) — сработавшие индикаторы и сумма их весов."""
    w = weights(cfg)
    out: dict[tuple[str, int], dict] = defaultdict(lambda: {"indicators": [], "weight": 0.0})
    for ind, ot, oid in conn.execute("SELECT DISTINCT indicator, object_type, object_id FROM signals "
                                     "WHERE object_type IN ('contract', 'procurement') ORDER BY 2, 3, 1"):
        d = out[(ot, oid)]
        d["indicators"].append(ind)
        d["weight"] = math.fsum([d["weight"], w.get(ind, 1.0)])
    return dict(out)


def employee_overview(conn: sqlite3.Connection, employee_id: int) -> tuple[int, int]:
    """«N решений с сигналами из M» по служащему (решение = контракт, где он ответственный или подписант)."""
    total = conn.execute("""SELECT count(*) FROM contracts c JOIN procurements p ON p.id = c.procurement_id
                            WHERE p.responsible_employee_id = ? OR c.signer_employee_id = ?""",
                         (employee_id, employee_id)).fetchone()[0]
    flagged = conn.execute("""SELECT count(DISTINCT c.id) FROM contracts c JOIN procurements p ON p.id = c.procurement_id
                              JOIN signals s ON (s.object_type = 'contract' AND s.object_id = c.id)
                                             OR (s.object_type = 'procurement' AND s.object_id = p.id)
                              WHERE p.responsible_employee_id = ? OR c.signer_employee_id = ?""",
                           (employee_id, employee_id)).fetchone()[0]
    return flagged, total


def run(db_path: Path, cfg: dict) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        signals = compute_signals(conn, cfg)
        write_signals(conn, signals)
        return {"db_path": str(db_path), "signals": len(signals),
                "by_indicator": dict(sorted(Counter(f"{s.indicator}/{s.object_type}" for s in signals).items())),
                "signals_sha256": signals_hash(conn)}
    finally:
        conn.close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Прогон индикаторов риска")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--db", type=Path, default=None)
    args = ap.parse_args(argv)
    cfg = load_settings(args.config)
    db = args.db or ROOT / cfg["paths"]["data_dir"] / cfg["paths"]["db_file"]
    t0 = time.perf_counter()
    summary = run(db, cfg)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
