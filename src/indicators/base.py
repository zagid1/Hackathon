"""Общая база индикаторов: контекст данных, Signal, группы сравнения, перцентили, доказательства.

Принципы (PLAN.md, раздел 7):
* группа сравнения = (function_code или первые 2 знака ОКПД2 / способ закупки, год);
* пороги — перцентили по группе, кроме законодательных; перцентиль считается по коллегам
  (без самого служащего — leave-one-out), чтобы выброс не поднимал собственный порог;
* индикатор уровня служащего считается при >= min_decisions решений в группе;
* у каждого сигнала: значение, порог, группа сравнения, объяснение, id фрагментов документов;
* никакого единого «индекса человека».
"""

from __future__ import annotations

import datetime as dt
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional, Sequence

from src.generator.names import FEMALE, MALE, PersonName


@dataclass
class Signal:
    indicator: str
    object_type: str
    object_id: int
    employee_id: Optional[int]
    value: Optional[float]
    threshold: Optional[float]
    peer_group: Optional[str]
    explanation: str
    evidence: list[int] = field(default_factory=list)

    def sort_key(self) -> tuple:
        return (self.indicator, self.object_type, self.object_id, self.employee_id or 0, self.peer_group or "")


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Перцентиль с линейной интерполяцией (как numpy.percentile по умолчанию)."""
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def pct(x: float, digits: int = 0) -> str:
    """0.623 -> «62%», pct(0.0021, 1) -> «0,2%»."""
    return f"{x * 100:.{digits}f}%".replace(".", ",")


def cap_first(s: str) -> str:
    return s[:1].upper() + s[1:]


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


def rub(x: float) -> str:
    r = int(round(x))
    return f"{r:,}".replace(",", " ") + " руб."


def date_ru(iso: str) -> str:
    return dt.date.fromisoformat(iso).strftime("%d.%m.%Y")


def person_from_full_name(full_name: str) -> Optional[PersonName]:
    parts = full_name.split()
    if len(parts) != 3:
        return None
    gender = FEMALE if parts[2].endswith(("вна", "чна", "шна")) else MALE
    return PersonName(parts[0], parts[1], parts[2], gender)


def name_variants(full_name: str) -> list[str]:
    """Формы ФИО, в которых оно встречается в документах: падежи и инициалы."""
    pn = person_from_full_name(full_name)
    if pn is None:
        return [full_name]
    forms = {pn.case(c) for c in ("nom", "gen", "dat", "acc")}
    forms |= {pn.initials_after(), pn.initials_before()}
    return sorted(forms, key=lambda s: (-len(s), s))


def short_name(full_name: str) -> str:
    pn = person_from_full_name(full_name)
    return pn.initials_after() if pn else full_name


def org_core(name: str) -> str:
    """«ООО «Вектор-Строй»» -> «Вектор-Строй» в кавычках-ёлочках (общая часть всех форм наименования)."""
    if "«" in name and "»" in name:
        return name[name.index("«"): name.rindex("»") + 1]
    return name


class Context:
    """Все данные, нужные индикаторам, загруженные из БД один раз."""

    def __init__(self, conn: sqlite3.Connection, cfg: dict):
        self.conn = conn
        self.cfg = cfg
        self.icfg = cfg["indicators"]
        q = conn.execute

        self.employees = {r[0]: {"id": r[0], "full_name": r[1], "position_id": r[2], "title": r[3],
                                 "function_code": r[4], "unit_id": r[5]}
                          for r in q("SELECT e.id, e.full_name, e.position_id, p.title, p.function_code, p.unit_id "
                                     "FROM employees e JOIN positions p ON p.id = e.position_id ORDER BY e.id")}
        self.authorities: dict[int, set[str]] = defaultdict(set)
        for pid, action in q("SELECT position_id, action FROM position_authorities ORDER BY 1, 2"):
            self.authorities[pid].add(action)
        self.positions = {r[0]: r[1] for r in q("SELECT id, title FROM positions ORDER BY id")}

        self.orgs = {r[0]: r[1] for r in q("SELECT id, name FROM organizations ORDER BY id")}
        self.persons = {r[0]: r[1] for r in q("SELECT id, full_name FROM persons ORDER BY id")}
        self.org_people: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for oid, pid, role in q("SELECT org_id, person_id, role FROM org_roles ORDER BY 1, 2, 3"):
            self.org_people[oid].append((pid, role))

        self.procurements = {}
        for r in q("SELECT id, unit_id, okpd2, method, nmck, published_at, deadline_at, commission_group_id, "
                   "responsible_employee_id FROM procurements ORDER BY id"):
            self.procurements[r[0]] = {"id": r[0], "unit_id": r[1], "okpd2": r[2], "method": r[3], "nmck": r[4],
                                       "published_at": r[5], "deadline_at": r[6], "commission": r[7],
                                       "responsible": r[8], "year": int(r[5][:4])}
        self.bids: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
        for bid, pid, org, price in q("SELECT id, procurement_id, org_id, price FROM bids ORDER BY procurement_id, id"):
            self.bids[pid].append((bid, org, price))
        self.contracts = {}
        self.contract_by_proc = {}
        for r in q("SELECT id, procurement_id, supplier_org_id, price, signed_at, signer_employee_id "
                   "FROM contracts ORDER BY id"):
            self.contracts[r[0]] = {"id": r[0], "procurement_id": r[1], "supplier": r[2], "price": r[3],
                                    "signed_at": r[4], "signer": r[5]}
            self.contract_by_proc[r[1]] = r[0]
        self.amendments: dict[int, list[tuple[str, float, str]]] = defaultdict(list)
        for cid, signed, delta, reason in q("SELECT contract_id, signed_at, price_delta, reason FROM amendments "
                                            "ORDER BY contract_id, signed_at, id"):
            self.amendments[cid].append((signed, delta, reason))

        self.groups = {r[0]: {"id": r[0], "kind": r[1], "name": r[2], "doc_id": r[3]}
                       for r in q("SELECT id, kind, name, created_by_doc_id FROM groups ORDER BY id")}
        self.group_members: dict[int, list[tuple[str, int, str]]] = defaultdict(list)
        for gid, mt, mid, role in q("SELECT group_id, member_type, member_id, role FROM group_members "
                                    "ORDER BY group_id, member_type, member_id"):
            self.group_members[gid].append((mt, mid, role))

        self.documents = {r[0]: {"id": r[0], "doc_type": r[1], "object_type": r[2], "object_id": r[3],
                                 "number": r[4], "date": r[5]}
                          for r in q("SELECT id, doc_type, object_type, object_id, doc_number, doc_date "
                                     "FROM documents ORDER BY id")}
        self.doc_by_object = {(d["object_type"], d["object_id"]): i for i, d in self.documents.items()}
        self.fragments: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
        for fid, doc, page, text in q("SELECT id, document_id, page, text FROM doc_fragments ORDER BY id"):
            self.fragments[doc].append((fid, page, text))

    # --- производные выборки ---

    @cached_property
    def graph(self):
        from src.graph.build import build_graph
        return build_graph(self.conn)

    def commission_employees(self, gid: Optional[int]) -> list[tuple[int, str]]:
        if gid is None:
            return []
        return [(mid, role) for mt, mid, role in self.group_members[gid] if mt == "employee"]

    def can(self, employee_id: int, action: str) -> bool:
        return action in self.authorities[self.employees[employee_id]["position_id"]]

    def n_bids(self, pid: int) -> int:
        return len(self.bids.get(pid, []))

    # --- доказательства: id фрагментов документов ---

    def protocol_fragments(self, pid: int, org_id: Optional[int] = None, last: bool = False) -> list[int]:
        """Фрагменты протокола закупки; с org_id — где упомянута организация (last — только последний,
        это решение комиссии о победителе)."""
        doc = self.doc_by_object.get(("procurement", pid))
        if doc is None:
            return []
        frags = self.fragments[doc]
        if org_id is not None:
            core = org_core(self.orgs[org_id])
            frags = [f for f in frags if core in f[2]]
        ids = [f[0] for f in frags]
        return ids[-1:] if last else ids

    def member_fragments(self, gid: int, members: Sequence[tuple[str, int]]) -> list[int]:
        """Фрагменты приказа о создании группы, где упомянуты указанные участники (в любом падеже)."""
        doc = self.groups[gid]["doc_id"]
        if doc is None:
            return []
        out = []
        for kind, mid in members:
            name = self.employees[mid]["full_name"] if kind == "employee" else self.persons[mid]
            forms = name_variants(name)
            out += [f[0] for f in self.fragments[doc] if any(v in f[2] for v in forms)][:1]
        return out

    def doc_ref(self, doc_id: int) -> str:
        d = self.documents[doc_id]
        kind = {"ORDER": "приказ", "PROTOCOL": "протокол", "CONTRACT": "контракт"}[d["doc_type"]]
        return f"{kind} № {d['number']} от {date_ru(d['date'])}"


def weights(cfg: dict) -> dict[str, float]:
    return dict(cfg["indicators"].get("weights", {}))
