"""Конвейер распознавания: файл -> JSON по контракту раздела 8 PLAN.md.

`python -m src.extraction.pipeline [ФАЙЛЫ...] [--out DIR]` — без аргументов обрабатывает все документы
из data/synthetic/docs и пишет результаты в data/synthetic/extracted/<имя>.json.

* Поддерживается DOCX (каноническая модель текста — src.generator.documents.read_docx_pages).
  PDF — следующий шаг (pdfplumber), сейчас выдаёт понятную ошибку.
* Тип документа определяется по заголовку (ПРОТОКОЛ / ПРИКАЗ).
* Кэш: результат пересчитывается, только если изменился файл (sha256) или версия парсеров.
* Детерминированно: правила + Natasha/pymorphy3 без случайности, JSON с сортировкой ключей.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Optional

from src.config import ROOT, load_settings
from src.generator.documents import read_docx_pages

from .order import parse_order
from .protocol import parse_protocol

EXTRACTOR_VERSION = "4"


class UnsupportedDocument(ValueError):
    pass


def read_pages(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx_pages(path)
    if suffix == ".pdf":
        raise UnsupportedDocument("PDF пока не поддерживается (план: pdfplumber), конвертируйте в DOCX")
    raise UnsupportedDocument(f"неподдерживаемый формат: {suffix}")


def detect_type(pages: list[str]) -> Optional[str]:
    head = (pages[0] if pages else "")[:300].upper()
    if "ПРОТОКОЛ" in head:
        return "PROTOCOL"
    if "ПРИКАЗ" in head:
        return "ORDER"
    return None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract(path: Path) -> dict:
    path = Path(path)
    pages = read_pages(path)
    doc_type = detect_type(pages)
    if doc_type == "PROTOCOL":
        result = parse_protocol(pages)
    elif doc_type == "ORDER":
        result = parse_order(pages)
    else:
        result = {"doc_type": None, "entities": [], "relations": []}
    return {"doc_id": path.stem, "file": path.name, "sha256": file_sha256(path), "pages": len(pages),
            "extractor_version": EXTRACTOR_VERSION, **result}


def run(paths: list[Path], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    done = cached = failed = 0
    errors = []
    for path in sorted(paths):
        out = out_dir / f"{path.stem}.json"
        if out.exists():
            old = json.loads(out.read_text(encoding="utf-8"))
            if old.get("sha256") == file_sha256(path) and old.get("extractor_version") == EXTRACTOR_VERSION:
                cached += 1
                continue
        try:
            res = extract(path)
        except UnsupportedDocument as e:
            failed += 1
            errors.append(f"{path.name}: {e}")
            continue
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                       newline="\n")
        done += 1
    return {"processed": done, "cached": cached, "failed": failed, "errors": errors[:10], "out_dir": str(out_dir)}


def default_dirs(cfg: dict) -> tuple[Path, Path]:
    data = ROOT / cfg["paths"]["data_dir"]
    return data / cfg["paths"]["docs_subdir"], data / "extracted"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Распознавание документов -> JSON")
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "settings.yaml")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    docs_dir, out_default = default_dirs(load_settings(args.config))
    paths = args.files or sorted(docs_dir.glob("*.docx"))
    t0 = time.perf_counter()
    summary = run(paths, args.out or out_default)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
