"""UI: слой данных и прогон приложения в Streamlit AppTest (без браузера)."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.app import data
from src.extraction.pipeline import run as extract_run
from src.generator.run import build
from src.indicators.run import run as signals_run


@pytest.fixture(scope="module")
def app_db(small_cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("app")
    db = build(small_cfg, out, render_docs=True)["db_path"]
    signals_run(db, small_cfg)
    extract_run(sorted((out / "docs").glob("*.docx")), out / "extracted")
    return db


def test_list_and_detail(app_db):
    conn = data.connect(app_db)
    rows = data.list_signals(conn)
    assert rows and {r["indicator"] for r in rows} <= set(data.INDICATOR_NAMES)
    assert data.list_signals(conn, indicators=["I7"]) == [r for r in rows if r["indicator"] == "I7"]
    some = next(r for r in rows if r["employee"] != "—")
    assert data.list_signals(conn, employee_query=some["employee"].split()[0])
    d = data.signal_detail(conn, rows[0]["id"])
    assert d["explanation"] and d["indicator_name"]
    assert data.signal_detail(conn, 10**9) is None


def test_review_update(app_db):
    conn = data.connect(app_db)
    sid = data.list_signals(conn)[0]["id"]
    data.update_review(conn, sid, "REJECTED", "  законная закупка  ")
    assert tuple(conn.execute("SELECT status, reviewer_comment FROM signals WHERE id = ?", (sid,)).fetchone()) == \
        ("REJECTED", "законная закупка")
    with pytest.raises(ValueError):
        data.update_review(conn, sid, "GUILTY", "")
    data.update_review(conn, sid, "NEW", "")


def test_document_highlight(app_db):
    conn = data.connect(app_db)
    row = conn.execute("SELECT id, evidence_fragment_ids FROM signals WHERE evidence_fragment_ids != '[]' "
                       "LIMIT 1").fetchone()
    ev = data.evidence(conn, json.loads(row[1]))
    pages = data.document_pages_html(conn, ev[0]["document_id"], {e["id"] for e in ev})
    assert any("<mark>" in p for p in pages)


def test_subgraph_for_every_indicator(app_db):
    conn = data.connect(app_db)
    cache = data.GraphCache(conn, Path(app_db).parent / "extracted")
    assert cache.doc_stats and cache.doc_stats["edges"] > 0
    for ind in data.INDICATOR_NAMES:
        r = conn.execute("SELECT id FROM signals WHERE indicator = ? LIMIT 1", (ind,)).fetchone()
        if r is None:
            continue
        sub, key, path = data.signal_subgraph(conn, cache, r[0])
        assert sub.number_of_nodes() >= 1 and key <= set(sub.nodes)
        if ind == "I2":
            assert len(path) >= 2 and all(n in sub for n in path)


def test_streamlit_app_runs(app_db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("RISK_DB", str(app_db))
    app = Path(__file__).resolve().parents[1] / "src" / "app" / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception
    assert any("Сигналы:" in s.value for s in at.subheader)
    sid = at.selectbox(key="signal").value
    at.radio(key=f"status_{sid}").set_value("IN_WORK")
    at.text_area(key=f"comment_{sid}").input("проверить аффилированность")
    at.button(key=f"save_{sid}").click().run()
    assert not at.exception
    conn = sqlite3.connect(app_db)
    assert conn.execute("SELECT status, reviewer_comment FROM signals WHERE id = ?", (sid,)).fetchone() == \
        ("IN_WORK", "проверить аффилированность")
    # фильтр по индикатору
    at.multiselect(key="f_ind").set_value(["I7"]).run()
    assert not at.exception
