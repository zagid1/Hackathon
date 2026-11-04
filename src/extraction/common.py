"""Общие средства парсеров документов: строки с позициями, роли по ключевым словам, склейка инициалов."""

from __future__ import annotations

import re
from typing import Optional

ROLE_RE = re.compile(
    r"(?P<DEPUTY_CHAIR>заместител\w*\s+председател\w*)"
    r"|(?P<CHAIR>председател\w*)"
    r"|(?P<SECRETARY>секретар\w*)"
    r"|(?P<MEMBER>член\w*)"
    r"|(?P<LEADER>руководител\w*)",
    re.IGNORECASE)


def lines(page_text: str) -> list[tuple[int, int, str]]:
    """Строки страницы с позициями [start, end)."""
    out, pos = [], 0
    for line in page_text.split("\n"):
        out.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return out


def entities_in(ents: list[dict], start: int, end: int, etype: Optional[str] = None) -> list[dict]:
    return [e for e in ents if start <= e["span"][0] and e["span"][1] <= end and (etype is None or e["type"] == etype)]


def _keyword(segment: str, last: bool) -> Optional[str]:
    ms = list(ROLE_RE.finditer(segment))
    if not ms:
        return None
    m = ms[-1] if last else ms[0]
    return m.lastgroup


# Роль, приписанная справа к ФИО: «Иванов И. И. — секретарь», «Иванов И. И. (председатель)», «… | член комиссии».
# Запятая не считается: в «председатель А, заместитель председателя Б» роль после запятой относится к Б.
_RIGHT_ATTACHED = re.compile(r"^\s*(?:—|–|-|\(|\|)\s*([^,;()|]{0,40})")


def assign_roles(page_text: str, persons: list[dict]) -> dict[int, Optional[str]]:
    """Роль каждого лица (по id(entity)), по убыванию приоритета: ключевое слово сразу справа после «—», «(»
    или «|»; ближайшее ключевое слово слева (после предыдущего лица); роль предыдущего лица той же строки
    («члены комиссии А и Б»); любое ключевое слово справа до следующего лица."""
    roles: dict[int, Optional[str]] = {}
    for ls, le, _ in lines(page_text):
        in_line = sorted(entities_in(persons, ls, le), key=lambda e: e["span"][0])
        prev_end, prev_role = ls, None
        for i, e in enumerate(in_line):
            s, t = e["span"]
            nxt = in_line[i + 1]["span"][0] if i + 1 < len(in_line) else le
            right = page_text[t:nxt]
            m_right = _RIGHT_ATTACHED.match(right)
            role = ((m_right and _keyword(m_right.group(1), last=False))
                    or _keyword(page_text[prev_end:s], last=True) or prev_role or _keyword(right, last=False))
            roles[id(e)] = role
            prev_end, prev_role = t, role
    return roles


def _initials_key(normalized: str) -> Optional[tuple[str, str, str]]:
    m = re.fullmatch(r"(\S+) ([А-ЯЁ])\. ([А-ЯЁ])\.", normalized)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def link_initials(persons: list[dict]) -> None:
    """«Иванов И. П.» -> полное ФИО, если в том же документе есть «Иванов Иван Петрович»
    (с учётом рода фамилии: «Антонова В. А.» ↔ «Антонова Вера Андреевна»). Меняет normalized на месте,
    добавляет linked=True. При нескольких кандидатах оставляет инициалы."""
    full: dict[tuple[str, str, str], set[str]] = {}
    for p in persons:
        parts = p["normalized"].split()
        if len(parts) == 3 and not p["normalized"].endswith("."):
            full.setdefault((parts[0], parts[1][0], parts[2][0]), set()).add(p["normalized"])
    for p in persons:
        key = _initials_key(p["normalized"])
        if key and len(full.get(key, ())) == 1:     # неоднозначные инициалы не склеиваем
            p["normalized"] = next(iter(full[key]))
            p["linked"] = True
