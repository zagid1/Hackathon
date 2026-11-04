"""Таблица метрик для паспорта (PLAN.md, раздел 11): `python -m src.evaluation.report [--full]`.

* Сигналы: recall по схемам, precision по индикаторам, precision@50, доля «чистых» контрактов с сигналом —
  на seed 42 (на нём подбирались правила) и на отложенных seed 1–5 (при подборе не смотрели).
* Распознавание: F1 по типам на корпусе генератора; на документах в стиле реальных — до и после доработки
  парсеров; на слепом отложенном наборе.
* Детерминизм: два прогона -> одинаковые хэши БД и сигналов.
* Время: генерация, распознавание, индикаторы (--full меряет и генерацию DOCX + распознавание корпуса).
Пишет reports/metrics.md и reports/metrics.json.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings
from src.generator.run import build

from .extraction_eval import HANDWRITTEN, evaluate, evaluate_handwritten
from .signals_eval import evaluate as evaluate_signals

DEV_SEED = 42
HOLDOUT_SEEDS = (1, 2, 3, 4, 5)
HOLDOUT_TEXTS = ROOT / "tests" / "fixtures" / "handwritten_holdout.json"
# Метрики на документах в стиле реальных до доработки парсеров (зафиксированы при первом прогоне, Этап 4).
# Слепой набор: результат ПЕРВОГО прогона (до знакомства с документами), зафиксирован. После него добавлена
# поддержка индивидуальных предпринимателей — текущие цифры по набору уже не слепые.
HOLDOUT_FIRST_RUN = {"BID": 0.800, "INN": 1.000, "MONEY": 1.000, "ORDER_META": 1.000, "ORG": 0.889, "PERSON": 0.968,
                     "WINNER": 1.000}
HANDWRITTEN_BEFORE = {"PERSON": 0.700, "ORG": 0.600, "INN": 1.000, "MONEY": 0.900, "BID": 0.571, "WINNER": 0.500,
                      "ORDER_META": 1.000}


def seed_run(cfg: dict, seed: int, workdir: Path) -> dict:
    from src.indicators.run import run as signals_run

    c = {**cfg, "seed": seed}
    t0 = time.perf_counter()
    summary = build(c, workdir / f"seed{seed}", render_docs=False)
    t_data = time.perf_counter() - t0
    t0 = time.perf_counter()
    sig = signals_run(Path(summary["db_path"]), c)
    t_sig = time.perf_counter() - t0
    conn = sqlite3.connect(summary["db_path"])
    try:
        ev = evaluate_signals(conn, c)
    finally:
        conn.close()
    return {"seed": seed, "eval": ev, "content_sha256": summary["content_sha256"],
            "signals_sha256": sig["signals_sha256"], "seconds_data": t_data, "seconds_signals": t_sig}


def _recall_key(x: dict) -> str:
    return f"{x['scheme']} → {x['indicator']} ({x['level']})"


def _prec_key(x: dict) -> str:
    return f"{x['indicator']} ({x['level']})"


def build_report(full: bool = False) -> dict:
    cfg = load_settings()
    data_dir = ROOT / cfg["paths"]["data_dir"]
    report: dict = {"generated_from": "config/settings.yaml", "dev_seed": DEV_SEED, "holdout_seeds": list(HOLDOUT_SEEDS)}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        runs = [seed_run(cfg, s, tmp) for s in (DEV_SEED, *HOLDOUT_SEEDS)]
        again = seed_run(cfg, DEV_SEED, tmp / "again")
        report["determinism"] = {
            "content_equal": again["content_sha256"] == runs[0]["content_sha256"],
            "signals_equal": again["signals_sha256"] == runs[0]["signals_sha256"],
            "content_sha256": runs[0]["content_sha256"], "signals_sha256": runs[0]["signals_sha256"]}
        report["seconds"] = {"data_no_docs": round(runs[0]["seconds_data"], 1),
                             "signals": round(runs[0]["seconds_signals"], 2)}
        if full:
            from src.extraction.pipeline import run as extract_run
            t0 = time.perf_counter()
            build(cfg, tmp / "full", render_docs=True)
            report["seconds"]["data_with_docs"] = round(time.perf_counter() - t0, 1)
            t0 = time.perf_counter()
            res = extract_run(sorted((tmp / "full" / "docs").glob("*.docx")), tmp / "full" / "extracted")
            report["seconds"]["extract"] = round(time.perf_counter() - t0, 1)
            report["seconds"]["extract_docs"] = res["processed"]

    dev, holdout = runs[0], runs[1:]
    rows = {}
    for kind, getter, key in (("recall", lambda e: e["recall"], _recall_key),
                              ("precision", lambda e: e["precision"], _prec_key)):
        for x in getter(dev["eval"]):
            k = key(x)
            vals = []
            for h in holdout:
                match = [y for y in getter(h["eval"]) if key(y) == k]
                vals.append(match[0][kind] if match else (0.0 if kind == "precision" else None))
            vals = [v for v in vals if v is not None]
            rows.setdefault(kind, []).append({
                "metric": k, "dev": x[kind], "found": f"{x.get('found', x.get('true'))}/{x.get('total', x.get('signals'))}",
                "holdout_mean": round(statistics.fmean(vals), 3) if vals else None,
                "holdout_min": round(min(vals), 3) if vals else None})
    report["signals"] = rows
    report["signals_summary"] = {
        "precision_at_50": {"dev": dev["eval"]["precision_at_50"],
                            "holdout_mean": round(statistics.fmean(h["eval"]["precision_at_50"] for h in holdout), 3),
                            "holdout_min": min(h["eval"]["precision_at_50"] for h in holdout)},
        "clean_flag_rate": {"dev": dev["eval"]["clean_contracts_flag_rate"],
                            "holdout_mean": round(statistics.fmean(h["eval"]["clean_contracts_flag_rate"]
                                                                   for h in holdout), 4),
                            "holdout_max": max(h["eval"]["clean_contracts_flag_rate"] for h in holdout)}}

    extracted = data_dir / "extracted"
    if extracted.exists():
        report["extraction_corpus"] = evaluate(data_dir / cfg["paths"]["docs_subdir"], extracted)
    report["extraction_handwritten"] = {"before": HANDWRITTEN_BEFORE,
                                        "after": {k: v["f1"] for k, v in evaluate_handwritten(HANDWRITTEN)["metrics"].items()}}
    hold = evaluate_handwritten(HOLDOUT_TEXTS)
    report["extraction_holdout"] = {"first_run": HOLDOUT_FIRST_RUN,
                                    "current": {k: v["f1"] for k, v in hold["metrics"].items()},
                                    "errors": hold["errors"]}
    return report


def _fmt(x) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}".replace(".", ",")
    return str(x)


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%".replace(".", ",")


def to_markdown(r: dict) -> str:
    L = ["# Метрики прототипа", "",
         "> Все метрики — на **синтетических** данных с внедрёнными схемами (ground truth известен). "
         "Это проверка работоспособности, а не оценка на реальных данных.", "",
         f"Правила и пороги подбирались на seed {r['dev_seed']}; seed {', '.join(map(str, r['holdout_seeds']))} — "
         "отложенные (при подборе не смотрели).", "",
         "## Сигналы: recall по внедрённым схемам", "",
         "| Схема → индикатор | seed 42 | найдено | отложенные: среднее | отложенные: минимум |", "|---|---|---|---|---|"]
    for x in r["signals"]["recall"]:
        L.append(f"| {x['metric']} | {_fmt(x['dev'])} | {x['found']} | {_fmt(x['holdout_mean'])} | {_fmt(x['holdout_min'])} |")
    L += ["", "## Сигналы: precision по индикаторам", "",
          "| Индикатор | seed 42 | верных / всего | отложенные: среднее | отложенные: минимум |", "|---|---|---|---|---|"]
    for x in r["signals"]["precision"]:
        L.append(f"| {x['metric']} | {_fmt(x['dev'])} | {x['found']} | {_fmt(x['holdout_mean'])} | {_fmt(x['holdout_min'])} |")
    s = r["signals_summary"]
    L += ["", f"* precision@50: seed 42 — {_fmt(s['precision_at_50']['dev'])}; отложенные — среднее "
          f"{_fmt(s['precision_at_50']['holdout_mean'])}, минимум {_fmt(s['precision_at_50']['holdout_min'])}.",
          f"* Доля «чистых» контрактов хотя бы с одним сигналом: seed 42 — {_pct(s['clean_flag_rate']['dev'])}; "
          f"отложенные — среднее {_pct(s['clean_flag_rate']['holdout_mean'])}, максимум "
          f"{_pct(s['clean_flag_rate']['holdout_max'])}.", ""]
    if "extraction_corpus" in r:
        ec = r["extraction_corpus"]
        L += ["## Распознавание документов", "",
              f"Корпус генератора: {ec['documents']} документов (3 шаблона на тип — парсеры их видели).", "",
              "| Тип | span-F1 | strict-F1 |", "|---|---|---|"]
        for t, m in ec["entities_strict"].items():
            L.append(f"| {t} | {_fmt(ec['entities_span'][t]['f1'])} | {_fmt(m['f1'])} |")
        for t, m in ec["relations"].items():
            L.append(f"| связь {t} | — | {_fmt(m['f1'])} |")
        L += ["", f"Доля ИНН с верной контрольной суммой: {_fmt(ec['inn_valid_checksum_share'])}.", ""]
    hw, ho = r["extraction_handwritten"], r["extraction_holdout"]
    keys = sorted(set(hw["before"]) | set(hw["after"]) | set(ho["first_run"]) | set(ho["current"]))
    L += ["Документы в стиле реальных протоколов ЕИС и приказов, написанные вручную (чужой формат):", "",
          "| Тип | набор А (4 док.): до доработки | набор А: после* | набор Б (3 док.): слепой прогон | набор Б: сейчас* |",
          "|---|---|---|---|---|"]
    for k in keys:
        L.append(f"| {k} | {_fmt(hw['before'].get(k))} | {_fmt(hw['after'].get(k))} | "
                 f"{_fmt(ho['first_run'].get(k))} | {_fmt(ho['current'].get(k))} |")
    L += ["", "\\* после доработки парсеров по этим же документам — оценка оптимистична. Честная оценка — "
          "«набор А: до доработки» и «набор Б: слепой прогон». На слепом прогоне не распознавался индивидуальный "
          "предприниматель как участник (его ФИО попадало в состав комиссии); после этого поддержка ИП добавлена.", ""]
    if ho["errors"]:
        L += ["Текущие ошибки на наборе Б:", ""]
        for e in ho["errors"]:
            for k, v in e.items():
                if k != "id":
                    L.append(f"* {e['id']}, {k}: ожидалось {json.dumps(v['expected'], ensure_ascii=False)}, "
                             f"получено {json.dumps(v['predicted'], ensure_ascii=False)}")
        L.append("")
    d, t = r["determinism"], r["seconds"]
    L += ["## Детерминизм и время", "",
          f"* Два прогона генератора и индикаторов: БД {'совпадает' if d['content_equal'] else 'НЕ совпадает'}, "
          f"сигналы {'совпадают' if d['signals_equal'] else 'НЕ совпадают'} "
          f"(content_sha256 `{d['content_sha256'][:12]}…`, signals_sha256 `{d['signals_sha256'][:12]}…`).",
          f"* Генерация 2000 закупок без DOCX: {t['data_no_docs']} с; индикаторы: {t['signals']} с."]
    if "data_with_docs" in t:
        L.append(f"* Генерация с DOCX: {t['data_with_docs']} с; распознавание {t['extract_docs']} документов: "
                 f"{t['extract']} с.")
    return "\n".join(L) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Таблица метрик для паспорта")
    ap.add_argument("--full", action="store_true", help="мерить и генерацию DOCX, и распознавание корпуса")
    args = ap.parse_args(argv)
    r = build_report(full=args.full)
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    md = to_markdown(r)
    (out / "metrics.md").write_text(md, encoding="utf-8", newline="\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
