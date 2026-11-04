import json

from src.extraction.requisites import (find_requisites, is_valid_bik, is_valid_corr_account, is_valid_inn,
                                       is_valid_ogrn, is_valid_settlement_account)
from src.generator.documents import read_docx_pages

BIK = "044525225"            # ПАО Сбербанк (открытые данные)
CORR = "30101810400000000225"


def _with_key(account19_no_key: str, prefix: str) -> str:
    """Подставляет контрольную цифру (9-я позиция счёта)."""
    for d in "0123456789":
        acc = account19_no_key[:8] + d + account19_no_key[8:]
        s = prefix + acc
        if sum(int(c) * (7, 1, 3)[i % 3] for i, c in enumerate(s)) % 10 == 0:
            return acc
    raise AssertionError


def test_inn_ogrn():
    assert is_valid_inn("7707083893") and is_valid_inn("500100732259")
    assert not is_valid_inn("7707083894") and not is_valid_inn("500100732258") and not is_valid_inn("123")
    assert is_valid_ogrn("1027700132195") and is_valid_ogrn("304500116000157")
    assert not is_valid_ogrn("1027700132194") and not is_valid_ogrn("12345")


def test_bik_and_accounts():
    assert is_valid_bik(BIK) and not is_valid_bik("123456789")
    assert is_valid_corr_account(CORR, BIK)
    assert not is_valid_corr_account("30101810400000000226", BIK)
    acc = _with_key("4070281003800001234", BIK[-3:])
    assert is_valid_settlement_account(acc, BIK)
    bad = acc[:-1] + str((int(acc[-1]) + 1) % 10)
    assert not is_valid_settlement_account(bad, BIK)


def test_find_requisites_with_keywords():
    acc = _with_key("4070281003800001234", BIK[-3:])
    text = (f"ООО «Ромашка», ИНН 7707083893, КПП 773601001, ОГРН 1027700132195, "
            f"р/с {acc}, БИК {BIK}, к/с {CORR}. Телефон 84951234567.")
    found = {e["type"]: e for e in find_requisites(text)}
    assert set(found) == {"INN", "OGRN", "ACCOUNT", "BIK", "CORR_ACCOUNT"}
    assert all(e["valid_checksum"] for e in found.values())
    for e in found.values():
        s, t = e["span"]
        assert text[s:t] == e["value"]


def test_invalid_inn_is_reported_not_dropped():
    found = find_requisites("ИНН 7707083894")
    assert found == [{"type": "INN", "value": "7707083894", "page": 1, "span": [4, 14], "valid_checksum": False}]


def test_number_without_keyword_needs_valid_checksum():
    assert [e["type"] for e in find_requisites("номер 7707083893 и 7707083894")] == ["INN"]


def test_all_inn_and_ogrn_from_generated_documents(small_build):
    """На корпусе генератора: все ИНН/ОГРН из разметки найдены с верными спанами и контрольными суммами."""
    out, _ = small_build
    total = 0
    for ann_path in sorted((out / "docs").glob("protocol_*.json")):
        ann = json.loads(ann_path.read_text(encoding="utf-8"))
        pages = read_docx_pages(ann_path.with_suffix(".docx"))
        found = {(e["page"], tuple(e["span"]), e["type"]) for p, text in enumerate(pages, 1)
                 for e in find_requisites(text, p) if e["valid_checksum"]}
        for ent in ann["entities"]:
            if ent["type"] in ("INN", "OGRN"):
                total += 1
                assert (ent["page"], tuple(ent["span"]), ent["type"]) in found, (ann_path.name, ent)
    assert total > 50
