"""F1 распознавания по типам сущностей и связей: `python -m src.evaluation.extraction_eval`.

Эталон — JSON-разметка генератора (data/synthetic/docs/*.json), предсказание — результат
`make extract` (data/synthetic/extracted/*.json).

* span-F1: совпали страница, границы и тип;
* strict-F1: плюс совпала нормализованная форма (если она есть в эталоне);
* связи: BID — (организация, сумма), WINNER — организация, MEMBER — (лицо, роль), multiset-сравнение.
Корпус синтетический (3 шаблона на тип документа) — на реальных документах качество ниже;
«живых» размеченных документов пока нет.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings

ENTITY_TYPES = ("PERSON", "ORG", "INN", "OGRN", "MONEY")


def _rel_key(r: dict) -> tuple:
    if r["type"] == "BID":
        return ("BID", r["from"], r["to"])
    if r["type"] == "MEMBER":
        return ("MEMBER", r["from"], r.get("role"))
    return (r["type"], r["from"])


def _f1(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def evaluate(gold_dir: Path, pred_dir: Path) -> dict:
    span = defaultdict(Counter)
    strict = defaultdict(Counter)
    rels = defaultdict(Counter)
    inn_total = inn_valid = docs = missing = 0
    by_doc_type = Counter()
    for gpath in sorted(Path(gold_dir).glob("*.json")):
        ppath = Path(pred_dir) / gpath.name
        if not ppath.exists():
            missing += 1
            continue
        gold = json.loads(gpath.read_text(encoding="utf-8"))
        pred = json.loads(ppath.read_text(encoding="utf-8"))
        docs += 1
        by_doc_type[gold["doc_type"]] += 1
        g_ents = {(e["page"], tuple(e["span"]), e["type"]): e for e in gold["entities"] if e["type"] in ENTITY_TYPES}
        p_ents = {(e["page"], tuple(e["span"]), e["type"]): e for e in pred["entities"] if e["type"] in ENTITY_TYPES}
        for k, g in g_ents.items():
            p = p_ents.get(k)
            t = k[2]
            if p is None:
                span[t]["fn"] += 1
                strict[t]["fn"] += 1
                continue
            span[t]["tp"] += 1
            if g.get("normalized") is None or p.get("normalized") == g.get("normalized"):
                strict[t]["tp"] += 1
            else:
                strict[t]["fn"] += 1
                strict[t]["fp"] += 1
        for k in p_ents.keys() - g_ents.keys():
            span[k[2]]["fp"] += 1
            strict[k[2]]["fp"] += 1
        for e in pred["entities"]:
            if e["type"] == "INN":
                inn_total += 1
                inn_valid += bool(e.get("valid_checksum"))
        g_rel = Counter(_rel_key(r) for r in gold["relations"] if r["type"] in ("BID", "WINNER", "MEMBER"))
        p_rel = Counter(_rel_key(r) for r in pred["relations"] if r["type"] in ("BID", "WINNER", "MEMBER"))
        for t in ("BID", "WINNER", "MEMBER"):
            g_t = Counter({k: v for k, v in g_rel.items() if k[0] == t})
            p_t = Counter({k: v for k, v in p_rel.items() if k[0] == t})
            rels[t]["tp"] += sum((g_t & p_t).values())
            rels[t]["fp"] += sum((p_t - g_t).values())
            rels[t]["fn"] += sum((g_t - p_t).values())

    def table(d):
        return {t: _f1(d[t]["tp"], d[t]["fp"], d[t]["fn"]) for t in sorted(d)}

    return {"note": "Синтетический корпус генератора (3 шаблона на тип документа); живых размеченных документов нет.",
            "documents": docs, "by_doc_type": dict(by_doc_type), "missing_predictions": missing,
            "entities_span": table(span), "entities_strict": table(strict), "relations": table(rels),
            "inn_valid_checksum_share": round(inn_valid / inn_total, 4) if inn_total else None}


HANDWRITTEN = ROOT / "tests" / "fixtures" / "handwritten.json"


def _multiset_f1(gold: list, pred: list) -> Counter:
    g, p = Counter(map(_hashable, gold)), Counter(map(_hashable, pred))
    return Counter(tp=sum((g & p).values()), fp=sum((p - g).values()), fn=sum((g - p).values()))


def _hashable(x):
    return tuple(_hashable(i) for i in x) if isinstance(x, list) else x


def evaluate_handwritten(path: Path = HANDWRITTEN) -> dict:
    """Оценка на вручную написанных документах в стиле реальных (чужой формат, не шаблоны генератора).
    Сравнение по нормализованным значениям (без позиций): PERSON — (ФИО, роль), ORG, INN, MONEY, BID, WINNER."""
    from src.extraction.order import parse_order
    from src.extraction.protocol import parse_protocol

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    totals: dict[str, Counter] = defaultdict(Counter)
    details = []
    for doc in data["documents"]:
        res = parse_protocol(doc["pages"]) if doc["doc_type"] == "PROTOCOL" else parse_order(doc["pages"])
        ents = res["entities"]
        pred = {
            "PERSON": [[e["normalized"], e.get("role")] for e in ents if e["type"] == "PERSON"],
            "ORG": [e["normalized"] for e in ents if e["type"] == "ORG"],
            "INN": [e["value"] for e in ents if e["type"] == "INN"],
            "MONEY": [e["normalized"] for e in ents if e["type"] == "MONEY"],
            "BID": [[r["from"].removeprefix("ORG:"), float(r["to"].split(":")[1])] for r in res["relations"]
                    if r["type"] == "BID"],
            "WINNER": [r["from"].removeprefix("ORG:") for r in res["relations"] if r["type"] == "WINNER"],
        }
        doc_res = {"id": doc["id"]}
        for key, gold in doc["expected"].items():
            if key == "ORDER":
                ok = all(res.get(k) == v for k, v in gold.items())
                totals["ORDER_META"].update(tp=int(ok), fn=int(not ok), fp=int(not ok))
                if not ok:
                    doc_res["ORDER_META"] = {"expected": gold, "predicted": {k: res.get(k) for k in gold}}
                continue
            c = _multiset_f1(gold, pred[key])
            totals[key].update(c)
            if c["fp"] or c["fn"]:
                doc_res[key] = {"expected": gold, "predicted": pred[key]}
        details.append(doc_res)
    return {"documents": len(data["documents"]),
            "metrics": {k: _f1(v["tp"], v["fp"], v["fn"]) for k, v in sorted(totals.items())},
            "errors": [d for d in details if len(d) > 1]}


def format_report(r: dict) -> str:
    lines = [r["note"], f"Документов: {r['documents']} {r['by_doc_type']}", "",
             f"{'Тип':<8}{'span-F1':>10}{'strict-F1':>11}{'P':>8}{'R':>8}"]
    for t, s in r["entities_strict"].items():
        lines.append(f"{t:<8}{r['entities_span'][t]['f1']:>10.3f}{s['f1']:>11.3f}{s['precision']:>8.3f}{s['recall']:>8.3f}")
    lines += ["", "Связи:"]
    for t, s in r["relations"].items():
        lines.append(f"  {t:<8} F1 = {s['f1']:.3f} (P = {s['precision']:.3f}, R = {s['recall']:.3f})")
    lines.append(f"\nДоля ИНН с верной контрольной суммой: {r['inn_valid_checksum_share']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="F1 распознавания")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    args = ap.parse_args(argv)
    cfg = load_settings(args.config)
    data = ROOT / cfg["paths"]["data_dir"]
    report = evaluate(data / cfg["paths"]["docs_subdir"], data / "extracted")
    report["handwritten"] = evaluate_handwritten()
    (data / "extraction_eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    sys.stdout.write(format_report(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
