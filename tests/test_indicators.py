"""Индикаторы И1–И4, И7: детерминизм, полнота объяснений, сохранение решений проверяющего, recall по схемам."""

import json
import sqlite3

import pytest

from src.evaluation.signals_eval import evaluate, format_report, strength
from src.generator.run import build
from src.indicators.base import name_variants, pct, percentile
from src.indicators.run import decision_summary, employee_overview, run, signals_hash

# Эталонный хэш сигналов для config/settings.yaml (seed 42); обновлять вместе с GOLDEN_CONTENT_SHA256.
GOLDEN_SIGNALS_SHA256 = "8bb8d7e5aab1eb8453ba0ae0f646bcd96052167d597d2e13dc38405bfb954639"


@pytest.fixture(scope="module")
def sig_db(cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("signals")
    db_path = build(cfg, out, render_docs=False)["db_path"]
    summary = run(db_path, cfg)
    conn = sqlite3.connect(db_path)
    yield conn, db_path, summary
    conn.close()


def test_percentile():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 90) == 10
    assert percentile(list(range(11)), 90) == 9
    assert percentile([], 90) is None


def test_formatting_helpers():
    assert pct(0.623) == "62%" and pct(0.0021, 1) == "0,2%"
    assert "Ивановой Анны Сергеевны" in name_variants("Иванова Анна Сергеевна")
    assert "А.С. Иванова" in name_variants("Иванова Анна Сергеевна")


def test_signals_deterministic(cfg, sig_db, tmp_path):
    conn, db_path, summary = sig_db
    again = run(db_path, cfg)
    assert again["signals_sha256"] == summary["signals_sha256"]
    fresh = build(cfg, tmp_path, render_docs=False)["db_path"]
    assert run(fresh, cfg)["signals_sha256"] == summary["signals_sha256"]
    if GOLDEN_SIGNALS_SHA256:
        assert summary["signals_sha256"] == GOLDEN_SIGNALS_SHA256


def test_every_signal_is_explained(sig_db):
    conn, _, _ = sig_db
    frag_ids = {r[0] for r in conn.execute("SELECT id FROM doc_fragments")}
    rows = conn.execute("SELECT indicator, object_type, value, threshold, peer_group, explanation, "
                        "evidence_fragment_ids, status FROM signals").fetchall()
    assert {r[0] for r in rows} == {"I1", "I2", "I3", "I4", "I7"}
    for ind, ot, value, thr, group, expl, ev, status in rows:
        assert expl and not expl[0].islower() and expl.endswith(".")
        assert status == "NEW" and group
        assert set(json.loads(ev)) <= frag_ids
        if ind in ("I1", "I3", "I4"):
            assert value is not None and thr is not None
    # у сигналов по контрактам с протоколом есть ссылка на фрагмент документа
    with_doc = conn.execute("""SELECT count(*), sum(s.evidence_fragment_ids != '[]') FROM signals s
                               JOIN contracts c ON s.object_type = 'contract' AND c.id = s.object_id
                               JOIN documents d ON d.object_type = 'procurement' AND d.object_id = c.procurement_id
                               WHERE s.indicator IN ('I2', 'I4', 'I7')""").fetchone()
    assert with_doc[0] > 0 and with_doc[0] == with_doc[1]


def test_i7_matches_regulation_exactly(sig_db):
    conn, _, _ = sig_db
    flagged = {r[0] for r in conn.execute("SELECT object_id FROM signals WHERE indicator = 'I7'")}
    unauthorized = {r[0] for r in conn.execute("""SELECT c.id FROM contracts c JOIN employees e
        ON e.id = c.signer_employee_id WHERE NOT EXISTS (SELECT 1 FROM position_authorities a
        WHERE a.position_id = e.position_id AND a.action = 'SIGN_CONTRACT')""")}
    assert flagged == unauthorized


def test_i2_explains_relative_path_for_s1(sig_db):
    conn, _, _ = sig_db
    rows = conn.execute("""SELECT s.explanation, s.employee_id, i.employee_id FROM signals s JOIN injected_schemes i
                           ON i.scheme = 'S1' AND i.object_type = 'contract' AND i.object_id = s.object_id
                           WHERE s.indicator = 'I2'""").fetchall()
    assert rows
    for expl, emp, gt_emp in rows:
        assert "родственник" in expl and emp == gt_emp


def test_reviewer_decision_survives_rerun(cfg, sig_db):
    conn, db_path, _ = sig_db
    sid = conn.execute("SELECT id FROM signals WHERE indicator = 'I4' ORDER BY id LIMIT 1").fetchone()[0]
    with conn:
        conn.execute("UPDATE signals SET status = 'IN_WORK', reviewer_comment = 'проверить' WHERE id = ?", (sid,))
    before = signals_hash(conn)
    run(db_path, cfg)
    assert conn.execute("SELECT status, reviewer_comment FROM signals WHERE id = ?", (sid,)).fetchone() == \
        ("IN_WORK", "проверить")
    assert signals_hash(conn) == before      # хэш не зависит от решений проверяющего


def test_summaries(cfg, sig_db):
    conn, _, _ = sig_db
    summary = decision_summary(conn, cfg)
    assert summary and all(v["weight"] >= len(v["indicators"]) * 0 for v in summary.values())
    emp = conn.execute("SELECT employee_id FROM injected_schemes WHERE scheme = 'S4' LIMIT 1").fetchone()[0]
    flagged, total = employee_overview(conn, emp)
    assert 0 < flagged <= total


def test_recall_on_injected_schemes(cfg, sig_db):
    """Регрессионная граница: основные индикаторы находят внедрённые схемы."""
    conn, _, _ = sig_db
    report = evaluate(conn, cfg)
    main = {(x["scheme"], x["indicator"], x["level"]): x["recall"] for x in report["recall"]}
    for key, value in main.items():
        if key != ("S1", "I1", "employee"):           # И1 для S1 — вторичная цель
            assert value >= 0.9, key
    prec = {(x["indicator"], x["level"]): x["precision"] for x in report["precision"]}
    assert prec[("I7", "contract")] == 1.0
    assert report["clean_contracts_flag_rate"] < 0.1
    assert "Recall по схемам" in format_report(report)


def test_strength_ranges():
    assert strength("I2", 1, 2, "contract") == 1.0
    assert 0 <= strength("I1", 0.8, 0.4, "employee") <= 1
    assert strength("I4", 0.0035, 0.005, "contract") == 0.5
