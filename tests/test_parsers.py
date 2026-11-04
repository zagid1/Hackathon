"""Парсеры протокола и приказа, конвейер файл -> JSON. Качество меряется на корпусе генератора
(3 шаблона на тип документа); это свои же шаблоны — на реальных документах качество ниже."""

import json
import sqlite3
from collections import Counter

import pytest

from src.extraction.common import assign_roles, link_initials
from src.extraction.money import find_money
from src.extraction.pipeline import UnsupportedDocument, detect_type, extract, read_pages, run
from src.generator.documents import read_docx_pages


def test_money_formats():
    vals = [e["normalized"] for e in find_money("1 286 456,23 руб.; 1250000.50 рублей; 502 124 руб. 74 коп.; "
                                                "501 773,25 руб.")]
    assert vals == [1286456.23, 1250000.5, 502124.74, 501773.25]
    assert find_money("от 18.01.2024 № 443-п, ИНН 7707083893") == []
    assert find_money("1 | ООО | 1 256 958,89") == []
    assert find_money("1 | ООО | 1 256 958,89", allow_bare=True)[0]["normalized"] == 1256958.89


def test_roles_and_initials():
    text = "Комиссия в составе: председателя комиссии А, членов комиссии Б, В,\nсекретаря комиссии Г рассмотрела."
    persons = [{"span": [text.index(x), text.index(x) + 1]} for x in "АБВГ"]
    roles = assign_roles(text, persons)
    assert [roles[id(p)] for p in persons] == ["CHAIR", "MEMBER", "MEMBER", "SECRETARY"]
    people = [{"normalized": "Иванов Иван Петрович"}, {"normalized": "Иванов И. П."},
              {"normalized": "Соболева Алла Алексеевна"}, {"normalized": "Соболева Анна Андреевна"},
              {"normalized": "Соболева А. А."}]
    link_initials(people)
    assert people[1]["normalized"] == "Иванов Иван Петрович"
    assert people[4]["normalized"] == "Соболева А. А."      # неоднозначно — не склеиваем


@pytest.fixture(scope="module")
def parsed(small_build):
    out, summary = small_build
    docs = sorted((out / "docs").glob("*.docx"))
    conn = sqlite3.connect(summary["db_path"])
    meta = {p.split("/")[-1][:-5]: (n, d) for p, n, d in conn.execute("SELECT path, doc_number, doc_date FROM documents")}
    groups = {f"order_{g:03d}": name for g, name in conn.execute("SELECT id, name FROM groups")}
    conn.close()
    res = []
    for d in docs:
        ann = json.loads(d.with_suffix(".json").read_text(encoding="utf-8"))
        res.append((d, ann, extract(d)))
    return res, meta, groups


def _score(items, doc_type):
    st = Counter()
    for _, ann, res in items:
        if ann["doc_type"] != doc_type:
            continue
        pred = {(e["page"], tuple(e["span"]), e["type"]): e for e in res["entities"]}
        for g in ann["entities"]:
            p = pred.get((g["page"], tuple(g["span"]), g["type"]))
            st["total"] += 1
            st["span"] += p is not None
            st["role"] += p is not None and p.get("role") == g.get("role")
            st["norm"] += p is not None and (g.get("normalized") is None or p.get("normalized") == g.get("normalized"))
    return st


def test_protocol_quality(parsed):
    items, meta, _ = parsed
    st = _score(items, "PROTOCOL")
    assert st["total"] > 300
    assert st["span"] / st["total"] >= 0.99 and st["role"] / st["total"] >= 0.98 and st["norm"] / st["total"] >= 0.97
    for d, ann, res in items:
        if ann["doc_type"] != "PROTOCOL":
            continue
        assert res["procurement_number"] == meta[d.stem][0]
        gold = Counter((r["type"], r["from"], r["to"]) for r in ann["relations"] if r["type"] == "BID")
        pred = Counter((r["type"], r["from"], r["to"]) for r in res["relations"] if r["type"] == "BID")
        assert gold == pred, d.name
        winners = {r["from"] for r in res["relations"] if r["type"] == "WINNER"}
        assert winners == {r["from"] for r in ann["relations"] if r["type"] == "WINNER"}


def test_order_quality(parsed):
    items, meta, groups = parsed
    st = _score(items, "ORDER")
    assert st["total"] > 50
    assert st["span"] == st["total"] and st["role"] == st["total"]
    for d, ann, res in items:
        if ann["doc_type"] != "ORDER":
            continue
        assert (res["order_number"], res["order_date"]) == meta[d.stem]
        assert res["group_name"] == groups[d.stem]
        gold = Counter((r["from"], r["role"]) for r in ann["relations"] if r["type"] == "MEMBER")
        pred = Counter((r["from"], r["role"]) for r in res["relations"] if r["type"] == "MEMBER")
        assert gold == pred, d.name


def test_pipeline_cache_and_determinism(small_build, tmp_path):
    out, _ = small_build
    files = sorted((out / "docs").glob("*.docx"))[:4]
    first = run(files, tmp_path)
    assert first["processed"] == 4 and first["cached"] == 0
    snapshot = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    second = run(files, tmp_path)
    assert second["processed"] == 0 and second["cached"] == 4
    (tmp_path / files[0].with_suffix(".json").name).unlink()
    run(files, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == snapshot


def test_unsupported_and_detect(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(UnsupportedDocument):
        read_pages(pdf)
    assert detect_type(["ПРИКАЗ\n..."]) == "ORDER" and detect_type(["Протокол № 1"]) == "PROTOCOL"
    assert detect_type(["Письмо"]) is None
