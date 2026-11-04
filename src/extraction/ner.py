"""Извлечение ФИО и организаций: правила + pymorphy3 + Natasha.

* PERSON, полное ФИО «Фамилия Имя Отчество» в любом падеже — правило (третье слово — отчество,
  подтверждённое pymorphy3) + нормализация каждого слова в именительный падеж с учётом рода
  (род берётся из отчества). Natasha на таких спанах ошибается границами примерно в четверти случаев.
* PERSON с инициалами («И.И. Иванов», «Иванов И. И.») — правило; normalized = «Иванов И. И.»: восстановить полное ФИО можно только сопоставлением
  со списком лиц (парсер протокола/приказа, Этап 3); нормальная форма Natasha портит фамилии
  («Яблонская» -> «Яблонскай»).
* PERSON, прочие (ФИО без отчества и т. п.) — спаны Natasha.
* ORG — правило: «ООО/АО/ПАО/ЗАО/ОАО «...»» и полные формы в разных падежах; normalized как в
  разделе 8: «ООО РОМАШКА». Прочие ORG-спаны Natasha (органы власти и т. п.) — с normalized = исходный текст.
* Буква «ё» в normalized заменяется на «е».

Совместимость: natasha==1.6.0 импортирует pymorphy2, который не работает на Python >= 3.11
(pkg_resources, inspect.getargspec). При импорте этого модуля pymorphy2 подменяется pymorphy3 —
форком с тем же API. Модели Natasha и словари входят в пакеты, сеть не нужна; результат детерминирован.
"""

from __future__ import annotations

import importlib
import re
import sys
import threading
from typing import Optional


def _install_pymorphy_shim() -> None:
    if getattr(sys.modules.get("pymorphy2"), "__name__", "") == "pymorphy3":
        return
    for name in ("", ".analyzer", ".units", ".units.base", ".tagset"):
        sys.modules["pymorphy2" + name] = importlib.import_module("pymorphy3" + name)


_install_pymorphy_shim()   # до любого импорта natasha

_LOCK = threading.Lock()
_MODELS: Optional[dict] = None

_FORMS = {
    "ООО": "ООО", "АО": "АО", "ПАО": "ПАО", "ЗАО": "ЗАО", "ОАО": "ОАО",
    "Общество с ограниченной ответственностью": "ООО", "Обществом с ограниченной ответственностью": "ООО",
    "Общества с ограниченной ответственностью": "ООО",
    "Акционерное общество": "АО", "Акционерным обществом": "АО", "Акционерного общества": "АО",
    "Публичное акционерное общество": "ПАО", "Публичным акционерным обществом": "ПАО",
    "Публичного акционерного общества": "ПАО",
}
_FORMS_LOWER = {k.lower(): v for k, v in _FORMS.items()}
# ОПФ в любом регистре («ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ»), кавычки «», "", “”, „“.
_ORG_RE = re.compile(
    "(?<![А-Яа-яЁё])(" + "|".join(re.escape(f) for f in sorted(_FORMS, key=len, reverse=True)) + ")"
    r"[\s\u00a0]*(?:«([^«»]{1,120})»|[\"“„]([^\"“”„«»]{1,120})[\"”“])", re.IGNORECASE)
_WORD = r"[А-ЯЁ][а-яё]+"
_FIO_RE = re.compile(rf"(?<![А-Яа-яЁё])({_WORD}(?:-{_WORD})?)\s+({_WORD})\s+"
                     rf"([А-ЯЁ][а-яё]*(?:вич|вн|ич|чн|шн)[а-яё]{{0,3}})(?![А-Яа-яЁё])")
_ROLES = ("Surn", "Name", "Patr")
_SURNAME = rf"{_WORD}(?:-{_WORD})?"
_INIT = r"[А-ЯЁ]\.\s?[А-ЯЁ]\."
_INITIALS_RE = re.compile(rf"(?<![А-Яа-яЁё.])(?:({_INIT})\s?({_SURNAME})|({_SURNAME})\s({_INIT}))(?![А-Яа-яЁё])")
_NOT_SURNAMES = {"Руководитель", "Председатель", "Секретарь", "Член", "Заместитель", "Директор", "Начальник",
                 "Консультант", "Подписи", "Комиссия", "Приказ", "Протокол"}
# Natasha иногда считает организациями служебные слова документов.
_ORG_STOP = ("комисси", "нмцк", "секретар", "председател", "член ", "заказчик", "участник", "протокол", "приказ")

# Запасная нормализация фамилий, которых нет в словаре pymorphy3: (окончание, замена) по роду.
_SURNAME_FALLBACK = {
    "femn": (("ской", "ская"), ("скую", "ская"), ("цкой", "цкая"), ("цкую", "цкая"), ("овой", "ова"), ("ову", "ова"),
             ("евой", "ева"), ("еву", "ева"), ("иной", "ина"), ("ину", "ина"), ("ыной", "ына"), ("ыну", "ына")),
    "masc": (("ского", "ский"), ("скому", "ский"), ("ским", "ский"), ("цкого", "цкий"), ("цкому", "цкий"),
             ("цким", "цкий"), ("ова", "ов"), ("ову", "ов"), ("овым", "ов"), ("ева", "ев"), ("еву", "ев"),
             ("евым", "ев"), ("ина", "ин"), ("ину", "ин"), ("иным", "ин"), ("ына", "ын"), ("ыну", "ын")),
}


def _models() -> dict:
    global _MODELS
    with _LOCK:
        if _MODELS is None:
            from natasha import (MorphVocab, NamesExtractor, NewsEmbedding, NewsNERTagger,
                                 Segmenter)
            emb = NewsEmbedding()
            vocab = MorphVocab()   # подкласс pymorphy3.MorphAnalyzer с граммемами UD
            import pymorphy3
            _MODELS = {"segmenter": Segmenter(), "vocab": vocab,
                       "ner": NewsNERTagger(emb), "names": NamesExtractor(vocab),
                       "pymorphy": pymorphy3.MorphAnalyzer()}   # «чистые» граммемы OpenCorpora
        return _MODELS


def _yo(s: str) -> str:
    return s.replace("ё", "е").replace("Ё", "Е")


def normalize_org(form: str, core: str) -> str:
    return _yo(f"{_FORMS_LOWER[form.lower()]} {core.strip().upper()}")


def normalize_fio(surname: str, name: str, patronymic: str) -> Optional[str]:
    """ФИО в любом падеже -> именительный. None, если третье слово не отчество."""
    morph = _models()["pymorphy"]
    patr = [p for p in morph.parse(patronymic) if "Patr" in p.tag]
    if not patr:
        return None
    gender = patr[0].tag.gender
    out = []
    for word, role in zip((surname, name, patronymic), _ROLES):
        parses = [p for p in morph.parse(word) if role in p.tag]
        same = [p for p in parses if p.tag.gender == gender or "Ms-f" in p.tag]
        parses = sorted(same or parses, key=lambda p: "plur" in p.tag)   # единственное число — первым
        if not parses and role == "Surn":
            out.append(_surname_fallback(word, gender))
            continue
        if not parses:                           # имени нет в словаре — по окончаниям
            out.append(_name_fallback(word, gender) if role == "Name" else word)
            continue
        p = parses[0]
        inflected = p.inflect({"nomn", "sing", gender}) if gender else None
        inflected = inflected or p.inflect({"nomn", "sing"}) or p.inflect({"nomn"})
        out.append((inflected.word if inflected else p.normal_form).capitalize())
    return _yo(" ".join(out))


def _surname_fallback(word: str, gender: Optional[str]) -> str:
    for end, repl in _SURNAME_FALLBACK.get(gender or "", ()):
        if word.endswith(end):
            return word[: -len(end)] + repl
    return word


def _name_fallback(word: str, gender: Optional[str]) -> str:
    """Женские имена 1-го склонения (Алины, Алине, Алину -> Алина); мужские не трогаем."""
    if gender != "femn":
        return word
    for end, repl in (("ии", "ия"), ("ию", "ия"), ("ьи", "ья"), ("ье", "ья"), ("ью", "ья"),
                      ("ы", "а"), ("у", "а"), ("ю", "я"), ("е", "а")):
        if word.endswith(end):
            return word[: -len(end)] + repl
    if word.endswith("и") and len(word) > 2 and word[-2] in "гкхжчшщ":
        return word[:-1] + "а"
    return word


_SURNAME_ENDINGS = re.compile(r"(?:ов|ев|ёв|ин|ын|ова|ева|ёва|ина|ына|ский|цкий|ская|цкая|ко|их|ых|ук|юк|ян|дзе|швили)$")


def _looks_like_surname(word: str) -> bool:
    """Слово перед инициалами («Иванов И. И.») — фамилия, а не должность («Министр А.В. ...»)."""
    if _SURNAME_ENDINGS.search(word.lower()):
        return True
    return any("Surn" in p.tag for p in _models()["pymorphy"].parse(word))


def find_initials(text: str, page: int = 1) -> list[dict]:
    """«И.И. Иванов» и «Иванов И. И.»; normalized = «Иванов И. И.» (фамилия — как в тексте)."""
    out = []
    pos = 0
    while (m := _INITIALS_RE.search(text, pos)) is not None:
        init, surname = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if surname in _NOT_SURNAMES or (m.group(3) and not _looks_like_surname(surname)):
            pos = m.start() + 1           # «Руководитель Л.С.», «Министр А.В. Ларин» — ищем дальше
            continue
        pos = m.end()
        letters = re.findall(r"[А-ЯЁ]", init)
        out.append({"type": "PERSON", "value": m.group(0), "normalized": _yo(f"{surname} {letters[0]}. {letters[1]}."),
                    "page": page, "span": [m.start(), m.end()], "source": "rules"})
    return out


def find_orgs(text: str, page: int = 1) -> list[dict]:
    return [{"type": "ORG", "value": m.group(0), "normalized": normalize_org(m.group(1), m.group(2) or m.group(3)),
             "page": page, "span": [m.start(), m.end()], "source": "rules"}
            for m in _ORG_RE.finditer(text)]


def find_full_names(text: str, page: int = 1) -> list[dict]:
    out = []
    for m in _FIO_RE.finditer(text):
        norm = normalize_fio(m.group(1), m.group(2), m.group(3))
        if norm:
            out.append({"type": "PERSON", "value": m.group(0), "normalized": norm, "page": page,
                        "span": [m.start(), m.end()], "source": "rules"})
    return out


def _overlaps(span: list[int], taken: list[list[int]]) -> bool:
    return any(span[0] < e and s < span[1] for s, e in taken)


def find_natasha(text: str, page: int = 1, skip: Optional[list[list[int]]] = None) -> list[dict]:
    from natasha import Doc

    m = _models()
    skip = skip or []
    doc = Doc(text)
    doc.segment(m["segmenter"])
    doc.tag_ner(m["ner"])          # морфология не нужна: нормализуем ФИО сами, а не через span.normalize
    out = []
    for span in doc.spans:
        sp = [span.start, span.stop]
        if _overlaps(sp, skip):
            continue
        if span.type == "PER":
            out.append({"type": "PERSON", "value": span.text, "normalized": _yo(span.text), "page": page,
                        "span": sp, "source": "natasha"})
        elif span.type == "ORG" and not span.text.lower().startswith(_ORG_STOP):
            out.append({"type": "ORG", "value": span.text, "normalized": _yo(span.text), "page": page,
                        "span": sp, "source": "natasha"})
    return out


_IP_RE = re.compile(r"(?<![А-Яа-яЁё])(Индивидуальн(?:ый|ым|ого)\s+предпринимател(?:ь|ем|я)|ИП)[\s\u00a0]+",
                    re.IGNORECASE)


def find_individual_entrepreneurs(text: str, page: int = 1, full_names: Optional[list[dict]] = None) -> list[dict]:
    """«Индивидуальный предприниматель Борисов Кирилл Андреевич», «ИП Борисов К. А.» -> ORG «ИП БОРИСОВ КИРИЛЛ
    АНДРЕЕВИЧ» (ФИО — в именительном падеже). Сам ФИО в таком случае не считается отдельным лицом."""
    names = full_names if full_names is not None else find_full_names(text, page)
    initials = find_initials(text, page)
    out = []
    for m in _IP_RE.finditer(text):
        person = next((e for e in names + initials if e["span"][0] == m.end()), None)
        if person is None:
            continue
        out.append({"type": "ORG", "value": text[m.start():person["span"][1]],
                    "normalized": _yo(f"ИП {person['normalized'].upper()}"), "page": page,
                    "span": [m.start(), person["span"][1]], "source": "rules"})
    return out


def extract_entities(text: str, page: int = 1) -> list[dict]:
    """PERSON и ORG на странице, отсортированные по позиции. Наименования организаций (в т.ч. ИП)
    имеют приоритет: ФИО внутри наименования ИП отдельным лицом не считается."""
    full = find_full_names(text, page)
    orgs = find_orgs(text, page) + find_individual_entrepreneurs(text, page, full)
    org_spans = [o["span"] for o in orgs]
    rules = orgs + [e for e in full if not _overlaps(e["span"], org_spans)]
    taken = [e["span"] for e in rules]
    rules += [e for e in find_initials(text, page) if not _overlaps(e["span"], taken)]
    found = rules + find_natasha(text, page, [e["span"] for e in rules])
    return sorted(found, key=lambda e: (e["span"][0], e["span"][1], e["type"]))
