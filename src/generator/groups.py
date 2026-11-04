"""Блок 1: закупочные комиссии, рабочие и проектные группы (создаются приказами),
связи SAME_COMMISSION / SAME_PROJECT между членами групп."""

from __future__ import annotations

import datetime as dt
from itertools import combinations

from src.models.entities import Group, GroupKind, GroupMember, MemberRole, RelType

from .common import GroupInfo, World, random_date
from .org import DEPUTY_DIRECTOR, SECTION_DEPUTY, SECTION_HEAD, STAFF
from .people import add_relation

WORKGROUP_TOPICS = (
    "подготовке технического задания на модернизацию серверного оборудования",
    "приемке результатов выполненных работ по текущему ремонту помещений",
    "подготовке предложений по оптимизации закупочной деятельности",
    "обследованию состояния информационной инфраструктуры",
    "подготовке ведомственного плана закупок",
    "проверке исполнения контрактов на оказание услуг",
    "инвентаризации материальных ценностей",
    "анализу рынка услуг технического обслуживания",
    "подготовке технического задания на оказание услуг связи",
    "приемке поставленного компьютерного оборудования",
)

PROJECT_TOPICS = (
    "внедрению системы электронного документооборота",
    "созданию реестра лицензий в электронном виде",
    "развитию портала государственных услуг ведомства",
    "переходу на отечественное программное обеспечение",
    "созданию системы мониторинга контрольно-надзорной деятельности",
    "модернизации центра обработки данных",
    "внедрению риск-ориентированного подхода",
    "цифровизации кадровых процессов",
)


def _reserve_order(w: World, rng, start: dt.date, end: dt.date) -> tuple[int, str, dt.date]:
    doc_id = w.doc_ids.next()
    date = random_date(rng, start, end)
    number = f"{rng.randint(10, 999)}-п"
    return doc_id, number, date


def _add_group(w: World, kind: str, name: str, members: list[tuple[str, int, str]], rng,
               start: dt.date, end: dt.date, department_id: int | None = None) -> GroupInfo:
    gid = len(w.groups) + 1
    doc_id, number, date = _reserve_order(w, rng, start, end)
    info = GroupInfo(gid, kind, name, doc_id, number, date, department_id, members)
    w.groups[gid] = info
    w.ds.groups.append(Group(gid, kind, name, doc_id))
    for mtype, mid, role in members:
        w.ds.group_members.append(GroupMember(gid, mtype, mid, role))
    rel = RelType.SAME_COMMISSION if kind == GroupKind.COMMISSION else RelType.SAME_PROJECT
    for (t1, i1, _), (t2, i2, _) in combinations(members, 2):
        if kind == GroupKind.COMMISSION and "person" in (t1, t2):
            continue
        add_relation(w, (t1, i1), (t2, i2), rel, evidence_doc_id=doc_id)
    return info


def build_groups(w: World) -> None:
    rng = w.rng("groups")
    g = w.gen
    start, end = w.period()
    emps = sorted(w.employees.values(), key=lambda e: e.id)
    proc = [e for e in emps if e.function_code == "PROC"]
    departments = sorted(w.department_function)
    proc_dep = next((d for d, fc in w.department_function.items() if fc == "PROC"), None)

    def pick(pool, used: set[int]):
        cand = [e for e in pool if e.id not in used]
        e = rng.choice(cand)
        used.add(e.id)
        return e.id

    # --- постоянно действующие закупочные комиссии: созданы приказами в январе 2024 ---
    for k in range(g["commissions"]):
        dep = departments[k % len(departments)]
        used: set[int] = set()
        chair = pick([e for e in proc if e.role in (SECTION_HEAD, DEPUTY_DIRECTOR)], used)
        deputy = pick([e for e in proc if e.role == SECTION_DEPUTY], used)
        dep_pool = [e for e in emps if e.department_id == dep and e.role in (SECTION_HEAD, SECTION_DEPUTY, STAFF)
                    and (dep == proc_dep or e.function_code != "PROC")]
        m1, m2 = pick(dep_pool, used), pick(dep_pool, used)
        secretary = pick([e for e in proc if e.role == STAFF], used)
        members = [("employee", chair, MemberRole.CHAIR), ("employee", deputy, MemberRole.DEPUTY_CHAIR),
                   ("employee", m1, MemberRole.MEMBER), ("employee", m2, MemberRole.MEMBER),
                   ("employee", secretary, MemberRole.SECRETARY)]
        _add_group(w, GroupKind.COMMISSION, f"Единая комиссия по осуществлению закупок № {k + 1}",
                   members, rng, start, start + dt.timedelta(days=30), department_id=dep)

    # --- рабочие группы ---
    for k in range(g["workgroups"]):
        used = set()
        deps = rng.sample(departments, 2)
        pool = [e for e in emps if e.department_id in deps]
        n = rng.randint(4, 6)
        ids = [pick(pool, used) for _ in range(n)]
        roles = [MemberRole.LEADER] + [MemberRole.MEMBER] * (n - 2) + [MemberRole.SECRETARY]
        topic = WORKGROUP_TOPICS[k % len(WORKGROUP_TOPICS)]
        _add_group(w, GroupKind.WORKGROUP, f"Рабочая группа по {topic}",
                   [("employee", i, r) for i, r in zip(ids, roles)], rng, start, end)

    # --- проектные группы: могут включать внешних лиц (представителей организаций) ---
    it_orgs = sorted(o.id for o in w.orgs.values() if set(o.markets) & {"58", "62", "72"})
    for k in range(g["projects"]):
        used = set()
        deps = rng.sample(departments, 2)
        pool = [e for e in emps if e.department_id in deps]
        n = rng.randint(4, 6)
        ids = [pick(pool, used) for _ in range(n)]
        members = [("employee", ids[0], MemberRole.LEADER)] + [("employee", i, MemberRole.MEMBER) for i in ids[1:]]
        for org_id in rng.sample(it_orgs, rng.randint(1, 2)):
            members.append(("person", w.org_director[org_id], MemberRole.MEMBER))
        topic = PROJECT_TOPICS[k % len(PROJECT_TOPICS)]
        _add_group(w, GroupKind.PROJECT, f"Проектная группа по {topic}", members, rng,
                   start, start + dt.timedelta(days=365))


def commissions_by_department(w: World) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for gi in w.groups.values():
        if gi.kind == GroupKind.COMMISSION and gi.department_id is not None:
            out.setdefault(gi.department_id, []).append(gi.id)
    return out


def employee_members(w: World, group_id: int) -> list[int]:
    return [mid for mtype, mid, _ in w.groups[group_id].members if mtype == "employee"]
