"""Общие вспомогательные средства генератора.

Детерминированность:
* у каждого модуля свой поток случайных чисел random.Random(f"{seed}:{имя}") — правка одного
  модуля не сдвигает случайность в остальных; строковый seed в CPython хэшируется SHA-512
  и не зависит от PYTHONHASHSEED;
* используются только rng.random/randint/choice/choices/sample/shuffle и арифметика —
  без math.log/exp и т. п., чтобы результат не зависел от реализации libm;
* суммы float — только math.fsum (встроенный sum() для float в 3.12 и 3.11 даёт разный результат);
* деньги считаются в целых копейках, в БД пишутся как копейки / 100.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence, TypeVar

from src.models.entities import Dataset

from .names import NameFactory, PersonName

T = TypeVar("T")


def make_rng(seed: int, stream: str) -> random.Random:
    return random.Random(f"{seed}:{stream}")


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s))


def random_date(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=rng.randint(0, (end - start).days))


def wchoice(rng: random.Random, items: Sequence[T], weights: Sequence[float]) -> T:
    return rng.choices(items, weights=weights, k=1)[0]


def rub(kop: int) -> float:
    return kop / 100


class IdSeq:
    def __init__(self) -> None:
        self.last = 0

    def next(self) -> int:
        self.last += 1
        return self.last


@dataclass
class EmployeeInfo:
    id: int
    name: PersonName
    position_id: int
    title: str
    unit_id: int          # отдел (или департамент/ведомство для руководителей)
    department_id: Optional[int]
    function_code: str
    role: str             # HEAD, DEPUTY_HEAD, DIRECTOR, DEPUTY_DIRECTOR, SECTION_HEAD, SECTION_DEPUTY, STAFF
    actions: frozenset[str] = frozenset()


@dataclass
class Market:
    code: str             # первые 2 знака ОКПД2
    name: str
    okpd2: tuple[tuple[str, str], ...]   # (код ОКПД2, наименование объекта закупки)
    okved: str
    nmck_rub: tuple[int, int]
    bid_weights: tuple[float, ...]       # вероятности 1, 2, 3, ... заявок
    weight: float                        # доля закупок рынка
    org_share: float                     # доля организаций рынка
    tender_share: float = 0.05


@dataclass
class OrgInfo:
    id: int
    name: str
    legal_form: str       # ООО / АО / ПАО
    core: str             # название без формы и кавычек
    inn: str
    ogrn: str
    markets: list[str]
    major: bool = False   # крупный «честный» поставщик рынка


@dataclass
class GroupInfo:
    id: int
    kind: str
    name: str
    doc_id: int
    doc_number: str
    doc_date: dt.date
    department_id: Optional[int]
    members: list[tuple[str, int, str]] = field(default_factory=list)   # (member_type, id, role)


@dataclass
class World:
    """Состояние генерации: строки БД + служебные сведения, которых нет в схеме (род, рынки ...)."""

    cfg: dict
    seed: int
    ds: Dataset = field(default_factory=Dataset)
    employees: dict[int, EmployeeInfo] = field(default_factory=dict)
    person_names: dict[int, PersonName] = field(default_factory=dict)
    units: dict[int, str] = field(default_factory=dict)
    unit_parent: dict[int, Optional[int]] = field(default_factory=dict)
    department_function: dict[int, str] = field(default_factory=dict)
    markets: dict[str, Market] = field(default_factory=dict)
    orgs: dict[int, OrgInfo] = field(default_factory=dict)
    org_director: dict[int, int] = field(default_factory=dict)
    org_founders: dict[int, list[int]] = field(default_factory=dict)
    relatives: dict[int, list[int]] = field(default_factory=dict)      # employee -> persons
    groups: dict[int, GroupInfo] = field(default_factory=dict)
    responsible_markets: dict[int, list[str]] = field(default_factory=dict)
    names: Optional[NameFactory] = None
    doc_ids: IdSeq = field(default_factory=IdSeq)
    person_ids: IdSeq = field(default_factory=IdSeq)
    relation_ids: IdSeq = field(default_factory=IdSeq)

    @property
    def gen(self) -> dict:
        return self.cfg["generator"]

    def rng(self, stream: str) -> random.Random:
        return make_rng(self.seed, stream)

    def period(self) -> tuple[dt.date, dt.date]:
        return parse_date(self.gen["period_start"]), parse_date(self.gen["period_end"])
