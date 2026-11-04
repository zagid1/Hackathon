"""Парсер приказа о создании комиссии / рабочей / проектной группы -> сущности и связи.

* вид группы и название — из заголовка («О создании …», «об утверждении состава …», «… создать … в составе»);
* номер и дата приказа;
* участники: полные ФИО + роль по ближайшему ключевому слову в строке (председатель, заместитель
  председателя, руководитель, член, секретарь) -> связь MEMBER с группой;
* внешние участники: организация в той же строке после ФИО -> связь AFFILIATION;
* лицо инициалами без пары в документе — подписант приказа (SIGNATORY).
"""

from __future__ import annotations

import re
from typing import Optional

from .common import assign_roles, entities_in, lines, link_initials
from .ner import extract_entities

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
NUMBER_RE = re.compile(r"№\s*([\w\-/]+)")
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})|«(\d{1,2})»\s+([а-я]+)\s+(\d{4})")
TITLE_RE = re.compile(r"(?:О создании|об утверждении состава|приказываю создать)\s+(.+?)(?:\s+в составе.*)?\.?$",
                      re.IGNORECASE)
HEADS = {  # родительный/винительный -> именительный
    "единой комиссии": "Единая комиссия", "единую комиссию": "Единая комиссия",
    "рабочей группы": "Рабочая группа", "рабочую группу": "Рабочая группа",
    "проектной группы": "Проектная группа", "проектную группу": "Проектная группа",
}
KINDS = {"комисси": "COMMISSION", "рабоч": "WORKGROUP", "проектн": "PROJECT"}


def _date(text: str) -> Optional[str]:
    m = DATE_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    month = MONTHS.get(m.group(5))
    return f"{m.group(6)}-{month:02d}-{int(m.group(4)):02d}" if month else None


def _group_name(pages: list[str]) -> tuple[Optional[str], Optional[str]]:
    for text in pages:
        for _, _, line in lines(text):
            m = TITLE_RE.search(line)
            if not m:
                continue
            name = m.group(1).strip().rstrip(".")
            for head, nom in HEADS.items():
                if name.lower().startswith(head):
                    name = nom + name[len(head):]
                    break
            kind = next((k for key, k in KINDS.items() if key in name.lower()), None)
            return name, kind
    return None, None


def parse_order(pages: list[str]) -> dict:
    first = pages[0] if pages else ""
    number = None
    for _, _, line in lines(first):          # номер приказа — в строке с датой (не «комиссия № 2» из названия)
        if DATE_RE.search(line) and (m := NUMBER_RE.search(line)):
            number = m.group(1)
            break
    date = _date(first)
    name, kind = _group_name(pages)
    prefix = kind or "GROUP"
    group_ref = f"GROUP:{name}" if name else "GROUP:?"

    entities: list[dict] = []
    relations: list[dict] = []
    for page_no, text in enumerate(pages, start=1):
        ner = extract_entities(text, page_no)
        persons = [e for e in ner if e["type"] == "PERSON"]
        orgs = [e for e in ner if e["type"] == "ORG" and e.get("source") == "rules"]
        roles = assign_roles(text, persons)
        for p in persons:
            r = roles.get(id(p))
            if "." in p["value"]:
                p["role"] = "SIGNATORY"
            else:
                p["role"] = f"{prefix}_{r or 'MEMBER'}"
        for ls, le, line in lines(text):
            line_people = sorted(entities_in(persons, ls, le), key=lambda e: e["span"][0])
            for i, p in enumerate(line_people):
                if p["role"] == "SIGNATORY":
                    continue
                relations.append({"type": "MEMBER", "from": f"PERSON:{p['normalized']}", "to": group_ref,
                                  "role": p["role"].split("_", 1)[1], "page": page_no, "evidence_span": [ls, le]})
                nxt = line_people[i + 1]["span"][0] if i + 1 < len(line_people) else le
                for o in entities_in(orgs, p["span"][1], nxt):
                    o["role"] = "AFFILIATION"
                    relations.append({"type": "AFFILIATION", "from": f"PERSON:{p['normalized']}",
                                      "to": f"ORG:{o['normalized']}", "page": page_no, "evidence_span": [ls, le]})
        entities += persons + orgs

    people = [e for e in entities if e["type"] == "PERSON"]
    link_initials(people)
    for p in people:
        if p.get("linked") and p["role"] == "SIGNATORY":
            p["role"] = next((q["role"] for q in people if q["normalized"] == p["normalized"] and not q.get("linked")),
                             p["role"])
    for e in entities:
        e.pop("source", None)
    entities.sort(key=lambda e: (e["page"], e["span"][0], e["type"]))
    return {"doc_type": "ORDER", "order_number": number, "order_date": date, "group_name": name,
            "group_kind": kind, "entities": entities, "relations": relations}
