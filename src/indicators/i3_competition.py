"""И3 Конкуренция (уровень служащего + закупки).

Служащий (группа function_code, год; >= min_decisions конкурентных закупок с заявками):
  * single_share — доля конкурентных закупок с единственной заявкой; сигнал, если > P90 коллег;
  * margin — средний запас срока подачи заявок сверх законодательного минимума (дни);
    сигнал, если < P10 коллег.
Закупка (только у служащих с сигналом): единственная заявка и запас срока <= P10 по группе
(способ закупки, год). Нестрогое «<=» — потому что срок дискретен (дни) и P10 часто равен 0.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from src.law import legal_min_days

from .base import Context, Signal, cap_first, mean, pct, percentile

CODE = "I3"


def _margin(p: dict) -> int:
    days = (dt.date.fromisoformat(p["deadline_at"]) - dt.date.fromisoformat(p["published_at"])).days
    return days - legal_min_days(p["method"], int(round(p["nmck"] * 100)))


def _days(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " дн."


def compute(ctx: Context) -> list[Signal]:
    icfg = ctx.icfg
    min_n, q_hi, q_lo = icfg["min_decisions"], icfg["percentile_high"], icfg["percentile_low"]

    comp = [p for p in ctx.procurements.values() if p["deadline_at"] and ctx.n_bids(p["id"]) > 0]
    by_emp: dict[tuple[int, int], list[dict]] = defaultdict(list)
    by_method: dict[tuple[str, int], list[int]] = defaultdict(list)
    for p in comp:
        by_emp[(p["responsible"], p["year"])].append(p)
        by_method[(p["method"], p["year"])].append(_margin(p))
    method_p10 = {k: percentile(v, q_lo) for k, v in by_method.items()}

    stats = {}
    groups: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for (e, year), ps in sorted(by_emp.items()):
        if len(ps) < min_n:
            continue
        single = sum(1 for p in ps if ctx.n_bids(p["id"]) == 1)
        stats[(e, year)] = (single / len(ps), mean([_margin(p) for p in ps]), single, len(ps))
        groups[(ctx.employees[e]["function_code"], year)].append((e, year))

    out = []
    for (fc, year), members in sorted(groups.items()):
        for key in members:
            e = key[0]
            share, margin, single, n = stats[key]
            others = [stats[m] for m in members if m != key]
            thr_share = percentile([s[0] for s in others], q_hi)
            thr_margin = percentile([s[1] for s in others], q_lo)
            by_share = thr_share is not None and share > thr_share
            by_margin = thr_margin is not None and margin < thr_margin
            if not (by_share or by_margin):
                continue
            parts = []
            if by_share:
                parts.append(f"{single} из {n} конкурентных закупок {year} г. — с единственной заявкой "
                             f"({pct(share)}; у коллег по функции {fc} P{q_hi} = {pct(thr_share)})")
            if by_margin:
                parts.append(f"средний запас срока подачи заявок сверх законодательного минимума — {_days(margin)} "
                             f"(у коллег P{q_lo} = {_days(thr_margin)})")
            flagged = []
            for p in sorted(by_emp[key], key=lambda x: x["id"]):
                thr = method_p10[(p["method"], p["year"])]
                if ctx.n_bids(p["id"]) == 1 and _margin(p) <= thr:
                    flagged.append((p, thr))
            ev = [f for p, _ in flagged for f in ctx.protocol_fragments(p["id"], last=True)]
            value, threshold = (share, thr_share) if by_share else (margin, thr_margin)
            out.append(Signal(CODE, "employee", e, e, round(value, 4), round(threshold, 4), f"{fc}/{year}",
                              cap_first("; ".join(parts)) + ".", ev[:5]))
            for p, thr in flagged:
                m = _margin(p)
                out.append(Signal(
                    CODE, "procurement", p["id"], e, float(m), float(thr), f"{p['method']}/{p['year']}",
                    ("Единственная заявка; срок подачи заявок равен законодательному минимуму "
                     if m == 0 else f"Единственная заявка; срок подачи заявок лишь на {m} дн. больше законодательного минимума ")
                    +
                    f"(P{q_lo} запаса срока по группе «{p['method']}, {p['year']}» = {thr:g} дн.). "
                    f"Ответственный систематически получает такие закупки.",
                    ctx.protocol_fragments(p["id"], last=True)))
    return out
