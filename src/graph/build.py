"""Блок 1: граф связей из БД (networkx).

Узлы: "employee:12", "person:7", "organization:5", "group:3" (атрибуты kind, label).
Рёбра (MultiGraph; тип связи — в атрибуте rel):
  * RELATIVE, EX_EMPLOYER, SAME_PROJECT, SAME_COMMISSION — из relations (evidence_doc_id, relation_id);
  * DIRECTOR, FOUNDER — из org_roles (person — organization);
  * MEMBER — из group_members (участник — group, role).
Узлы и рёбра добавляются в отсортированном порядке, поэтому обход графа детерминирован.
На Этапе 3 сюда добавятся рёбра из распознанных документов.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

import networkx as nx

AFFILIATION_TYPES = ("RELATIVE", "EX_EMPLOYER", "SAME_PROJECT")   # рёбра для И2 (PLAN.md, раздел 7)


def node(kind: str, obj_id: int) -> str:
    return f"{kind}:{obj_id}"


def parse_node(n: str) -> tuple[str, int]:
    kind, obj_id = n.split(":")
    return kind, int(obj_id)


def build_graph(conn: sqlite3.Connection) -> nx.MultiGraph:
    g = nx.MultiGraph()
    for eid, name, title in conn.execute(
            "SELECT e.id, e.full_name, p.title FROM employees e JOIN positions p ON p.id = e.position_id ORDER BY e.id"):
        g.add_node(node("employee", eid), kind="employee", label=name, title=title)
    for pid, name in conn.execute("SELECT id, full_name FROM persons ORDER BY id"):
        g.add_node(node("person", pid), kind="person", label=name)
    for oid, name, inn in conn.execute("SELECT id, name, inn FROM organizations ORDER BY id"):
        g.add_node(node("organization", oid), kind="organization", label=name, inn=inn)
    for gid, kind, name, doc in conn.execute("SELECT id, kind, name, created_by_doc_id FROM groups ORDER BY id"):
        g.add_node(node("group", gid), kind="group", group_kind=kind, label=name, doc_id=doc)

    for rid, at, ai, bt, bi, rel, doc in conn.execute(
            "SELECT id, a_type, a_id, b_type, b_id, rel_type, evidence_doc_id FROM relations ORDER BY id"):
        g.add_edge(node(at, ai), node(bt, bi), key=f"{rel}#{rid}", rel=rel, relation_id=rid, evidence_doc_id=doc)
    for oid, pid, role in conn.execute("SELECT org_id, person_id, role FROM org_roles ORDER BY org_id, person_id, role"):
        g.add_edge(node("person", pid), node("organization", oid), key=role, rel=role)
    for gid, mt, mid, role in conn.execute(
            "SELECT group_id, member_type, member_id, role FROM group_members ORDER BY group_id, member_type, member_id"):
        g.add_edge(node(mt, mid), node("group", gid), key="MEMBER", rel="MEMBER", role=role)
    return g


def affiliation_graph(g: nx.MultiGraph, rel_types: Iterable[str] = AFFILIATION_TYPES) -> nx.Graph:
    """Простой граф только из рёбер заданных типов (для поиска путей)."""
    types = set(rel_types)
    out = nx.Graph()
    out.add_nodes_from(g.nodes(data=True))
    for u, v, data in g.edges(data=True):
        if data["rel"] in types and not out.has_edge(u, v):
            out.add_edge(u, v, **data)
    return out


def shortest_path_to(gaff: nx.Graph, sources: Iterable[str], targets: set[str],
                     max_len: int) -> Optional[list[str]]:
    """Кратчайший путь (не длиннее max_len рёбер) от любого источника до любой цели.
    При равной длине выбирается путь с меньшими (источник, цель) — детерминированно."""
    best: Optional[tuple[int, str, str, list[str]]] = None
    for s in sorted(set(sources)):
        if s not in gaff:
            continue
        paths = nx.single_source_shortest_path(gaff, s, cutoff=max_len)
        for t in sorted(targets & paths.keys()):
            cand = (len(paths[t]) - 1, s, t, paths[t])
            if best is None or cand[:3] < best[:3]:
                best = cand
    return best[3] if best else None



def affiliation_path(gaff: nx.Graph, gstrong: nx.Graph, sources: Iterable[str], targets: set[str],
                     max_len: int) -> Optional[list[str]]:
    """Путь для И2: прямая связь любого допустимого типа (длина 1) или путь до max_len только по «сильным»
    рёбрам (родство, бывший работодатель). Цепочки через общие проекты («коллега коллеги») — слабые и
    сигналом не считаются."""
    sources = list(sources)
    return shortest_path_to(gaff, sources, targets, 1) or shortest_path_to(gstrong, sources, targets, max_len)

# --- Рёбра из распознанных документов (src/extraction/pipeline.py) ----------------------------------
# Типы: MEMBER_DOC (лицо — группа, из приказа), AFFILIATION_DOC (лицо — организация, из приказа),
# COMMISSION_DOC (член комиссии — закупка), BID_DOC / WINNER_DOC (организация — закупка, из протокола).
# У ребра: source="document", doc_id, role/amount. Узлы закупок "procurement:<id>" добавляются по мере надобности.

def load_extracted(extracted_dir) -> dict[str, dict]:
    import json
    from pathlib import Path

    out = {}
    for p in sorted(Path(extracted_dir).glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def _initials(full_name: str) -> Optional[str]:
    parts = full_name.split()
    return f"{parts[0]} {parts[1][0]}. {parts[2][0]}." if len(parts) == 3 else None


def people_index(conn: sqlite3.Connection) -> dict[str, str]:
    """Нормализованное ФИО (и «Фамилия И. О.», если однозначно) -> узел employee:/person:."""
    full: dict[str, set[str]] = {}
    for kind, sql in (("employee", "SELECT id, full_name FROM employees"), ("person", "SELECT id, full_name FROM persons")):
        for i, name in conn.execute(sql):
            n = name.replace("ё", "е")
            full.setdefault(n, set()).add(node(kind, i))
            if (ini := _initials(n)):
                full.setdefault(ini, set()).add(node(kind, i))
    return {k: next(iter(v)) for k, v in full.items() if len(v) == 1}


def orgs_index(conn: sqlite3.Connection) -> dict[str, str]:
    out = {}
    for i, name in conn.execute("SELECT id, name FROM organizations"):
        form, _, rest = name.partition(" ")
        out[f"{form} {rest.strip('«»').upper()}".replace("Ё", "Е")] = node("organization", i)
    return out


def add_document_edges(g: nx.MultiGraph, conn: sqlite3.Connection, extracted: dict[str, dict]) -> dict[str, int]:
    """Добавляет в граф рёбра из распознанных документов. Возвращает счётчики (в т.ч. несопоставленные)."""
    from pathlib import PurePosixPath

    docs = {PurePosixPath(p).stem: (i, ot, oid, num) for i, p, ot, oid, num in
            conn.execute("SELECT id, path, object_type, object_id, doc_number FROM documents")}
    people, orgs = people_index(conn), orgs_index(conn)
    stats = {"edges": 0, "unmatched_persons": 0, "unmatched_orgs": 0, "unknown_docs": 0}

    def person(name: str) -> Optional[str]:
        n = people.get(name.removeprefix("PERSON:"))
        if n is None:
            stats["unmatched_persons"] += 1
        return n

    def org(name: str) -> Optional[str]:
        n = orgs.get(name.removeprefix("ORG:"))
        if n is None:
            stats["unmatched_orgs"] += 1
        return n

    def edge(u: Optional[str], v: Optional[str], rel: str, doc_id: int, **attrs) -> None:
        if u is None or v is None:
            return
        g.add_edge(u, v, key=f"{rel}#{doc_id}#{attrs.get('role', '')}{attrs.get('amount', '')}", rel=rel,
                   source="document", doc_id=doc_id, **attrs)
        stats["edges"] += 1

    for stem in sorted(extracted):
        res = extracted[stem]
        if stem not in docs:
            stats["unknown_docs"] += 1
            continue
        doc_id, ot, oid, num = docs[stem]
        if res.get("doc_type") == "ORDER" and ot == "group":
            grp = node("group", oid)
            for r in res["relations"]:
                if r["type"] == "MEMBER":
                    edge(person(r["from"]), grp, "MEMBER_DOC", doc_id, role=r.get("role"))
                elif r["type"] == "AFFILIATION":
                    edge(person(r["from"]), org(r["to"]), "AFFILIATION_DOC", doc_id)
        elif res.get("doc_type") == "PROTOCOL" and ot == "procurement":
            proc = node("procurement", oid)
            if proc not in g:
                g.add_node(proc, kind="procurement", label=f"Закупка № {num}")
            for e in res["entities"]:
                if e["type"] == "PERSON" and e.get("role", "").startswith("COMMISSION_") and "." not in e["value"]:
                    edge(person(e["normalized"]), proc, "COMMISSION_DOC", doc_id, role=e["role"].split("_", 1)[1])
            for r in res["relations"]:
                if r["type"] == "BID":
                    edge(org(r["from"]), proc, "BID_DOC", doc_id, amount=float(r["to"].split(":")[1]))
                elif r["type"] == "WINNER":
                    edge(org(r["from"]), proc, "WINNER_DOC", doc_id)
    return stats
