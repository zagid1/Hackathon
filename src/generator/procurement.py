"""Закупки, заявки, контракты, допсоглашения (фон + экземпляры схем S1–S5).

Упрощения (синтетика, не юридическая модель): нормы сроков и лимитов — в src/law.py;
победитель — участник с наименьшей ценой; контракт подписывается не ранее 10 дней после протокола;
фоновые допсоглашения увеличивают цену не более чем на 9%, второе допсоглашение цену не увеличивает.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Optional

from src.law import QUOTATION_LIMIT_KOP, SINGLE_SUPPLIER_LIMIT_KOP, legal_min_days
from src.models.entities import Amendment, Bid, Contract, Method, Procurement

from .common import World, rub, random_date, wchoice
from .companies import affiliated_persons, orgs_in_market
from .groups import commissions_by_department, employee_members
from .org import DEPUTY_HEAD, DIRECTOR, HEAD, responsible_pool, sections_of
from .schemes import SchemePlan


REASON_TERMS = ("Изменение сроков исполнения контракта", "Изменение реквизитов сторон",
                "Уточнение графика поставки")
REASON_UP = "Увеличение объема поставки (оказания услуг) по п. 1 ч. 1 ст. 95 44-ФЗ"
REASON_DOWN = "Уменьшение объема поставки (оказания услуг) по п. 1 ч. 1 ст. 95 44-ФЗ"


@dataclass
class ProcMeta:
    """Служебные сведения о закупке, нужные документам (в БД не пишутся)."""
    market: str
    subject: str
    protocol_date: Optional[dt.date] = None
    bid_ids: list[int] = field(default_factory=list)
    contract_id: Optional[int] = None


def assign_specializations(w: World) -> None:
    """Каждый контрактный управляющий ведёт 2–4 рынка; у каждого рынка не меньше 2 специалистов."""
    rng = w.rng("specializations")
    codes = sorted(w.markets)
    weights = [w.markets[c].weight for c in codes]
    for e in sorted(x.id for x in responsible_pool(w)):
        k = rng.randint(2, 4)
        chosen: list[str] = []
        while len(chosen) < k:
            c = wchoice(rng, codes, weights)
            if c not in chosen:
                chosen.append(c)
        w.responsible_markets[e] = sorted(chosen)
    for c in codes:
        while sum(c in ms for ms in w.responsible_markets.values()) < 2:
            e = rng.choice(sorted(w.responsible_markets))
            if c not in w.responsible_markets[e]:
                w.responsible_markets[e] = sorted(w.responsible_markets[e] + [c])


def _gen_nmck(rng: random.Random, lo_rub: int, hi_rub: int) -> int:
    u = rng.random()
    return lo_rub * 100 + int((hi_rub - lo_rub) * 100 * (u * u * u))


def _pick_method(rng: random.Random, market, nmck_kop: int) -> str:
    if nmck_kop <= SINGLE_SUPPLIER_LIMIT_KOP and rng.random() < 0.55:
        return Method.SINGLE_SUPPLIER
    if rng.random() < market.tender_share:
        return Method.TENDER
    if nmck_kop <= QUOTATION_LIMIT_KOP and rng.random() < 0.25:
        return Method.QUOTATION
    return Method.AUCTION


def _weighted_sample(rng: random.Random, items: list, weights: list[float], k: int) -> list:
    items, weights = list(items), list(weights)
    out = []
    for _ in range(min(k, len(items))):
        i = rng.choices(range(len(items)), weights=weights, k=1)[0]
        out.append(items.pop(i))
        weights.pop(i)
    return out


def _price(nmck_kop: int, drop_bp: int) -> int:
    return nmck_kop * (10_000 - drop_bp) // 10_000


def build_procurements(w: World, plan: SchemePlan) -> dict[int, ProcMeta]:
    rng = w.rng("procurements")
    rs = w.rng("scheme_hooks")           # отдельный поток для решений по схемам
    g, sc, noise = w.gen, w.cfg["schemes"], w.gen["noise"]
    start, end = w.period()
    last_pub = end - dt.timedelta(days=45)
    ds = w.ds

    codes = sorted(w.markets)
    m_weights = [w.markets[c].weight for c in codes]
    activity = {e: 0.6 + rng.random() for e in sorted(w.responsible_markets)}
    specialists = {c: sorted(e for e, ms in w.responsible_markets.items() if c in ms) for c in codes}
    market_orgs = {c: sorted(orgs_in_market(w, c), key=lambda o: o.id) for c in codes}
    sections = sections_of(w)
    comm_by_dep = commissions_by_department(w)
    all_comms = sorted(gid for ids in comm_by_dep.values() for gid in ids)
    head = next(e.id for e in w.employees.values() if e.role == HEAD)
    deputies = sorted(e.id for e in w.employees.values() if e.role == DEPUTY_HEAD)
    directors = {e.department_id: e.id for e in w.employees.values() if e.role == DIRECTOR}

    # фирмы, аффилированные с родственниками служащего (для «чистого» фона)
    person_orgs: dict[int, set[int]] = {}
    for oid in w.orgs:
        for p in affiliated_persons(w, oid):
            person_orgs.setdefault(p, set()).add(oid)
    conflicted = {e: set().union(*(person_orgs.get(p, set()) for p in ps)) for e, ps in w.relatives.items()}

    meta: dict[int, ProcMeta] = {}
    bid_id = contract_id = amendment_id = 0
    s1_win, s2_target = sc["S1"]["win_share"], sc["S2"]["target_share"]

    for pid in range(1, g["procurements"] + 1):
        code = wchoice(rng, codes, m_weights)
        market = w.markets[code]
        okpd2, subject = rng.choice(market.okpd2)
        resp = wchoice(rng, specialists[code], [activity[e] for e in specialists[code]])
        unit = rng.choice(sections)
        dep = w.unit_parent[unit]
        nmck = _gen_nmck(rng, *market.nmck_rub)
        method = _pick_method(rng, market, nmck)
        competitive = method != Method.SINGLE_SUPPLIER
        published = random_date(rng, start, last_pub)

        deadline: Optional[dt.date] = None
        commission: Optional[int] = None
        if competitive:
            extra = 0 if rng.random() < noise["short_deadline_share"] else rng.randint(1, 4) + rng.randint(0, 8)
            deadline = published + dt.timedelta(days=legal_min_days(method, nmck) + extra)
            commission = rng.choice(comm_by_dep.get(dep) or all_comms)

        r = rng.random()
        signer = directors[dep] if r < 0.75 else (rng.choice(deputies) if r < 0.95 else head)
        s5 = False
        if unit in plan.s5 and rs.random() < sc["S5"]["share"]:
            signer, s5 = plan.s5[unit], True

        participants = {resp, signer} | (set(employee_members(w, commission)) if commission else set())
        forbidden = set().union(*(conflicted.get(e, set()) for e in participants))

        # --- решения по схемам ---
        forced: Optional[int] = None
        tags: list[tuple[str, int]] = []
        if resp in plan.s1_resp and plan.s1_resp[resp][1] == code and rs.random() < s1_win:
            forced = plan.s1_resp[resp][0]
            tags.append(("S1", resp))
        elif commission in plan.s1_comm and plan.s1_comm[commission][2] == code and rs.random() < s1_win:
            member, forced, _ = plan.s1_comm[commission]
            tags.append(("S1", member))
        elif resp in plan.s2:
            fav, total = plan.s2_totals[resp]
            if fav < s2_target * (total + nmck):
                forced = plan.s2[resp]
                plan.s2_totals[resp][0] += nmck
            plan.s2_totals[resp][1] += nmck
        s3 = competitive and resp in plan.s3 and rs.random() < sc["S3"]["share"]
        s4 = competitive and resp in plan.s4 and rs.random() < sc["S4"]["share"]
        if s3:
            deadline = published + dt.timedelta(days=legal_min_days(method, nmck))
            tags.append(("S3", resp))
            plan.label("S3", "employee", resp, resp)
        if s4:
            tags.append(("S4", resp))

        ds.procurements.append(Procurement(
            pid, unit, okpd2, method, rub(nmck), published.isoformat(),
            deadline.isoformat() if deadline else None, commission, resp))
        pm = ProcMeta(code, subject)
        meta[pid] = pm

        pool = [o for o in market_orgs[code] if o.id not in forbidden and o.id != forced]
        supplier: Optional[int] = None
        price = 0
        if competitive:
            # --- заявки ---
            if s3:
                n = 1
            elif s4:
                n = rs.randint(2, 3)
            else:
                n = 0 if rng.random() < 0.04 else wchoice(
                    rng, list(range(1, len(market.bid_weights) + 1)), market.bid_weights)
            if forced is not None:
                n = max(n - 1, 0)
            bidders = _weighted_sample(rng, pool, [6.0 if o.major else 1.0 for o in pool], n)
            if s4 and bidders:
                win_bp = rs.randint(5, 40)
                drops = [rs.randint(0, win_bp - 1) for _ in bidders]
                drops[rs.randrange(len(drops))] = win_bp
            elif len(bidders) >= 2 and rng.random() < noise["low_drop_share"]:
                drops = [rng.randint(0, 45) for _ in bidders]
            elif len(bidders) == 1:
                drops = [rng.randint(0, 150)]
            else:
                drops = [min(9000, rng.randint(50, 300 + 350 * len(bidders))
                             + (rng.randint(0, 300) if o.major else 0)) for o in bidders]
            offers = [(o.id, d) for o, d in zip(bidders, drops)]
            if forced is not None:
                fd = min(9500, max(drops) + rs.randint(10, 250)) if drops else rs.randint(0, 150)
                offers.insert(rs.randint(0, len(offers)), (forced, fd))
            for org_id, d in offers:
                bid_id += 1
                ds.bids.append(Bid(bid_id, pid, org_id, rub(_price(nmck, d))))
                pm.bid_ids.append(bid_id)
            if offers:
                best = min(range(len(offers)), key=lambda i: (_price(nmck, offers[i][1]), i))
                supplier, price = offers[best][0], _price(nmck, offers[best][1])
                pm.protocol_date = deadline + dt.timedelta(days=rng.randint(1, 3))
                signed = pm.protocol_date + dt.timedelta(days=rng.randint(10, 20))
        else:
            if forced is not None:
                supplier = forced
            elif pool:
                supplier = wchoice(rng, pool, [6.0 if o.major else 1.0 for o in pool]).id
            if supplier is not None:
                price = _price(nmck, rng.randint(0, 300))
                signed = published + dt.timedelta(days=rng.randint(2, 20))

        if supplier is None:
            continue   # закупка не состоялась

        contract_id += 1
        ds.contracts.append(Contract(contract_id, pid, supplier, rub(price), signed.isoformat(), signer))
        pm.contract_id = contract_id
        for scheme, emp in tags:
            if scheme in ("S1", "S4"):
                plan.label(scheme, "contract", contract_id, emp)
            elif scheme == "S3":
                plan.label("S3", "procurement", pid, emp)
        if s5:
            plan.label("S5", "contract", contract_id, signer)

        # --- допсоглашения ---
        deltas: list[tuple[int, str]] = []
        if s4:
            a1 = rs.randint(500, 800)
            a2 = max(rs.randint(400, 800), 1000 - a1 + rs.randint(10, 300))   # итог >= 10,1%
            deltas = [(price * a1 // 10_000, REASON_UP), (price * a2 // 10_000, REASON_UP)]
        elif rng.random() < g["amendment_share"]:
            for k in range(1 if rng.random() < 0.8 else 2):
                r = rng.random()
                if r < 0.5 or (k > 0 and r < 0.85):
                    deltas.append((0, rng.choice(REASON_TERMS)))
                elif r < 0.85:
                    deltas.append((price * rng.randint(100, 900) // 10_000, REASON_UP))
                else:
                    deltas.append((-(price * rng.randint(100, 1000) // 10_000), REASON_DOWN))
        when = signed
        for delta, reason in deltas:
            when = when + dt.timedelta(days=rng.randint(30, 150))
            amendment_id += 1
            ds.amendments.append(Amendment(amendment_id, contract_id, when.isoformat(), rub(delta), reason))

    for e in plan.s2:
        plan.label("S2", "employee", e, e)
    return meta
