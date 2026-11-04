"""Данные для UI (без Streamlit — тестируется отдельно).

UI показывает сигналы риска и основания; решение о человеке принимает пользователь (статус + комментарий).
Таблица injected_schemes (ground truth) в UI не используется.
"""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path
from typing import Optional

import networkx as nx

from src.graph.build import (add_document_edges, affiliation_graph, affiliation_path, build_graph,
                             load_extracted, node)

INDICATOR_NAMES = {"I1": "И1 Концентрация", "I2": "И2 Аффилированность", "I3": "И3 Конкуренция",
                   "I4": "И4 Цена", "I7": "И7 Полномочия"}
STATUS_NAMES = {"NEW": "Новый", "IN_WORK": "Принят в работу", "REJECTED": "Отклонён"}
OBJECT_NAMES = {"employee": "Служащий", "contract": "Контракт", "procurement": "Закупка"}
DOC_NAMES = {"PROTOCOL": "Протокол", "ORDER": "Приказ", "CONTRACT": "Контракт"}
REL_NAMES = {"RELATIVE": "родственник", "EX_EMPLOYER": "бывший работодатель", "SAME_PROJECT": "общий проект",
             "SAME_COMMISSION": "общая комиссия", "DIRECTOR": "директор", "FOUNDER": "учредитель",
             "MEMBER": "член группы", "MEMBER_DOC": "член группы (приказ)", "AFFILIATION_DOC": "представитель (приказ)",
             "COMMISSION_DOC": "в комиссии (протокол)", "BID_DOC": "заявка (протокол)",
             "WINNER_DOC": "победитель (протокол)", "RESPONSIBLE": "ответственный", "SIGNED": "подписал"}


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def money(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " руб."


def format_value(indicator: str, object_type: str, value: Optional[float]) -> str:
    if value is None:
        return "—"
    if indicator in ("I1", "I4") or (indicator == "I3" and object_type == "employee" and value <= 1):
        return f"{value * 100:.1f}%".replace(".", ",")
    if indicator == "I2":
        return f"путь {int(value)}"
    if indicator == "I3":
        return f"{value:g} дн."
    return f"{value:g}"


def object_label(conn: sqlite3.Connection, object_type: str, object_id: int) -> str:
    if object_type == "employee":
        r = conn.execute("SELECT full_name FROM employees WHERE id = ?", (object_id,)).fetchone()
        return r[0] if r else f"служащий {object_id}"
    if object_type == "contract":
        r = conn.execute("SELECT o.name, c.price FROM contracts c JOIN organizations o ON o.id = c.supplier_org_id "
                         "WHERE c.id = ?", (object_id,)).fetchone()
        return f"Контракт № {object_id}: {r[0]}, {money(r[1])}" if r else f"контракт {object_id}"
    if object_type == "procurement":
        r = conn.execute("SELECT okpd2, method, nmck FROM procurements WHERE id = ?", (object_id,)).fetchone()
        return f"Закупка № {object_id}: ОКПД2 {r[0]}, {r[1]}, НМЦК {money(r[2])}" if r else f"закупка {object_id}"
    return f"{object_type} {object_id}"


def list_signals(conn: sqlite3.Connection, indicators: Optional[list[str]] = None,
                 statuses: Optional[list[str]] = None, employee_query: str = "") -> list[dict]:
    sql = ("SELECT s.*, e.full_name AS employee_name FROM signals s LEFT JOIN employees e ON e.id = s.employee_id "
           "WHERE 1 = 1")
    args: list = []
    if indicators:
        sql += f" AND s.indicator IN ({','.join('?' * len(indicators))})"
        args += indicators
    if statuses:
        sql += f" AND s.status IN ({','.join('?' * len(statuses))})"
        args += statuses
    if employee_query.strip():
        sql += " AND e.full_name LIKE ?"
        args.append(f"%{employee_query.strip()}%")
    rows = conn.execute(sql + " ORDER BY s.id", args).fetchall()
    return [{"id": r["id"], "indicator": r["indicator"], "indicator_name": INDICATOR_NAMES.get(r["indicator"], r["indicator"]),
             "object_type": r["object_type"], "object_id": r["object_id"],
             "object": object_label(conn, r["object_type"], r["object_id"]),
             "employee_id": r["employee_id"], "employee": r["employee_name"] or "—",
             "value": format_value(r["indicator"], r["object_type"], r["value"]),
             "threshold": format_value(r["indicator"], r["object_type"], r["threshold"]),
             "peer_group": r["peer_group"], "status": r["status"], "status_name": STATUS_NAMES[r["status"]],
             "explanation": r["explanation"]} for r in rows]


def evidence(conn: sqlite3.Connection, fragment_ids: list[int]) -> list[dict]:
    if not fragment_ids:
        return []
    q = ",".join("?" * len(fragment_ids))
    rows = conn.execute(f"""SELECT f.id, f.document_id, f.page, f.text, d.doc_type, d.doc_number, d.doc_date, d.path
                            FROM doc_fragments f JOIN documents d ON d.id = f.document_id
                            WHERE f.id IN ({q}) ORDER BY f.document_id, f.page, f.char_start""", fragment_ids).fetchall()
    return [dict(r) for r in rows]


def signal_detail(conn: sqlite3.Connection, sid: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM signals WHERE id = ?", (sid,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["indicator_name"] = INDICATOR_NAMES.get(d["indicator"], d["indicator"])
    d["object"] = object_label(conn, d["object_type"], d["object_id"])
    d["value_text"] = format_value(d["indicator"], d["object_type"], d["value"])
    d["threshold_text"] = format_value(d["indicator"], d["object_type"], d["threshold"])
    d["evidence"] = evidence(conn, json.loads(d["evidence_fragment_ids"]))
    d["employee"] = None
    if d["employee_id"]:
        e = conn.execute("SELECT e.full_name, p.title FROM employees e JOIN positions p ON p.id = e.position_id "
                         "WHERE e.id = ?", (d["employee_id"],)).fetchone()
        d["employee"] = {"id": d["employee_id"], "name": e[0], "title": e[1]}
    d["same_object"] = [dict(x) for x in conn.execute(
        "SELECT id, indicator, explanation FROM signals WHERE object_type = ? AND object_id = ? AND id != ? ORDER BY id",
        (d["object_type"], d["object_id"], sid))]
    return d


def update_review(conn: sqlite3.Connection, sid: int, status: str, comment: str) -> None:
    if status not in STATUS_NAMES:
        raise ValueError(status)
    with conn:
        conn.execute("UPDATE signals SET status = ?, reviewer_comment = ? WHERE id = ?",
                     (status, comment.strip() or None, sid))


def document_info(conn: sqlite3.Connection, doc_id: int) -> dict:
    d = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone())
    d["title"] = f"{DOC_NAMES.get(d['doc_type'], d['doc_type'])} № {d['doc_number']} от {d['doc_date']}"
    return d


def document_pages_html(conn: sqlite3.Connection, doc_id: int, highlight: set[int]) -> list[str]:
    """Текст страниц, восстановленный из doc_fragments; фрагменты-основания подсвечены <mark>."""
    pages: dict[int, list[str]] = {}
    for fid, page, text in conn.execute("SELECT id, page, text FROM doc_fragments WHERE document_id = ? "
                                        "ORDER BY page, char_start", (doc_id,)):
        t = html.escape(text).replace("\n", "<br>")
        pages.setdefault(page, []).append(f"<mark>{t}</mark>" if fid in highlight else t)
    return ["<br>".join(blocks) for _, blocks in sorted(pages.items())]


# --- граф вокруг сигнала ------------------------------------------------------------------------

class GraphCache:
    """Полный граф (из БД + рёбра из распознанных документов) строится один раз."""

    def __init__(self, conn: sqlite3.Connection, extracted_dir: Optional[Path] = None):
        self.g = build_graph(conn)
        self.doc_stats = None
        if extracted_dir and Path(extracted_dir).exists():
            self.doc_stats = add_document_edges(self.g, conn, load_extracted(extracted_dir))
        self.gaff = affiliation_graph(self.g)
        self.gstrong = affiliation_graph(self.g, ("RELATIVE", "EX_EMPLOYER"))


def signal_subgraph(conn: sqlite3.Connection, cache: GraphCache, sid: int) -> tuple[nx.MultiGraph, set[str], list[str]]:
    """Подграф для карточки: служащий, объект, поставщик и его руководители, комиссия, связи из документов.
    Возвращает (граф, ключевые узлы, путь И2 или [])."""
    s = conn.execute("SELECT indicator, object_type, object_id, employee_id FROM signals WHERE id = ?", (sid,)).fetchone()
    g = cache.g
    sub = nx.MultiGraph()
    key: set[str] = set()

    def add(n: str) -> None:
        if n in g and n not in sub:
            sub.add_node(n, **g.nodes[n])

    def link(u: str, v: str, rel: str, **attrs) -> None:
        add(u)
        add(v)
        if u in sub and v in sub:
            sub.add_edge(u, v, key=rel, rel=rel, **attrs)

    emp = node("employee", s["employee_id"]) if s["employee_id"] else None
    if emp:
        add(emp)
        key.add(emp)
        for _, nb, d in g.edges(emp, data=True):
            if d["rel"] in ("RELATIVE", "EX_EMPLOYER"):     # общие проекты — только если они на пути И2
                link(emp, nb, d["rel"], source=d.get("source", "db"))

    pid = None
    if s["object_type"] == "contract":
        c = conn.execute("SELECT procurement_id, supplier_org_id, signer_employee_id FROM contracts WHERE id = ?",
                         (s["object_id"],)).fetchone()
        pid, sup, signer = c
        org = node("organization", sup)
        key.add(org)
        add(org)
        for _, nb, d in g.edges(org, data=True):
            if d["rel"] in ("DIRECTOR", "FOUNDER"):
                link(nb, org, d["rel"])
        proc = node("procurement", pid)
        if proc not in g:
            g.add_node(proc, kind="procurement", label=f"Закупка № {pid}")
        link(org, proc, "WINNER_DOC" if g.has_edge(org, proc) else "SUPPLIER", source="db")
        link(node("employee", signer), proc, "SIGNED")
    elif s["object_type"] == "procurement":
        pid = s["object_id"]
    if pid is not None:
        proc = node("procurement", pid)
        if proc not in g:
            g.add_node(proc, kind="procurement", label=f"Закупка № {pid}")
        add(proc)
        key.add(proc)
        resp, comm = conn.execute("SELECT responsible_employee_id, commission_group_id FROM procurements WHERE id = ?",
                                  (pid,)).fetchone()
        link(node("employee", resp), proc, "RESPONSIBLE")
        for _, nb, d in g.edges(proc, data=True):
            if d["rel"] in ("COMMISSION_DOC", "BID_DOC", "WINNER_DOC"):
                link(nb, proc, d["rel"], source="document", role=d.get("role"), amount=d.get("amount"))
        if comm and not any(d["rel"] == "COMMISSION_DOC" for _, _, d in g.edges(proc, data=True)):
            for _, nb, d in g.edges(node("group", comm), data=True):
                if d["rel"] in ("MEMBER", "MEMBER_DOC"):
                    link(nb, node("group", comm), d["rel"], source=d.get("source", "db"))

    path: list[str] = []
    if s["indicator"] == "I2" and s["object_type"] == "contract":
        targets = {node("organization", sup)} | {nb for _, nb, d in g.edges(node("organization", sup), data=True)
                                                 if d["rel"] in ("DIRECTOR", "FOUNDER")}
        path = affiliation_path(cache.gaff, cache.gstrong, [emp], targets, 2) or []
        for u, v in zip(path, path[1:]):
            link(u, v, cache.gaff.edges[u, v]["rel"], source="db", on_path=True)
        key |= set(path)
    return sub, key, path
