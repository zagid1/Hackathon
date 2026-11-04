"""И1 Концентрация (уровень служащего).

share_top = max_s Σprice(e, s) / Σprice(e) по контрактам, где e — ответственный за закупку.
Сигнал, если share_top > P90 коллег в группе (function_code, год) и у служащего >= min_decisions контрактов.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .base import Context, Signal, pct, percentile

CODE = "I1"


def compute(ctx: Context) -> list[Signal]:
    icfg = ctx.icfg
    min_n, q = icfg["min_decisions"], icfg["percentile_high"]

    per: dict[tuple[int, int], dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for c in ctx.contracts.values():
        p = ctx.procurements[c["procurement_id"]]
        per[(p["responsible"], p["year"])][c["supplier"]].append(c["price"])

    stats = {}
    groups: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    for (e, year), by_sup in sorted(per.items()):
        n = sum(len(v) for v in by_sup.values())
        if n < min_n:
            continue
        sums = {s: math.fsum(v) for s, v in by_sup.items()}
        total = math.fsum(sums.values())
        top = min(sums, key=lambda s: (-sums[s], s))
        stats[(e, year)] = (sums[top] / total, top, len(by_sup[top]), n)
        groups[(ctx.employees[e]["function_code"], year)].append((e, year))

    out = []
    for (fc, year), members in sorted(groups.items()):
        for e, y in members:
            share, top, n_top, n = stats[(e, y)]
            thr = percentile([stats[m][0] for m in members if m != (e, y)], q)
            if thr is None or share <= thr:
                continue
            pids = sorted(c["procurement_id"] for c in ctx.contracts.values()
                          if c["supplier"] == top and ctx.procurements[c["procurement_id"]]["responsible"] == e
                          and ctx.procurements[c["procurement_id"]]["year"] == y)
            evidence = [f for pid in pids for f in ctx.protocol_fragments(pid, top, last=True)][:5]
            out.append(Signal(
                CODE, "employee", e, e, round(share, 4), round(thr, 4), f"{fc}/{year}",
                f"{pct(share)} стоимости контрактов служащего в {year} г. ({n_top} из {n}) — у {ctx.orgs[top]}; "
                f"у коллег по функции {fc} P{q} = {pct(thr)}.",
                evidence))
    return out
