import sqlite3

import pytest

from src.config import load_settings
from src.generator.run import build, generate

# Небольшой набор для тестов документов (рендер DOCX — самая медленная часть).
SMALL = {"generator": {"procurements": 300}, "documents": {"max_protocols": 30}}


@pytest.fixture(scope="session")
def cfg():
    return load_settings()


@pytest.fixture(scope="session")
def small_cfg():
    return load_settings(overrides=SMALL)


@pytest.fixture(scope="session")
def world(cfg):
    """Полный набор по умолчанию (seed 42), без записи DOCX."""
    return generate(cfg)


@pytest.fixture(scope="session")
def db(cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("default")
    summary = build(cfg, out, render_docs=False)
    conn = sqlite3.connect(summary["db_path"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def small_build(small_cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("small")
    summary = build(small_cfg, out, render_docs=True)
    return out, summary
