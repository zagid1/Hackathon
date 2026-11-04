"""Оценка сигналов по внедрённым схемам (ground truth): `python -m src.evaluation.signals_eval`.

Соответствие «схема -> индикатор и уровень объекта» (PLAN.md, раздел 6):
  S1 -> И2 по контрактам (дополнительно И1 по служащим S1);  S2 -> И1 по служащим;
  S3 -> И3 по служащим и по закупкам;  S4 -> И4 по контрактам;  S5 -> И7 по контрактам.
Сигнал считается верным, если его объект входит в ground truth схем, которые должен находить индикатор.

Метрики (на синтетике!):
  * recall по каждой схеме;
  * precision по каждому индикатору (и уровню объекта);
  * precision@K по всем сигналам, упорядоченным по весу индикатора и силе превышения порога;
  * доля «чистых» контрактов хотя бы с одним сигналом (уровень ложных срабатываний).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings
from src.indicators.base import weights

# индикатор/уровень -> множества GT, попадание в которые считается верным сигналом
TARGETS = {
    ("I1", "employee"): [("S2", "employee"), ("S1", "employee*")],
    ("I2", "contract"): [("S1", "contract")],
    ("I3", "employee"): [("S3", "employee")],
    ("I3", "procurement"): [("S3", "procurement")],
    ("I4", "contract"): [("S4", "contract")],
    ("I7", "contract"): [("S5", "contract")],
}
# схема -> (индикатор, уровень, множество GT) для recall
RECALL = [
    ("S1", "I2", "contract", ("S1", "contract")),
    ("S1", "I1", "employee", ("S1", "employee*")),
    ("S2", "I1", "employee", ("S2", "employee")),
    ("S3", "I3", "employee", ("S3", "employee")),
    ("S3", "I3", "procurement", ("S3", "procurement")),
    ("S4", "I4", "contract", ("S4", "contract")),
    ("S5", "I7", "contract", ("S5", "contract")),
]


def load_truth(conn: sqlite3.Connection) -> dict[tuple[str, str], set[int]]:
    truth: dict[tuple[str, str], set[int]] = defaultdict(set)
    for scheme, ot, oid, emp in conn.execute("SELECT scheme, object_type, object_id, employee_id FROM injected_schemes"):
        truth[(scheme, ot)].add(oid)
        truth[(scheme, "employee*")].add(emp)      # служащие-участники схемы
    return truth


def strength(indicator: str, value: Optional[float], threshold: Optional[float], object_type: str) -> float:
    """Сила сигнала для ранжирования (0..1). Правила-нарушения (И2, И7) — 1; перцентильные — относительное
    превышение порога, ограниченное 1. Предварительно: уточнить на Этапе 4."""
    if indicator in ("I2", "I7") or value is None or threshold is None:
        return 1.0
    if indicator == "I3" and object_type == "procurement":
        return 0.5
    if indicator == "I4":
        return 1.0 if value >= threshold else 0.5    # рост цены — сильнее, чем малое снижение
    if indicator == "I3" and value < threshold:      # критерий «срок меньше P10»
        return min(1.0, (threshold - value) / max(threshold, 1e-9))
    return min(1.0, (value - threshold) / max(threshold, 1e-9))


def evaluate(conn: sqlite3.Connection, cfg: dict, k: int = 50) -> dict:
    truth = load_truth(conn)
    w = weights(cfg)
    signals = conn.execute("SELECT id, indicator, object_type, object_id, value, threshold FROM signals").fetchall()

    def correct(ind: str, ot: str, oid: int) -> bool:
        return any(oid in truth[t] for t in TARGETS.get((ind, ot), []))

    flagged: dict[tuple[str, str], set[int]] = defaultdict(set)
    for _, ind, ot, oid, _, _ in signals:
        flagged[(ind, ot)].add(oid)

    recall = []
    for scheme, ind, ot, gt_key in RECALL:
        gt = truth[gt_key]
        hit = len(gt & flagged[(ind, ot)])
        recall.append({"scheme": scheme, "indicator": ind, "level": ot, "found": hit, "total": len(gt),
                       "recall": round(hit / len(gt), 3) if gt else None})

    precision = []
    for (ind, ot), objs in sorted(flagged.items()):
        tp = sum(1 for o in objs if correct(ind, ot, o))
        precision.append({"indicator": ind, "level": ot, "signals": len(objs), "true": tp,
                          "precision": round(tp / len(objs), 3)})

    ranked = sorted(signals, key=lambda s: (-w.get(s[1], 1.0) * strength(s[1], s[4], s[5], s[2]), s[0]))
    top = ranked[:k]
    p_at_k = sum(1 for s in top if correct(s[1], s[2], s[3])) / len(top) if top else None

    # «чистые» контракты: не входят в GT ни одной схемы (в т.ч. через закупку S3)
    proc_of = dict(conn.execute("SELECT id, procurement_id FROM contracts"))
    gt_contracts = set().union(*(truth[(s, "contract")] for s in ("S1", "S4", "S5")))
    gt_contracts |= {c for c, p in proc_of.items() if p in truth[("S3", "procurement")]}
    clean = set(proc_of) - gt_contracts
    sig_contracts = flagged[("I2", "contract")] | flagged[("I4", "contract")] | flagged[("I7", "contract")]
    sig_contracts |= {c for c, p in proc_of.items() if p in flagged[("I3", "procurement")]}
    fp_clean = len(clean & sig_contracts)

    return {
        "note": "Метрики на синтетических данных с внедрёнными схемами (seed из dataset_meta).",
        "recall": recall,
        "precision": precision,
        f"precision_at_{k}": round(p_at_k, 3) if p_at_k is not None else None,
        "clean_contracts": len(clean),
        "clean_contracts_with_signal": fp_clean,
        "clean_contracts_flag_rate": round(fp_clean / len(clean), 4) if clean else None,
    }


def format_report(r: dict) -> str:
    lines = [r["note"], "", "Recall по схемам:"]
    for x in r["recall"]:
        lines.append(f"  {x['scheme']} -> {x['indicator']} ({x['level']:<11}) {x['found']:>3}/{x['total']:<3} "
                     f"recall = {x['recall']}")
    lines += ["", "Precision по индикаторам:"]
    for x in r["precision"]:
        lines.append(f"  {x['indicator']} ({x['level']:<11}) {x['true']:>3}/{x['signals']:<3} precision = {x['precision']}")
    pk = next(k for k in r if k.startswith("precision_at_"))
    lines += ["", f"{pk.replace('precision_at_', 'precision@')} = {r[pk]}",
              f"Чистые контракты с сигналом: {r['clean_contracts_with_signal']} из {r['clean_contracts']} "
              f"({r['clean_contracts_flag_rate']:.2%})"]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Оценка сигналов по внедрённым схемам")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--k", type=int, default=50)
    args = ap.parse_args(argv)
    cfg = load_settings(args.config)
    db = args.db or ROOT / cfg["paths"]["data_dir"] / cfg["paths"]["db_file"]
    conn = sqlite3.connect(db)
    try:
        report = evaluate(conn, cfg, args.k)
    finally:
        conn.close()
    out = Path(db).with_name("eval.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(format_report(report) + f"\n\nJSON: {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
