"""Нормы 44-ФЗ, общие для генератора и индикаторов (упрощённо; перепроверить по актуальной редакции).

* минимальный срок подачи заявок: аукцион 7 дней (15 при НМЦК > 300 млн), конкурс 10,
  запрос котировок 4 дня;
* закупка у единственного поставщика — при НМЦК <= 600 тыс. руб. (п. 4 ч. 1 ст. 93);
* запрос котировок — при НМЦК <= 3 млн руб.
"""

from __future__ import annotations

from src.models.entities import Method

LEGAL_MIN_DAYS = {Method.AUCTION: 7, Method.TENDER: 10, Method.QUOTATION: 4}
SINGLE_SUPPLIER_LIMIT_KOP = 600_000 * 100
QUOTATION_LIMIT_KOP = 3_000_000 * 100
AUCTION_LONG_DEADLINE_KOP = 300_000_000 * 100


def legal_min_days(method: str, nmck_kop: int) -> int:
    if method == Method.AUCTION and nmck_kop > AUCTION_LONG_DEADLINE_KOP:
        return 15
    return LEGAL_MIN_DAYS[method]
