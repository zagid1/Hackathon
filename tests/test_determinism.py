from src.generator.run import build


def _files(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_same_seed_same_db(cfg, tmp_path):
    a = build(cfg, tmp_path / "a", render_docs=False)
    b = build(cfg, tmp_path / "b", render_docs=False)
    assert a["db_sha256"] == b["db_sha256"]
    assert a["content_sha256"] == b["content_sha256"]


def test_other_seed_other_db(cfg, tmp_path):
    a = build(cfg, tmp_path / "a", render_docs=False)
    b = build({**cfg, "seed": 7}, tmp_path / "b", render_docs=False)
    assert a["content_sha256"] != b["content_sha256"]


def test_rendering_does_not_change_db(small_cfg, small_build, tmp_path):
    _, rendered = small_build
    plain = build(small_cfg, tmp_path, render_docs=False)
    assert plain["db_sha256"] == rendered["db_sha256"]


def test_documents_byte_identical(small_cfg, small_build, tmp_path):
    out, _ = small_build
    build(small_cfg, tmp_path, render_docs=True)
    a, b = _files(out / "docs"), _files(tmp_path / "docs")
    assert a.keys() == b.keys() and len(a) > 40
    assert all(a[k] == b[k] for k in a)


# Эталонный хэш содержимого БД для config/settings.yaml (seed 42). Совпадает на Windows/Python 3.12
# и в Docker python:3.11-slim. Если генератор или конфиг меняются намеренно — обновите константу
# (значение content_sha256 печатает `make data`), и проверьте его на второй машине.
GOLDEN_CONTENT_SHA256 = "e295e8dcb1dbb710be935a7d8014caad30af336afee93679d05adf996f1e9841"


def test_golden_content_hash(cfg, tmp_path):
    assert build(cfg, tmp_path, render_docs=False)["content_sha256"] == GOLDEN_CONTENT_SHA256
