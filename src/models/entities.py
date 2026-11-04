"""Dataclass-модели строк БД. Источник истины для структуры — schema.sql;
тест tests/test_models.py проверяет, что поля dataclass совпадают с колонками таблиц.

Перечисления хранятся как обычные строки (константы в классах ниже), чтобы в БД попадали
ровно те значения, что разрешены CHECK-ограничениями.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass, field, fields
from typing import Any, ClassVar, Optional

SYNTHETIC = "synthetic"
REAL = "real"


class FunctionCode:
    PROC = "PROC"
    LIC = "LIC"
    CONTROL = "CONTROL"
    HR = "HR"
    OTHER = "OTHER"
    ALL = (PROC, LIC, CONTROL, HR, OTHER)


class Action:
    SIGN_CONTRACT = "SIGN_CONTRACT"
    SIGN_AMENDMENT = "SIGN_AMENDMENT"
    APPROVE_PROC = "APPROVE_PROC"
    RESPONSIBLE_PROC = "RESPONSIBLE_PROC"
    ALL = (SIGN_CONTRACT, SIGN_AMENDMENT, APPROVE_PROC, RESPONSIBLE_PROC)


class Method:
    AUCTION = "AUCTION"
    TENDER = "TENDER"
    QUOTATION = "QUOTATION"
    SINGLE_SUPPLIER = "SINGLE_SUPPLIER"
    COMPETITIVE = (AUCTION, TENDER, QUOTATION)
    ALL = (AUCTION, TENDER, QUOTATION, SINGLE_SUPPLIER)


class RelType:
    RELATIVE = "RELATIVE"
    EX_EMPLOYER = "EX_EMPLOYER"
    SAME_PROJECT = "SAME_PROJECT"
    SAME_COMMISSION = "SAME_COMMISSION"


class GroupKind:
    PROJECT = "PROJECT"
    COMMISSION = "COMMISSION"
    WORKGROUP = "WORKGROUP"


class MemberRole:
    CHAIR = "CHAIR"
    DEPUTY_CHAIR = "DEPUTY_CHAIR"
    MEMBER = "MEMBER"
    SECRETARY = "SECRETARY"
    LEADER = "LEADER"


class DocType:
    PROTOCOL = "PROTOCOL"
    ORDER = "ORDER"
    CONTRACT = "CONTRACT"


class SignalStatus:
    NEW = "NEW"
    IN_WORK = "IN_WORK"
    REJECTED = "REJECTED"


class Row:
    """Базовый класс строки таблицы."""

    TABLE: ClassVar[str] = ""

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]  # type: ignore[arg-type]

    def to_row(self) -> tuple[Any, ...]:
        return astuple(self)  # type: ignore[call-overload]


@dataclass
class Unit(Row):
    TABLE: ClassVar[str] = "units"
    id: int
    name: str
    parent_id: Optional[int]
    level: int
    source: str = SYNTHETIC


@dataclass
class Position(Row):
    TABLE: ClassVar[str] = "positions"
    id: int
    unit_id: int
    title: str
    function_code: str


@dataclass
class PositionAuthority(Row):
    TABLE: ClassVar[str] = "position_authorities"
    position_id: int
    action: str


@dataclass
class Employee(Row):
    TABLE: ClassVar[str] = "employees"
    id: int
    full_name: str
    position_id: int
    hired_at: str
    source: str = SYNTHETIC


@dataclass
class Person(Row):
    TABLE: ClassVar[str] = "persons"
    id: int
    full_name: str
    source: str = SYNTHETIC


@dataclass
class Organization(Row):
    TABLE: ClassVar[str] = "organizations"
    id: int
    name: str
    inn: str
    ogrn: str
    okved: str
    registered_at: str
    source: str = SYNTHETIC


@dataclass
class OrgRole(Row):
    TABLE: ClassVar[str] = "org_roles"
    org_id: int
    person_id: int
    role: str  # DIRECTOR | FOUNDER


@dataclass
class Document(Row):
    TABLE: ClassVar[str] = "documents"
    id: int
    doc_type: str
    path: str
    source: str = SYNTHETIC
    object_type: Optional[str] = None
    object_id: Optional[int] = None
    doc_number: Optional[str] = None
    doc_date: Optional[str] = None


@dataclass
class DocFragment(Row):
    TABLE: ClassVar[str] = "doc_fragments"
    id: int
    document_id: int
    page: int
    char_start: int
    char_end: int
    text: str


@dataclass
class Group(Row):
    TABLE: ClassVar[str] = "groups"
    id: int
    kind: str
    name: str
    created_by_doc_id: Optional[int]
    source: str = SYNTHETIC


@dataclass
class GroupMember(Row):
    TABLE: ClassVar[str] = "group_members"
    group_id: int
    member_type: str  # employee | person
    member_id: int
    role: str


@dataclass
class Relation(Row):
    TABLE: ClassVar[str] = "relations"
    id: int
    a_type: str
    a_id: int
    b_type: str
    b_id: int
    rel_type: str
    source: str = SYNTHETIC
    evidence_doc_id: Optional[int] = None


@dataclass
class Procurement(Row):
    TABLE: ClassVar[str] = "procurements"
    id: int
    unit_id: int
    okpd2: str
    method: str
    nmck: float
    published_at: str
    deadline_at: Optional[str]
    commission_group_id: Optional[int]
    responsible_employee_id: int
    source: str = SYNTHETIC


@dataclass
class Bid(Row):
    TABLE: ClassVar[str] = "bids"
    id: int
    procurement_id: int
    org_id: int
    price: float
    source: str = SYNTHETIC


@dataclass
class Contract(Row):
    TABLE: ClassVar[str] = "contracts"
    id: int
    procurement_id: int
    supplier_org_id: int
    price: float
    signed_at: str
    signer_employee_id: int
    source: str = SYNTHETIC


@dataclass
class Amendment(Row):
    TABLE: ClassVar[str] = "amendments"
    id: int
    contract_id: int
    signed_at: str
    price_delta: float
    reason: str
    source: str = SYNTHETIC


@dataclass
class Signal(Row):
    TABLE: ClassVar[str] = "signals"
    id: int
    indicator: str
    object_type: str
    object_id: int
    employee_id: Optional[int]
    value: Optional[float]
    threshold: Optional[float]
    peer_group: Optional[str]
    explanation: str
    evidence_fragment_ids: str = "[]"
    status: str = SignalStatus.NEW
    reviewer_comment: Optional[str] = None


@dataclass
class InjectedScheme(Row):
    TABLE: ClassVar[str] = "injected_schemes"
    id: int
    scheme: str
    object_type: str
    object_id: int
    employee_id: int


@dataclass
class DatasetMeta(Row):
    TABLE: ClassVar[str] = "dataset_meta"
    key: str
    value: str


# Порядок вставки учитывает внешние ключи.
ALL_MODELS: tuple[type[Row], ...] = (
    Unit, Position, PositionAuthority, Employee, Person, Organization, OrgRole,
    Document, DocFragment, Group, GroupMember, Relation,
    Procurement, Bid, Contract, Amendment, Signal, InjectedScheme, DatasetMeta,
)


@dataclass
class Dataset:
    """Все строки одного набора данных; списки упорядочены по id (порядок генерации)."""

    units: list[Unit] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    position_authorities: list[PositionAuthority] = field(default_factory=list)
    employees: list[Employee] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    organizations: list[Organization] = field(default_factory=list)
    org_roles: list[OrgRole] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)
    doc_fragments: list[DocFragment] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    group_members: list[GroupMember] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    procurements: list[Procurement] = field(default_factory=list)
    bids: list[Bid] = field(default_factory=list)
    contracts: list[Contract] = field(default_factory=list)
    amendments: list[Amendment] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    injected_schemes: list[InjectedScheme] = field(default_factory=list)
    dataset_meta: list[DatasetMeta] = field(default_factory=list)

    def tables(self) -> list[tuple[type[Row], list[Row]]]:
        return [(m, getattr(self, m.TABLE)) for m in ALL_MODELS]
