"""Ведомство, подразделения, должности, полномочия, служащие."""

from __future__ import annotations

import datetime as dt

from src.models.entities import Action, Employee, FunctionCode, Position, PositionAuthority, Unit

from .common import EmployeeInfo, World, random_date

# (окончание названия департамента в род. падеже, функция, окончания названий отделов)
DEPARTMENTS = (
    ("закупок и материально-технического обеспечения", FunctionCode.PROC,
     ("планирования закупок", "проведения конкурентных процедур", "контрактной работы",
      "материально-технического обеспечения")),
    ("лицензирования и разрешительной деятельности", FunctionCode.LIC,
     ("лицензирования", "выдачи разрешений", "ведения реестров", "методологии лицензирования")),
    ("контроля и надзора", FunctionCode.CONTROL,
     ("плановых проверок", "внеплановых проверок", "административной практики", "анализа рисков")),
    ("кадров и делопроизводства", FunctionCode.HR,
     ("государственной службы и кадров", "профилактики коррупционных правонарушений",
      "делопроизводства", "правового обеспечения")),
    ("информационных технологий", FunctionCode.OTHER,
     ("развития информационных систем", "эксплуатации инфраструктуры", "информационной безопасности",
      "цифровых сервисов")),
)

STAFF_TITLES = ("Консультант", "Главный специалист-эксперт", "Ведущий специалист-эксперт")

HEAD, DEPUTY_HEAD = "HEAD", "DEPUTY_HEAD"
DIRECTOR, DEPUTY_DIRECTOR = "DIRECTOR", "DEPUTY_DIRECTOR"
SECTION_HEAD, SECTION_DEPUTY, STAFF = "SECTION_HEAD", "SECTION_DEPUTY", "STAFF"

SIGNERS = frozenset({Action.SIGN_CONTRACT, Action.SIGN_AMENDMENT})


def _authorities(role: str, function_code: str) -> frozenset[str]:
    """Регламент полномочий (синтетический). Право подписи контракта — только у руководства
    ведомства, директоров департаментов и заместителя директора департамента закупок."""
    proc = function_code == FunctionCode.PROC
    if role in (HEAD, DEPUTY_HEAD):
        return SIGNERS | {Action.APPROVE_PROC}
    if role == DIRECTOR:
        return SIGNERS | ({Action.APPROVE_PROC} if proc else set())
    if role == DEPUTY_DIRECTOR:
        return SIGNERS | {Action.APPROVE_PROC} if proc else frozenset()
    if role == SECTION_HEAD:
        return frozenset({Action.APPROVE_PROC, Action.RESPONSIBLE_PROC}) if proc else frozenset()
    if role in (SECTION_DEPUTY, STAFF):
        return frozenset({Action.RESPONSIBLE_PROC}) if proc else frozenset()
    raise ValueError(role)


def build_org(w: World) -> None:
    g = w.gen
    rng = w.rng("org")
    n_dep, n_sec = g["departments"], g["sections_per_department"]
    if not 1 <= n_dep <= len(DEPARTMENTS) or not 1 <= n_sec <= 4:
        raise ValueError("поддерживается до 5 департаментов и до 4 отделов в каждом")

    ds = w.ds
    unit_id = 0
    position_id = 0
    positions: dict[tuple[int, str], int] = {}

    def add_unit(name: str, parent: int | None, level: int) -> int:
        nonlocal unit_id
        unit_id += 1
        ds.units.append(Unit(unit_id, name, parent, level))
        w.units[unit_id] = name
        w.unit_parent[unit_id] = parent
        return unit_id

    def position(unit: int, title: str, fc: str, role: str) -> int:
        nonlocal position_id
        key = (unit, title)
        if key not in positions:
            position_id += 1
            positions[key] = position_id
            ds.positions.append(Position(position_id, unit, title, fc))
            for a in sorted(_authorities(role, fc)):
                ds.position_authorities.append(PositionAuthority(position_id, a))
        return positions[key]

    # --- структура ---
    agency = add_unit(g["agency_name"], None, 0)
    plan: list[tuple[int, int | None, str, str, str]] = []  # (unit, department, title, fc, role)
    plan.append((agency, None, "Руководитель", FunctionCode.OTHER, HEAD))
    plan += [(agency, None, "Заместитель руководителя", FunctionCode.OTHER, DEPUTY_HEAD)] * 2

    sections: list[tuple[int, int, str, str]] = []  # (unit, department, tail, fc)
    for tail, fc, sec_tails in DEPARTMENTS[:n_dep]:
        dep = add_unit(f"Департамент {tail}", agency, 1)
        w.department_function[dep] = fc
        plan.append((dep, dep, f"Директор Департамента {tail}", fc, DIRECTOR))
        plan.append((dep, dep, f"Заместитель директора Департамента {tail}", fc, DEPUTY_DIRECTOR))
        for st in sec_tails[:n_sec]:
            sec = add_unit(f"Отдел {st}", dep, 2)
            sections.append((sec, dep, st, fc))
            plan.append((sec, dep, f"Начальник отдела {st}", fc, SECTION_HEAD))
            plan.append((sec, dep, f"Заместитель начальника отдела {st}", fc, SECTION_DEPUTY))

    # --- рядовые сотрудники: PROC добираем до proc_employees, остальное — по прочим отделам ---
    fixed_proc = sum(1 for p in plan if p[3] == FunctionCode.PROC)
    proc_secs = [s for s in sections if s[3] == FunctionCode.PROC]
    other_secs = [s for s in sections if s[3] != FunctionCode.PROC]
    proc_staff = g["proc_employees"] - fixed_proc if proc_secs else 0
    other_staff = g["employees"] - len(plan) - proc_staff
    if proc_staff < 0 or other_staff < 0:
        raise ValueError("слишком мало служащих для заданной структуры")

    def spread(total: int, secs: list) -> list[int]:
        if not secs:
            return []
        base, extra = divmod(total, len(secs))
        lucky = set(rng.sample(range(len(secs)), extra))
        return [base + (1 if i in lucky else 0) for i in range(len(secs))]

    for secs, total in ((proc_secs, proc_staff), (other_secs, other_staff)):
        for (sec, dep, st, fc), n in zip(secs, spread(total, secs)):
            for k in range(n):
                plan.append((sec, dep, f"{STAFF_TITLES[k % len(STAFF_TITLES)]} отдела {st}", fc, STAFF))

    # --- служащие ---
    plan.sort(key=lambda p: (p[0], ("HEAD DEPUTY_HEAD DIRECTOR DEPUTY_DIRECTOR SECTION_HEAD "
                                    "SECTION_DEPUTY STAFF").split().index(p[4])))
    assert w.names is not None
    for i, (unit, dep, title, fc, role) in enumerate(plan, start=1):
        pid = position(unit, title, fc, role)
        name = w.names.new()
        hired = random_date(rng, dt.date(2006, 1, 1), dt.date(2023, 12, 31))
        ds.employees.append(Employee(i, name.full, pid, hired.isoformat()))
        w.employees[i] = EmployeeInfo(i, name, pid, title, unit, dep, fc, role, _authorities(role, fc))


# --- удобные выборки для других модулей ---

def sections_of(w: World) -> list[int]:
    return [u.id for u in w.ds.units if u.level == 2]


def department_of_unit(w: World, unit_id: int) -> int | None:
    lvl = next(u.level for u in w.ds.units if u.id == unit_id)
    if lvl == 1:
        return unit_id
    if lvl == 2:
        return w.unit_parent[unit_id]
    return None


def employees_by_role(w: World, role: str, department_id: int | None = None) -> list[EmployeeInfo]:
    return [e for e in w.employees.values()
            if e.role == role and (department_id is None or e.department_id == department_id)]


def responsible_pool(w: World) -> list[EmployeeInfo]:
    """Кто может быть ответственным за закупку (контрактные управляющие)."""
    return [e for e in w.employees.values() if Action.RESPONSIBLE_PROC in e.actions]
