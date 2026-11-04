"""Внедрение схем S1–S5 (PLAN.md, раздел 6) и ground truth (таблица injected_schemes).

Подготовка (setup_schemes) выбирает участников схем до генерации закупок; сами закупки
генерирует procurement.py, который спрашивает у SchemePlan, не должна ли конкретная закупка
стать экземпляром схемы. Фон при этом остаётся «чистым» по прямому родству: фирмы родственников
участников закупки (ответственный, члены комиссии, подписант) в фоне к закупке не допускаются.

Гранулярность ground truth = уровень индикатора, который должен найти схему:
  S1 — контракты (И2; на уровне служащего — И1 через employee_id);
  S2 — служащие (И1);
  S3 — служащие и закупки (И3);
  S4 — контракты (И4);
  S5 — контракты (И7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models.entities import Action, InjectedScheme

from .common import World
from .companies import affiliated_persons, orgs_in_market, set_director
from .groups import employee_members
from .org import SECTION_DEPUTY, SECTION_HEAD, responsible_pool
from .people import make_relative


@dataclass
class SchemePlan:
    s1_resp: dict[int, tuple[int, str]] = field(default_factory=dict)        # служащий -> (фирма, рынок)
    s1_comm: dict[int, tuple[int, int, str]] = field(default_factory=dict)   # комиссия -> (член, фирма, рынок)
    s2: dict[int, int] = field(default_factory=dict)                         # служащий -> фирма
    s2_totals: dict[int, list[int]] = field(default_factory=dict)            # служащий -> [своей фирме, всего], коп.
    s3: set[int] = field(default_factory=set)
    s4: set[int] = field(default_factory=set)
    s5: dict[int, int] = field(default_factory=dict)                         # отдел -> подписант
    labels: set[tuple[str, str, int, int]] = field(default_factory=set)

    def scheme_employees(self) -> set[int]:
        return (set(self.s1_resp) | {m for m, _, _ in self.s1_comm.values()} | set(self.s2)
                | self.s3 | self.s4 | set(self.s5.values()))

    def label(self, scheme: str, object_type: str, object_id: int, employee_id: int) -> None:
        self.labels.add((scheme, object_type, object_id, employee_id))


def _free_firm(w: World, market: str, taken: set[int], rng) -> int:
    """Немажорная фирма рынка, не задействованная в других схемах и проектных группах."""
    in_projects = {mid for gi in w.groups.values() for t, mid, _ in gi.members if t == "person"}
    cand = [o.id for o in orgs_in_market(w, market)
            if not o.major and o.id not in taken and w.org_director[o.id] not in in_projects]
    firm = rng.choice(sorted(cand))
    taken.add(firm)
    return firm


def setup_schemes(w: World) -> SchemePlan:
    rng = w.rng("schemes")
    sc = w.cfg["schemes"]
    plan = SchemePlan()
    taken_firms: set[int] = set()

    pool = sorted(e.id for e in responsible_pool(w))
    need = (sc["S1"]["responsible_employees"] + sc["S2"]["employees"] + sc["S3"]["employees"]
            + sc["S4"]["employees"])
    if need > len(pool):
        raise ValueError("ответственных за закупки меньше, чем участников схем")
    chosen = rng.sample(pool, need)
    k1, k2, k3 = sc["S1"]["responsible_employees"], sc["S2"]["employees"], sc["S3"]["employees"]
    s1_emps, s2_emps = chosen[:k1], chosen[k1:k1 + k2]
    s3_emps, s4_emps = chosen[k1 + k2:k1 + k2 + k3], chosen[k1 + k2 + k3:]

    # S2: «своя» фирма; специализация служащего сужается до рынков этой фирмы
    big_markets = sorted(c for c, m in w.markets.items() if m.weight >= 0.09)
    for e in sorted(s2_emps):
        firm = _free_firm(w, rng.choice(big_markets), taken_firms, rng)
        plan.s2[e] = firm
        plan.s2_totals[e] = [0, 0]
        w.responsible_markets[e] = list(w.orgs[firm].markets)

    # S1 (ответственный): родственник служащего — директор фирмы на одном из его рынков
    for e in sorted(s1_emps):
        markets = [m for m in w.responsible_markets[e] if len(orgs_in_market(w, m)) >= 6]
        market = rng.choice(sorted(markets))
        firm = _free_firm(w, market, taken_firms, rng)
        rel = make_relative(w, e)
        set_director(w, firm, rel, also_founder=rng.random() < 0.5)
        plan.s1_resp[e] = (firm, market)

    # S1 (член комиссии): родственник члена комиссии (не из закупочного подразделения) — директор фирмы
    used = set(chosen)
    commissions = sorted(gid for gid, gi in w.groups.items() if gi.kind == "COMMISSION")
    rng.shuffle(commissions)
    for gid in commissions[: sc["S1"]["commission_members"]]:
        members = [m for mt, m, role in w.groups[gid].members
                   if mt == "employee" and role == "MEMBER" and m not in used
                   and w.employees[m].function_code != "PROC"]
        member = rng.choice(sorted(members))
        used.add(member)
        market = rng.choice(big_markets)
        firm = _free_firm(w, market, taken_firms, rng)
        rel = make_relative(w, member)
        set_director(w, firm, rel, also_founder=rng.random() < 0.5)
        plan.s1_comm[gid] = (member, firm, market)

    plan.s3 = set(s3_emps)
    plan.s4 = set(s4_emps)

    # S5: начальник (или заместитель) непрофильного отдела подписывает контракты своего отдела
    sections = sorted(e.unit_id for e in w.employees.values()
                      if e.role == SECTION_HEAD and e.function_code != "PROC")
    for unit in sorted(rng.sample(sections, sc["S5"]["signers"])):
        cands = sorted(e.id for e in w.employees.values()
                       if e.unit_id == unit and e.role in (SECTION_HEAD, SECTION_DEPUTY) and e.id not in used)
        signer = rng.choice(cands)
        assert Action.SIGN_CONTRACT not in w.employees[signer].actions
        used.add(signer)
        plan.s5[unit] = signer
    return plan


def forbidden_orgs(w: World, employee_ids) -> set[int]:
    """Фирмы, где директор или учредитель — родственник кого-то из участников закупки."""
    persons = {p for e in employee_ids for p in w.relatives.get(e, [])}
    if not persons:
        return set()
    return {oid for oid in w.orgs if affiliated_persons(w, oid) & persons}


def emit_labels(w: World, plan: SchemePlan) -> None:
    rows = sorted(plan.labels)
    w.ds.injected_schemes = [InjectedScheme(i, *r) for i, r in enumerate(rows, start=1)]


__all__ = ["SchemePlan", "setup_schemes", "forbidden_orgs", "emit_labels", "employee_members"]
