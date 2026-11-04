"""Денежные суммы в тексте документов.

Поддерживаемые формы (пробелы-разделители тысяч могут быть неразрывными):
  «1 250 000,00 руб.», «1250000.00 рублей», «1 250 000 руб. 00 коп.», «1 250 000,00» (в ячейке таблицы).
Голое число без «руб.» принимается только при allow_bare=True (строки таблиц с колонкой цены).
"""

from __future__ import annotations

import re

_SP = r"[  ]"
_INT = rf"\d{{1,3}}(?:{_SP}\d{{3}})+|\d+"
_MONEY_RE = re.compile(
    rf"(?<![\d.,])(?P<int>{_INT})"
    rf"(?:(?P<sep>[,.])(?P<frac>\d{{2}}))?"
    rf"(?P<cur>{_SP}*(?:руб(?:лей|ля|ль)?\.?)(?:{_SP}*(?P<kop>\d{{2}}){_SP}*коп\.?)?)?"
    rf"(?![\d])")


def _value(m: re.Match) -> float:
    rub = int(re.sub(r"\D", "", m.group("int")))
    kop = m.group("frac") or m.group("kop") or "00"
    return round(rub + int(kop) / 100, 2)


def find_money(text: str, page: int = 1, allow_bare: bool = False) -> list[dict]:
    out = []
    for m in _MONEY_RE.finditer(text):
        has_currency = bool(m.group("cur") and m.group("cur").strip())
        bare_ok = allow_bare and m.group("frac") and m.group("sep") == ","
        if not (has_currency or bare_ok):
            continue
        value = m.group(0).rstrip()
        out.append({"type": "MONEY", "value": value, "normalized": _value(m), "page": page,
                    "span": [m.start(), m.start() + len(value)]})
    return out
