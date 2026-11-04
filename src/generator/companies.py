"""Организации-контрагенты: рынки (по 2 знакам ОКПД2), ИНН/ОГРН с верными контрольными суммами,
руководители и учредители."""

from __future__ import annotations

import datetime as dt
import math
import random

from src.models.entities import Organization, OrgRole

from .common import Market, OrgInfo, World, random_date
from .people import add_person

# Узкие рынки (71, 72, 86, 33) — мало поставщиков, единственная заявка там норма (честный шум для И3).
MARKETS: tuple[Market, ...] = (
    Market("26", "Компьютерное и электронное оборудование",
           (("26.20.11.110", "Поставка ноутбуков"), ("26.20.15.000", "Поставка персональных компьютеров"),
            ("26.30.11.110", "Поставка средств связи")),
           "46.51", (150_000, 8_000_000), (0.10, 0.22, 0.28, 0.22, 0.12, 0.06), 0.13, 0.12),
    Market("58", "Программное обеспечение",
           (("58.29.29.000", "Поставка лицензий на программное обеспечение"),
            ("58.29.31.000", "Поставка средств защиты информации")),
           "58.29", (100_000, 6_000_000), (0.20, 0.30, 0.28, 0.15, 0.07), 0.09, 0.08),
    Market("62", "Услуги в области информационных технологий",
           (("62.01.11.000", "Разработка программного обеспечения"),
            ("62.02.30.000", "Техническая поддержка информационных систем"),
            ("62.03.12.130", "Сопровождение информационной инфраструктуры")),
           "62.01", (300_000, 15_000_000), (0.18, 0.30, 0.27, 0.17, 0.08), 0.12, 0.12, 0.25),
    Market("17", "Бумага и канцелярские товары",
           (("17.12.14.110", "Поставка бумаги для офисной техники"),
            ("17.23.13.191", "Поставка канцелярских принадлежностей")),
           "46.49", (50_000, 1_500_000), (0.08, 0.17, 0.25, 0.25, 0.15, 0.10), 0.09, 0.11),
    Market("43", "Ремонтные и строительные работы",
           (("43.31.10.000", "Выполнение штукатурных работ"),
            ("43.39.19.190", "Текущий ремонт помещений")),
           "43.39", (500_000, 25_000_000), (0.12, 0.25, 0.28, 0.20, 0.10, 0.05), 0.10, 0.12, 0.15),
    Market("81", "Уборка помещений",
           (("81.21.10.000", "Оказание услуг по уборке помещений"),),
           "81.21", (300_000, 6_000_000), (0.10, 0.22, 0.30, 0.23, 0.15), 0.06, 0.08),
    Market("80", "Охранные услуги",
           (("80.10.12.000", "Оказание услуг охраны"),),
           "80.10", (400_000, 8_000_000), (0.20, 0.32, 0.28, 0.15, 0.05), 0.05, 0.06),
    Market("49", "Транспортные услуги",
           (("49.32.11.000", "Оказание услуг по перевозке пассажиров"),
            ("49.39.11.000", "Оказание транспортных услуг")),
           "49.32", (200_000, 4_000_000), (0.22, 0.32, 0.26, 0.14, 0.06), 0.06, 0.07),
    Market("71", "Технические испытания и экспертиза",
           (("71.20.19.190", "Проведение технической экспертизы"),),
           "71.20", (200_000, 5_000_000), (0.55, 0.30, 0.15), 0.07, 0.04),
    Market("72", "Научные исследования и разработки",
           (("72.19.29.110", "Выполнение научно-исследовательской работы"),
            ("72.20.29.000", "Проведение прикладных исследований")),
           "72.19", (500_000, 12_000_000), (0.60, 0.28, 0.12), 0.06, 0.04, 0.40),
    Market("33", "Ремонт и обслуживание оборудования",
           (("33.12.19.000", "Техническое обслуживание оборудования"),
            ("33.14.11.000", "Ремонт электрооборудования")),
           "33.12", (100_000, 3_000_000), (0.40, 0.32, 0.18, 0.10), 0.09, 0.07),
    Market("86", "Медицинские услуги",
           (("86.21.10.120", "Оказание услуг по диспансеризации служащих"),),
           "86.21", (200_000, 3_000_000), (0.50, 0.32, 0.18), 0.08, 0.05),
)

ROOTS = (
    "Вектор", "Меридиан", "Гарант", "Прогресс", "Импульс", "Альфа", "Сигма", "Орион", "Атлант", "Лидер",
    "Стандарт", "Партнер", "Регион", "Феникс", "Горизонт", "Квант", "Монолит", "Эталон", "Север",
    "Восток", "Аврора", "Бастион", "Гранит", "Витязь", "Зенит", "Интеграл", "Континент", "Магистраль",
    "Навигатор", "Олимп", "Пульсар", "Ресурс", "Спектр", "Триумф", "Фортуна", "Цитадель", "Эверест",
    "Янтарь", "Дельта", "Омега", "Вега", "Ладога", "Байкал", "Алтай", "Урал", "Кедр", "Ирбис", "Сокол",
)

SUFFIXES = {
    "26": ("Технологии", "Компьютерс", "Электроника", "Системс"),
    "58": ("Софт", "Лаб", "Информ"),
    "62": ("АйТи", "Интеграция", "Диджитал", "Инфосистемы"),
    "17": ("Офис", "Канцторг", "Снаб"),
    "43": ("Строй", "СтройМонтаж", "Ремонт"),
    "81": ("Клининг", "Чистота", "Сервис"),
    "80": ("Охрана", "Щит", "Безопасность"),
    "49": ("Транс", "Авто", "Логистик"),
    "71": ("Эксперт", "Лаборатория", "Тест"),
    "72": ("НИЦ", "Наука", "Исследования"),
    "33": ("Техсервис", "Ремсервис", "Инжиниринг"),
    "86": ("Медика", "Мед", "Клиник"),
}

LEGAL_FORMS = (("ООО", 0.8), ("АО", 0.15), ("ПАО", 0.05))
LEGAL_FORM_FULL = {
    "ООО": "Общество с ограниченной ответственностью",
    "АО": "Акционерное общество",
    "ПАО": "Публичное акционерное общество",
}
LEGAL_FORM_FULL_INS = {   # творительный падеж: «заключить контракт с Обществом ...»
    "ООО": "Обществом с ограниченной ответственностью",
    "АО": "Акционерным обществом",
    "ПАО": "Публичным акционерным обществом",
}
INN_PREFIXES = ("7701", "7704", "7707", "7714", "7718", "7725", "7731", "7743", "5003", "5024",
                "5027", "7802", "7810", "6658", "5260", "1655", "6164", "5406")

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)


def inn10_check_digit(first9: str) -> int:
    return sum(int(d) * k for d, k in zip(first9, _INN10_WEIGHTS)) % 11 % 10


def is_valid_inn10(inn: str) -> bool:
    return len(inn) == 10 and inn.isdigit() and inn10_check_digit(inn[:9]) == int(inn[9])


def ogrn_check_digit(first12: str) -> int:
    return int(first12) % 11 % 10


def is_valid_ogrn(ogrn: str) -> bool:
    return len(ogrn) == 13 and ogrn.isdigit() and ogrn_check_digit(ogrn[:12]) == int(ogrn[12])


def make_inn(rng: random.Random) -> str:
    first9 = rng.choice(INN_PREFIXES) + f"{rng.randint(0, 99_999):05d}"
    return first9 + str(inn10_check_digit(first9))


def make_ogrn(rng: random.Random, inn: str, registered: dt.date) -> str:
    first12 = "1" + f"{registered.year % 100:02d}" + inn[:2] + inn[2:4] + f"{rng.randint(0, 99_999):05d}"
    return first12 + str(ogrn_check_digit(first12))


def normalize_org_name(legal_form: str, core: str) -> str:
    """Нормализованное имя, как в контракте раздела 8: «ООО «Ромашка»» -> «ООО РОМАШКА»."""
    return f"{legal_form} {core.upper()}"


def _allocate(total: int, shares: list[float]) -> list[int]:
    """Целочисленное распределение по долям методом наибольшего остатка.
    math.fsum, а не sum: в Python 3.12 sum() для float считает иначе, чем в 3.11."""
    s = math.fsum(shares)
    raw = [total * x / s for x in shares]
    out = [int(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - out[i]), i))
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def build_companies(w: World) -> None:
    rng = w.rng("companies")
    w.markets = {m.code: m for m in MARKETS}
    n_orgs = w.gen["organizations"]
    counts = _allocate(n_orgs, [m.org_share for m in MARKETS])

    used_names: set[str] = set()
    used_inn: set[str] = set()
    oid = 0
    for market, cnt in zip(MARKETS, counts):
        for k in range(cnt):
            oid += 1
            form = rng.choices([f for f, _ in LEGAL_FORMS], [p for _, p in LEGAL_FORMS])[0]
            while True:
                root, suf = rng.choice(ROOTS), rng.choice(SUFFIXES[market.code])
                core = rng.choice((f"{root}-{suf}", f"{root} {suf}", f"{root}{suf.lower()}"))
                if core not in used_names:
                    used_names.add(core)
                    break
            while True:
                inn = make_inn(rng)
                if inn not in used_inn:
                    used_inn.add(inn)
                    break
            registered = random_date(rng, dt.date(2002, 1, 1), dt.date(2022, 12, 31))
            ogrn = make_ogrn(rng, inn, registered)
            markets = [market.code]
            if rng.random() < 0.25:
                markets.append(rng.choice([m.code for m in MARKETS if m.code != market.code]))
            info = OrgInfo(oid, f"{form} «{core}»", form, core, inn, ogrn, markets,
                           major=(k == 0 and cnt >= 5))
            w.orgs[oid] = info
            w.ds.organizations.append(
                Organization(oid, info.name, inn, ogrn, market.okved, registered.isoformat()))

    # руководители и учредители
    for oid in sorted(w.orgs):
        director = add_person(w)
        w.org_director[oid] = director
        founders = []
        if rng.random() < 0.5:
            founders.append(director)
        if not founders or rng.random() < 0.5:
            founders.append(add_person(w))
        w.org_founders[oid] = founders


def set_director(w: World, org_id: int, person_id: int, also_founder: bool = False) -> None:
    """Делает лицо директором фирмы (прежний директор остаётся в учредителях, если был им)."""
    w.org_director[org_id] = person_id
    if also_founder and person_id not in w.org_founders[org_id]:
        w.org_founders[org_id].append(person_id)


def emit_org_roles(w: World) -> None:
    rows = set()
    for oid, pid in w.org_director.items():
        rows.add((oid, pid, "DIRECTOR"))
    for oid, pids in w.org_founders.items():
        for pid in pids:
            rows.add((oid, pid, "FOUNDER"))
    w.ds.org_roles = [OrgRole(*r) for r in sorted(rows)]


def orgs_in_market(w: World, code: str) -> list[OrgInfo]:
    return [o for o in w.orgs.values() if code in o.markets]


def affiliated_persons(w: World, org_id: int) -> set[int]:
    return {w.org_director[org_id], *w.org_founders[org_id]}
