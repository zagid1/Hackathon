"""Внешние лица: родственники служащих, руководители и учредители фирм; связи RELATIVE и EX_EMPLOYER."""

from __future__ import annotations

from typing import Optional

from src.models.entities import Person, RelType, Relation

from .common import World
from .names import FEMALE, MALE, PersonName, surname_base

# Степени родства (для описаний; в схеме связи RELATIVE степень не хранится).
KINSHIP = ("супруг(а)", "брат/сестра", "сын/дочь", "отец/мать")


def add_person(w: World, name: Optional[PersonName] = None, **kw) -> int:
    assert w.names is not None
    pn = name or w.names.new(**kw)
    pid = w.person_ids.next()
    w.ds.persons.append(Person(pid, pn.full))
    w.person_names[pid] = pn
    return pid


def add_relation(w: World, a: tuple[str, int], b: tuple[str, int], rel_type: str,
                 evidence_doc_id: Optional[int] = None) -> int:
    """Неориентированная связь; концы упорядочиваются, чтобы не зависеть от порядка аргументов."""
    (at, ai), (bt, bi) = sorted([a, b])
    rid = w.relation_ids.next()
    w.ds.relations.append(Relation(rid, at, ai, bt, bi, rel_type, evidence_doc_id=evidence_doc_id))
    return rid


def make_relative(w: World, employee_id: int) -> int:
    """Создаёт родственника служащего (person) и связь RELATIVE."""
    rng = w.rng(f"relative:{employee_id}:{len(w.relatives.get(employee_id, []))}")
    emp = w.employees[employee_id].name
    gender = MALE if rng.random() < 0.5 else FEMALE
    same_family = rng.random() < 0.7          # супруги/дети/братья обычно с той же фамилией
    assert w.names is not None
    pn = w.names.new(gender=gender, surname_base=surname_base(emp) if same_family else None)
    pid = add_person(w, pn)
    w.relatives.setdefault(employee_id, []).append(pid)
    add_relation(w, ("employee", employee_id), ("person", pid), RelType.RELATIVE)
    return pid


def build_background_relatives(w: World, exclude: set[int]) -> list[int]:
    """Фоновые родственники ~employee_share служащих. Возвращает созданных лиц."""
    cfg = w.gen["relatives"]
    rng = w.rng("relatives")
    candidates = [e for e in sorted(w.employees) if e not in exclude]
    target = round(len(w.employees) * cfg["employee_share"]) - len(exclude)
    chosen = sorted(rng.sample(candidates, max(0, min(target, len(candidates)))))
    created = []
    for eid in chosen:
        for _ in range(rng.randint(1, cfg["max_per_employee"])):
            created.append(make_relative(w, eid))
    return created


def build_ex_employers(w: World, org_ids: list[int]) -> None:
    """Бывшее место работы части служащих — коммерческая организация (связь EX_EMPLOYER)."""
    rng = w.rng("ex_employer")
    emp_ids = sorted(w.employees)
    n = round(len(emp_ids) * w.gen["ex_employer_share"])
    for eid in sorted(rng.sample(emp_ids, n)):
        add_relation(w, ("employee", eid), ("organization", rng.choice(org_ids)), RelType.EX_EMPLOYER)
