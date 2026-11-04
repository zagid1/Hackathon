import sqlite3

import pytest

from src.models.db import create_schema, table_names
from src.models.entities import ALL_MODELS, Dataset


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    yield c
    c.close()


def test_every_table_has_model_and_columns_match(conn):
    models = {m.TABLE: m for m in ALL_MODELS}
    assert set(table_names(conn)) == set(models)
    for table, model in models.items():
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        assert cols == model.columns(), table


def test_dataset_covers_all_models():
    assert [m for m, _ in Dataset().tables()] == list(ALL_MODELS)


def test_check_constraints_reject_unknown_values(conn):
    conn.execute("INSERT INTO units VALUES (1, 'В', NULL, 0, 'synthetic')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO positions VALUES (1, 1, 'X', 'BRIBES')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO units VALUES (2, 'В', NULL, 0, 'fake')")


def test_signal_defaults(conn):
    conn.execute("INSERT INTO signals (id, indicator, object_type, object_id, explanation) "
                 "VALUES (1, 'I1', 'employee', 1, 'x')")
    status, ev = conn.execute("SELECT status, evidence_fragment_ids FROM signals").fetchone()
    assert (status, ev) == ("NEW", "[]")
