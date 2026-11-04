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
