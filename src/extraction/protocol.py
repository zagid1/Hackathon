"""Парсер протокола закупочной комиссии -> сущности и связи (формат раздела 8 PLAN.md).

Правила по структуре документа, без привязки к конкретному шаблону:
* состав комиссии: ФИО + роль по ближайшему ключевому слову в строке (председатель, заместитель
  председателя, член, секретарь); подписи инициалами склеиваются с полными ФИО и берут их роль;
* участники: строка с одной организацией и суммой (в т.ч. строка таблицы «№ | Участник | ИНН | Цена»)
  -> связь BID;
* решение: строка со словами «победител», «заключить контракт», «заключается» -> WINNER и цена контракта;
* НМЦК: сумма в строке со словами «НМЦК» / «начальная (максимальная) цена».
"""

from __future__ import annotations

import re

from .common import assign_roles, entities_in, lines, link_initials
from .money import find_money
from .ner import extract_entities
from .requisites import find_requisites

DECISION_RE = re.compile(r"победител|заключить контракт|заключается", re.I)
NMCK_RE = re.compile(r"НМЦК|начальн\w*\s*\(максимальн", re.I)
REG_RE = re.compile(r"№\s*(\d{19})")


def money_key(v: float) -> str:
    return f"MONEY:{v:.2f}"


def parse_protocol(pages: list[str]) -> dict:
    entities: list[dict] = []
    relations: list[dict] = []
    number = None
    for page_no, text in enumerate(pages, start=1):
        if number is None and (m := REG_RE.search(text)):
            number = m.group(1)
        ner = extract_entities(text, page_no)
        reqs = [e for e in find_requisites(text, page_no) if e["type"] in ("INN", "OGRN")]
        money = []
        for ls, le, line in lines(text):
            for e in find_money(line, page_no, allow_bare=" | " in line):
                e["span"] = [e["span"][0] + ls, e["span"][1] + ls]
                money.append(e)
        persons = [e for e in ner if e["type"] == "PERSON"]
        orgs = [e for e in ner if e["type"] == "ORG" and e.get("source") == "rules"]

        roles = assign_roles(text, persons)
        for p in persons:
            r = roles.get(id(p))
            p["role"] = f"COMMISSION_{r}" if r and r != "LEADER" else "COMMISSION_MEMBER"

        for ls, le, line in lines(text):
            line_orgs = entities_in(orgs, ls, le)
            line_money = entities_in(money, ls, le)
            if DECISION_RE.search(line):
                for o in line_orgs:
                    o["role"] = "WINNER"
                    relations.append({"type": "WINNER", "from": f"ORG:{o['normalized']}",
                                      "to": f"PROCUREMENT:{number}", "page": page_no, "evidence_span": [ls, le]})
                for mo in line_money:
                    mo["role"] = "CONTRACT_PRICE"
            elif NMCK_RE.search(line):
                for mo in line_money:
                    mo["role"] = "NMCK"
            elif len(line_orgs) == 1 and line_money:
                o = line_orgs[0]
                o["role"] = "BIDDER"
                for mo in line_money:
                    mo["role"] = "BID"
                    relations.append({"type": "BID", "from": f"ORG:{o['normalized']}", "to": money_key(mo["normalized"]),
                                      "page": page_no, "evidence_span": [ls, le]})
        entities += persons + orgs + reqs + money

    people = [e for e in entities if e["type"] == "PERSON"]
    link_initials(people)
    role_by_name = {p["normalized"]: p["role"] for p in people if not p.get("linked") and "." not in p["value"]}
    for p in people:
        if p.get("linked"):
            p["role"] = role_by_name.get(p["normalized"], p["role"])
    for e in entities:
        e.pop("source", None)
    entities.sort(key=lambda e: (e["page"], e["span"][0], e["type"]))
    return {"doc_type": "PROTOCOL", "procurement_number": number, "entities": entities, "relations": relations}
