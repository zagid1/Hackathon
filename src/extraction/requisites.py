"""Реквизиты в тексте: ИНН (10/12), ОГРН (13) / ОГРНИП (15), БИК, расчётный и корреспондентский счёт.

Детерминированно: регулярные выражения + контрольные суммы.
* ИНН ЮЛ (10): веса 2,4,10,3,5,9,4,6,8; контрольная = сумма % 11 % 10.
* ИНН ФЛ/ИП (12): две контрольные цифры, веса 7,2,4,10,3,5,9,4,6,8 и 3,7,2,4,10,3,5,9,4,6,8.
* ОГРН (13): контрольная = первые 12 цифр % 11 % 10; ОГРНИП (15): первые 14 % 13 % 10.
* БИК: 9 цифр, начинается с «04» (банки РФ).
* Счёт (20 цифр) проверяется по ключу вместе с БИК: веса 7,1,3 по 23 цифрам, сумма % 10 == 0.
  Для расчётного счёта префикс — 3 последние цифры БИК, для корреспондентского — «0» + 5–6 цифры БИК.

Тип числа определяется ключевым словом слева («ИНН», «ОГРН», «БИК», «р/с», «к/с» ...); без ключевого
слова 10/12/13/15-значное число с верной контрольной суммой считается ИНН/ОГРН соответственно.
Формат выхода — как сущности в контракте раздела 8 PLAN.md.
"""

from __future__ import annotations

import re
from typing import Optional

_INN10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_ACCOUNT_W = (7, 1, 3)


def _check(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return _check(inn, _INN10) == int(inn[9])
    if len(inn) == 12:
        return _check(inn, _INN12_1) == int(inn[10]) and _check(inn, _INN12_2) == int(inn[11])
    return False


def is_valid_ogrn(ogrn: str) -> bool:
    if not ogrn.isdigit():
        return False
    if len(ogrn) == 13:
        return int(ogrn[:12]) % 11 % 10 == int(ogrn[12])
    if len(ogrn) == 15:
        return int(ogrn[:14]) % 13 % 10 == int(ogrn[14])
    return False


def is_valid_bik(bik: str) -> bool:
    return len(bik) == 9 and bik.isdigit() and bik.startswith("04")


def _account_key_ok(prefix: str, account: str) -> bool:
    s = prefix + account
    return sum(int(d) * _ACCOUNT_W[i % 3] for i, d in enumerate(s)) % 10 == 0


def is_valid_settlement_account(account: str, bik: str) -> bool:
    """Расчётный счёт в банке с данным БИК."""
    return (len(account) == 20 and account.isdigit() and is_valid_bik(bik)
            and _account_key_ok(bik[-3:], account))


def is_valid_corr_account(account: str, bik: str) -> bool:
    """Корреспондентский счёт банка (в подразделении ЦБ)."""
    return (len(account) == 20 and account.isdigit() and is_valid_bik(bik)
            and _account_key_ok("0" + bik[4:6], account))


# Ключевые слова слева от числа (до 20 символов).
_KEYWORDS = (
    ("BIK", re.compile(r"БИК", re.I)),
    ("OGRN", re.compile(r"ОГРН(?:ИП)?", re.I)),
    ("INN", re.compile(r"ИНН", re.I)),
    ("CORR_ACCOUNT", re.compile(r"к/с|кор(?:р)?\.?\s*сч|корреспондентск", re.I)),
    ("ACCOUNT", re.compile(r"р/с|рас(?:ч)?\.?\s*сч|расч[её]тн|сч[её]т", re.I)),
    ("KPP", re.compile(r"КПП", re.I)),
)
_NUMBER = re.compile(r"(?<!\d)\d{9,20}(?!\d)")


def _keyword_type(text: str, start: int) -> Optional[str]:
    left = text[max(0, start - 20):start]
    best: Optional[tuple[int, str]] = None
    for t, rx in _KEYWORDS:
        for m in rx.finditer(left):
            if best is None or m.end() > best[0]:
                best = (m.end(), t)
    return best[1] if best else None


def find_requisites(text: str, page: int = 1) -> list[dict]:
    """Все реквизиты на странице. Счета проверяются по ключу с ближайшим БИК в том же тексте."""
    found: list[dict] = []
    for m in _NUMBER.finditer(text):
        num, start, end = m.group(), m.start(), m.end()
        kw = _keyword_type(text, start)
        etype: Optional[str] = None
        if kw == "KPP":
            continue
        if kw in ("INN",) and len(num) in (10, 12):
            etype = "INN"
        elif kw == "OGRN" and len(num) in (13, 15):
            etype = "OGRN"
        elif kw == "BIK" and len(num) == 9:
            etype = "BIK"
        elif kw in ("ACCOUNT", "CORR_ACCOUNT") and len(num) == 20:
            etype = kw
        elif kw is None:
            if len(num) in (10, 12) and is_valid_inn(num):
                etype = "INN"
            elif len(num) in (13, 15) and is_valid_ogrn(num):
                etype = "OGRN"
        if etype is None:
            continue
        found.append({"type": etype, "value": num, "page": page, "span": [start, end]})

    biks = [e for e in found if e["type"] == "BIK"]
    for e in found:
        t, v = e["type"], e["value"]
        if t == "INN":
            e["valid_checksum"] = is_valid_inn(v)
        elif t == "OGRN":
            e["valid_checksum"] = is_valid_ogrn(v)
        elif t == "BIK":
            e["valid_checksum"] = is_valid_bik(v)
        else:
            bik = min(biks, key=lambda b: abs(b["span"][0] - e["span"][0]))["value"] if biks else None
            check = is_valid_settlement_account if t == "ACCOUNT" else is_valid_corr_account
            e["valid_checksum"] = bool(bik) and check(v, bik)
            if bik:
                e["bik"] = bik
    return found
