"""И4 Цена (уровень контракта).

drop = 1 − price / nmck; growth = Σprice_delta / price.
Сигнал, если (drop < i4_min_drop при >= 2 заявках) или growth >= i4_growth
или >= i4_min_amendments допсоглашений с ростом цены. Пороги абсолютные (законодательные/экспертные).
"""

from __future__ import annotations

import math

from .base import Context, Signal, cap_first, date_ru, pct

CODE = "I4"


def compute(ctx: Context) -> list[Signal]:
    icfg = ctx.icfg
    min_drop, max_growth, min_up = icfg["i4_min_drop"], icfg["i4_growth"], icfg["i4_min_amendments"]
    out = []
    for cid, c in sorted(ctx.contracts.items()):
        p = ctx.procurements[c["procurement_id"]]
        n = ctx.n_bids(p["id"])
        drop = 1 - c["price"] / p["nmck"]
        am = ctx.amendments.get(cid, [])
        ups = [a for a in am if a[1] > 0]
        growth = math.fsum(a[1] for a in am) / c["price"]
        r_drop = n >= 2 and drop < min_drop
        r_growth = growth >= max_growth
        r_ups = len(ups) >= min_up
        if not (r_drop or r_growth or r_ups):
            continue
        parts = []
        if r_drop:
            parts.append(f"снижение на торгах {pct(drop, 2)} при {n} заявках (порог {pct(min_drop, 1)})")
        if r_growth or r_ups:
            dates = ", ".join(date_ru(a[0]) for a in ups)
            parts.append(f"{'затем ' if r_drop else ''}{pct(growth, 1)} к цене контракта допсоглашениями "
                         f"({len(ups)} с ростом цены: {dates}; порог роста {pct(max_growth)})")
        value, thr = (growth, max_growth) if (r_growth or r_ups) else (drop, min_drop)
        out.append(Signal(CODE, "contract", cid, p["responsible"], round(value, 4), thr, "абсолютный порог",
                          cap_first("; ".join(parts)) + ".",
                          ctx.protocol_fragments(p["id"], c["supplier"])))
    return out
