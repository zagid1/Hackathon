"""Точка входа генератора: `python -m src.generator.run [--config ...] [--seed N] [--out DIR] [--no-docs]`.

Порядок шагов фиксирован — от него зависит нумерация id и, значит, побайтная воспроизводимость.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings
from src.models.db import content_hash, file_sha256, write_dataset
from src.models.entities import DatasetMeta

from .common import World
from .companies import build_companies, emit_org_roles, set_director
from .documents import build_documents
from .groups import build_groups
from .names import NameFactory
from .org import build_org
from .people import build_background_relatives, build_ex_employers
from .procurement import assign_specializations, build_procurements
from .schemes import emit_labels, setup_schemes

GENERATOR_VERSION = "1"


def _assign_relative_directors(w: World, relatives: list[int], busy_orgs: set[int]) -> None:
    """Часть фоновых родственников руководит фирмами (фирмы не получают от «своих» служащих контрактов)."""
    rng = w.rng("relative_directors")
    share = w.gen["relatives"]["director_share"]
    free = sorted(o for o, info in w.orgs.items() if not info.major and o not in busy_orgs)
    for pid in relatives:
        if rng.random() < share and free:
            org = free.pop(rng.randrange(len(free)))
            set_director(w, org, pid, also_founder=rng.random() < 0.5)


DATA_CONFIG_KEYS = ("seed", "generator", "schemes", "documents")


def config_hash(cfg: dict) -> str:
    """Хэш только тех разделов конфига, от которых зависят данные: правка порогов индикаторов
    не должна менять «отпечаток» набора данных."""
    part = {k: cfg.get(k) for k in DATA_CONFIG_KEYS}
    part["docs_subdir"] = cfg.get("paths", {}).get("docs_subdir")
    return hashlib.sha256(json.dumps(part, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def generate(cfg: dict, docs_dir: Optional[Path] = None) -> World:
    w = World(cfg=cfg, seed=int(cfg["seed"]))
    w.names = NameFactory(w.rng("names"))

    build_org(w)
    build_companies(w)
    build_groups(w)
    assign_specializations(w)
    plan = setup_schemes(w)

    scheme_firms = ({f for f, _ in plan.s1_resp.values()} | {f for _, f, _ in plan.s1_comm.values()}
                    | set(plan.s2.values()))
    project_persons = {mid for gi in w.groups.values() for t, mid, _ in gi.members if t == "person"}
    project_orgs = {o for o, p in w.org_director.items() if p in project_persons}
    background = build_background_relatives(w, exclude=set(w.relatives))
    _assign_relative_directors(w, background, scheme_firms | project_orgs)
    build_ex_employers(w, sorted(w.orgs))
    emit_org_roles(w)

    meta = build_procurements(w, plan)
    emit_labels(w, plan)

    contract_proc = {c.id: c.procurement_id for c in w.ds.contracts}
    scheme_procs = {oid if ot == "procurement" else contract_proc[oid]
                    for _, ot, oid, _ in plan.labels if ot in ("procurement", "contract")}
    build_documents(w, meta, scheme_procs, docs_dir)

    w.ds.dataset_meta = [
        DatasetMeta("config_sha256", config_hash(cfg)),
        DatasetMeta("generator_version", GENERATOR_VERSION),
        DatasetMeta("seed", str(w.seed)),
        DatasetMeta("source", "synthetic"),
    ]
    return w


def build(cfg: dict, data_dir: Path, render_docs: bool = True) -> dict:
    data_dir = Path(data_dir)
    db_path = data_dir / cfg["paths"]["db_file"]
    docs_dir = data_dir / cfg["paths"]["docs_subdir"]
    if render_docs:
        docs_dir.mkdir(parents=True, exist_ok=True)
        for p in list(docs_dir.glob("*.docx")) + list(docs_dir.glob("*.json")):
            p.unlink()
    w = generate(cfg, docs_dir if render_docs else None)
    write_dataset(w.ds, db_path)
    return {
        "db_path": str(db_path),
        "db_sha256": file_sha256(db_path),
        "content_sha256": content_hash(db_path),
        "counts": {m.TABLE: len(rows) for m, rows in w.ds.tables()},
        "schemes": dict(sorted(Counter(f"{r.scheme}/{r.object_type}" for r in w.ds.injected_schemes).items())),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Генератор синтетических данных")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--seed", type=int, default=None, help="переопределить seed из конфига")
    ap.add_argument("--out", type=Path, default=None, help="каталог данных (по умолчанию paths.data_dir)")
    ap.add_argument("--no-docs", action="store_true", help="не писать DOCX/JSON (строки в БД остаются)")
    args = ap.parse_args(argv)

    cfg = load_settings(args.config, {"seed": args.seed} if args.seed is not None else None)
    data_dir = args.out or (ROOT / cfg["paths"]["data_dir"])
    render = cfg.get("documents", {}).get("render_files", True) and not args.no_docs
    t0 = time.perf_counter()
    summary = build(cfg, data_dir, render_docs=render)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
