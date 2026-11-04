"""Документы: разметка (ground truth) и фрагменты БД совпадают с текстом, прочитанным из DOCX."""

import json
import re
import sqlite3

import pytest

from src.generator.documents import DocBuilder, Ent, money, read_docx_pages


def test_money_formats():
    assert money(125_000_000, "spaced") == "1 250 000,00 руб."
    assert money(125_000_050, "plain") == "1250000.50 рублей"
    assert money(125_000_000, "kop") == "1 250 000 руб. 00 коп."
    assert money(99, "table") == "0,99"
    assert money(100_000, "nbsp") == "1 000,00 руб."


def test_builder_offsets():
    b = DocBuilder()
    b.p("Заголовок")
    b.p("Победитель: ", Ent("ООО «А»", "ORG"), ".")
    b.page_break()
    b.row("1", Ent("ООО «Б»", "ORG"), Ent("7707083893", "INN"))
    built = b.build()
    assert built.pages == ["Заголовок\nПобедитель: ООО «А».", "1 | ООО «Б» | 7707083893"]
    for e in built.entities:
        s, t = e["span"]
        assert built.pages[e["page"] - 1][s:t] == e["value"]


@pytest.fixture(scope="module")
def corpus(small_build):
    out, summary = small_build
    conn = sqlite3.connect(summary["db_path"])
    docs = conn.execute("SELECT id, doc_type, path FROM documents ORDER BY id").fetchall()
    frags = conn.execute("SELECT document_id, page, char_start, char_end, text FROM doc_fragments").fetchall()
    names = {f"employee:{i}": n for i, n in conn.execute("SELECT id, full_name FROM employees")}
    names |= {f"person:{i}": n for i, n in conn.execute("SELECT id, full_name FROM persons")}
    conn.close()
    return out, docs, frags, names


def test_files_exist_for_every_document(corpus):
    out, docs, _, _ = corpus
    assert {t for _, t, _ in docs} == {"ORDER", "PROTOCOL"}
    for _, _, path in docs:
        assert (out / path).exists() and (out / path).with_suffix(".json").exists()


def test_fragments_match_docx_text(corpus):
    out, docs, frags, _ = corpus
    pages = {doc_id: read_docx_pages(out / path) for doc_id, _, path in docs}
    for doc_id, page, s, e, text in frags:
        assert pages[doc_id][page - 1][s:e] == text


def test_annotations_match_docx_text(corpus):
    out, docs, _, names = corpus
    variants = set()
    types = set()
    for doc_id, doc_type, path in docs:
        pages = read_docx_pages(out / path)
        ann = json.loads((out / path).with_suffix(".json").read_text(encoding="utf-8"))
        assert ann["db_document_id"] == doc_id and ann["doc_type"] == doc_type and ann["pages"] == len(pages)
        for ent in ann["entities"]:
            s, e = ent["span"]
            assert pages[ent["page"] - 1][s:e] == ent["value"], (path, ent)
            types.add(ent["type"])
            if ent["type"] == "PERSON":
                assert names[ent["ref"]] == ent["normalized"]
            if ent["type"] == "MONEY":
                digits = re.sub(r"\D", "", ent["value"])
                assert int(digits) == round(ent["normalized"] * 100)
        for rel in ann["relations"]:
            s, e = rel["evidence_span"]
            assert 0 <= s < e <= len(pages[rel["page"] - 1])
        if doc_type == "PROTOCOL":
            assert any(r["type"] == "WINNER" for r in ann["relations"])
        variants.add((doc_type, pages[0][:12]))
    assert {"PERSON", "ORG", "INN", "OGRN", "MONEY"} <= types
    assert len({v for v in variants if v[0] == "PROTOCOL"}) == 3   # все три шаблона встречаются


def test_no_known_grammar_slips(corpus):
    out, docs, _, _ = corpus
    for _, _, path in docs:
        text = "\n".join(read_docx_pages(out / path))
        assert "Павелович" not in text and "Павеловна" not in text
        assert not re.search(r"с (Общество|Акционерное общество|Публичное акционерное общество)\b", text)


def test_declined_names_present(corpus):
    """В документах встречаются ФИО не в именительном падеже — нормализация обязательна."""
    out, docs, _, _ = corpus
    declined = 0
    for _, _, path in docs:
        ann = json.loads((out / path).with_suffix(".json").read_text(encoding="utf-8"))
        declined += sum(1 for e in ann["entities"] if e["type"] == "PERSON"
                        and e["value"] != e["normalized"] and "." not in e["value"])
    assert declined > 20


def test_no_double_dots(corpus):
    _, _, frags, _ = corpus
    assert not [t for *_, t in frags if ".." in t]
