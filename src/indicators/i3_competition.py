"""И3 Конкуренция (уровень служащего + закупки).

Служащий (группа function_code, год; >= min_decisions конкурентных закупок с заявками):
  * excess — доля закупок с единственной заявкой минус ожидаемая доля для рынков этих закупок
    (по ОКПД2-2 и году, без самого служащего). Узкие рынки, где одна заявка — норма, не дают сигнала.
    Сигнал, если excess > P90 коллег, excess >= i3_min_excess и вероятность получить столько
    единственных заявок случайно (распределение Пуассона–Бернулли по рыночным долям) <= i3_max_p;
  * margin — средний запас срока подачи заявок сверх законодательного минимума (дни);
    сигнал, если < P10 коллег и отстаёт от среднего коллег не меньше чем на i3_min_deadline_gap дней.
Минимальный эффект и проверка случайности нужны потому, что перцентильный порог по ~30 коллегам
всегда помечает 2–3 человек даже при отсутствии нарушений.
Закупка (только у служащих с сигналом): единственная заявка и запас срока <= P10 по группе
(способ закупки, год). Нестрогое «<=» — потому что срок дискретен (дни) и P10 часто равен 0.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from src.law import legal_min_days

from .base import Context, Signal, cap_first, mean, pct, percentile

CODE = "I3"


def _margin(p: dict) -> int:
    days = (dt.date.fromisoformat(p["deadline_at"]) - dt.date.fromisoformat(p["published_at"])).days
    return days - legal_min_days(p["method"], int(round(p["nmck"] * 100)))


def tail_probability(probs: list[float], k: int) -> float:
    """P(X >= k) для суммы независимых бернуллиевских величин с вероятностями probs (точно, DP)."""
    dist = [1.0]
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for i, v in enumerate(dist):
            nxt[i] += v * (1 - p)
            nxt[i + 1] += v * p
        dist = nxt
    return min(1.0, math.fsum(dist[k:]))


def _pp(x: float) -> str:
    sign = "+" if x >= 0 else "−"
    return f"{sign}{abs(x) * 100:.0f} п.п."


def _days(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + " дн."


def compute(ctx: Context) -> list[Signal]:
    icfg = ctx.icfg
    min_n, q_hi, q_lo = icfg["min_decisions"], icfg["percentile_high"], icfg["percentile_low"]
    min_excess, max_p, min_gap = icfg["i3_min_excess"], icfg["i3_max_p"], icfg["i3_min_deadline_gap"]

    comp = [p for p in ctx.procurements.values() if p["deadline_at"] and ctx.n_bids(p["id"]) > 0]
    by_emp: dict[tuple[int, int], list[dict]] = defaultdict(list)
    by_method: dict[tuple[str, int], list[int]] = defaultdict(list)
    market: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)   # (рынок, год) -> [(служащий, 1/0)]
    for p in comp:
        by_emp[(p["responsible"], p["year"])].append(p)
        by_method[(p["method"], p["year"])].append(_margin(p))
        market[(p["okpd2"][:2], p["year"])].append((p["responsible"], int(ctx.n_bids(p["id"]) == 1)))
    method_p10 = {k: percentile(v, q_lo) for k, v in by_method.items()}

    def expected(p: dict, e: int) -> float:
        others = [x for emp, x in market[(p["okpd2"][:2], p["year"])] if emp != e]
        if not others:
            others = [x for (m, y), v in sorted(market.items()) if y == p["year"] for emp, x in v if emp != e]
        return sum(others) / len(others)

    stats = {}
    groups: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for (e, year), ps in sorted(by_emp.items()):
        if len(ps) < min_n:
            continue
        single = sum(1 for p in ps if ctx.n_bids(p["id"]) == 1)
        probs = [expected(p, e) for p in ps]
        exp_share = math.fsum(probs) / len(ps)
        stats[(e, year)] = {"share": single / len(ps), "expected": exp_share, "excess": single / len(ps) - exp_share,
                            "p": tail_probability(probs, single), "margin": mean([_margin(p) for p in ps]),
                            "single": single, "n": len(ps)}
        groups[(ctx.employees[e]["function_code"], year)].append((e, year))

    out = []
    for (fc, year), members in sorted(groups.items()):
        for key in members:
            e = key[0]
            st = stats[key]
            others = [stats[m] for m in members if m != key]
            thr_excess = percentile([s["excess"] for s in others], q_hi)
            thr_margin = percentile([s["margin"] for s in others], q_lo)
            peers_margin = mean([s["margin"] for s in others]) if others else None
            by_share = (thr_excess is not None and st["excess"] > thr_excess and st["excess"] >= min_excess
                        and st["p"] <= max_p)
            by_margin = (thr_margin is not None and st["margin"] < thr_margin
                         and peers_margin - st["margin"] >= min_gap)
            if not (by_share or by_margin):
                continue
            parts = []
            if by_share:
                parts.append(f"{st['single']} из {st['n']} конкурентных закупок {year} г. — с единственной заявкой "
                             f"({pct(st['share'])}); ожидаемо для рынков этих закупок — {pct(st['expected'])} "
                             f"(превышение {_pp(st['excess'])}; у коллег по функции {fc} P{q_hi} превышения = "
                             f"{_pp(thr_excess)}; вероятность получить столько случайно — {pct(st['p'], 2)})")
            if by_margin:
                parts.append(f"средний запас срока подачи заявок сверх законодательного минимума — "
                             f"{_days(st['margin'])} (у коллег в среднем {_days(peers_margin)}, P{q_lo} = "
                             f"{_days(thr_margin)})")
            flagged = []
            for p in sorted(by_emp[key], key=lambda x: x["id"]):
                thr = method_p10[(p["method"], p["year"])]
                if ctx.n_bids(p["id"]) == 1 and _margin(p) <= thr:
                    flagged.append((p, thr))
            ev = [f for p, _ in flagged for f in ctx.protocol_fragments(p["id"], last=True)]
            value, threshold = (st["excess"], thr_excess) if by_share else (st["margin"], thr_margin)
            out.append(Signal(CODE, "employee", e, e, round(value, 4), round(threshold, 4),
                              f"{fc}/{year}" + (", с поправкой на рынок (ОКПД2)" if by_share else ""),
                              cap_first("; ".join(parts)) + ".", ev[:5]))
            for p, thr in flagged:
                m = _margin(p)
                lead = ("Единственная заявка; срок подачи заявок равен законодательному минимуму " if m == 0 else
                        f"Единственная заявка; срок подачи заявок лишь на {m} дн. больше законодательного минимума ")
                out.append(Signal(
                    CODE, "procurement", p["id"], e, float(m), float(thr), f"{p['method']}/{p['year']}",
                    lead + f"(P{q_lo} запаса срока по группе «{p['method']}, {p['year']}» = {thr:g} дн.). "
                    "Ответственный систематически получает такие закупки.",
                    ctx.protocol_fragments(p["id"], last=True)))
    return out
