"""UI прототипа: список сигналов -> карточка -> граф связей -> документ-основание.

Запуск: `make app` (streamlit run src/app/streamlit_app.py). Путь к БД — из config/settings.yaml
или переменной окружения RISK_DB. Система показывает признаки риска и их основания;
решение принимает человек — статус сигнала и комментарий ставит пользователь.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from src.app import data  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.indicators.base import short_name  # noqa: E402
from src.indicators.run import employee_overview  # noqa: E402

NODE_STYLE = {"employee": ("#2563eb", "dot"), "person": ("#9333ea", "dot"), "organization": ("#ea580c", "box"),
              "group": ("#16a34a", "diamond"), "procurement": ("#475569", "square")}


def db_paths() -> tuple[Path, Path]:
    cfg = load_settings()
    data_dir = ROOT / cfg["paths"]["data_dir"]
    db = Path(os.environ.get("RISK_DB", data_dir / cfg["paths"]["db_file"]))
    return db, db.parent / "extracted"


@st.cache_resource
def get_conn(db: str):
    return data.connect(Path(db))


@st.cache_resource
def get_graph(db: str, extracted: str):
    return data.GraphCache(get_conn(db), Path(extracted))


def graph_html(sub, key_nodes: set[str], path: list[str]) -> str:
    from pyvis.network import Network

    net = Network(height="560px", width="100%", cdn_resources="in_line", directed=False)
    for n, attrs in sorted(sub.nodes(data=True)):
        kind = attrs.get("kind")
        color, shape = NODE_STYLE.get(kind, ("#64748b", "dot"))
        full = attrs.get("label", n)
        label = short_name(full) if kind in ("employee", "person") else (full if len(full) <= 32 else full[:30] + "…")
        tooltip = full + (f" — {attrs['title']}" if attrs.get("title") else "")
        net.add_node(n, label=label, color=color, shape=shape, borderWidth=4 if n in key_nodes else 1,
                     size=22 if n in key_nodes else 14, title=tooltip)
    on_path = set(zip(path, path[1:])) | set(zip(path[1:], path))
    for u, v, d in sub.edges(data=True):
        rel = d.get("rel", "")
        net.add_edge(u, v, label=data.REL_NAMES.get(rel, rel), dashes=d.get("source") == "document",
                     width=4 if (u, v) in on_path else 1, color="#dc2626" if (u, v) in on_path else "#94a3b8")
    net.set_options('{"physics": {"stabilization": {"iterations": 150}}, "edges": {"font": {"size": 10}}}')
    return net.generate_html()


def main() -> None:
    st.set_page_config(page_title="Сигналы риска в деятельности служащих", layout="wide")
    st.title("Сигналы риска в деятельности служащих")
    st.caption("Прототип для подразделения по профилактике коррупционных правонарушений. "
               "Система показывает признаки риска в решениях и их основания; **вывод о человеке делает "
               "проверяющий**. Данные синтетические (source = synthetic).")

    db, extracted = db_paths()
    if not db.exists():
        st.error(f"База не найдена: {db}. Выполните `make data` и `make signals`.")
        return
    conn = get_conn(str(db))
    if conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 0:
        st.warning("Сигналов нет. Выполните `make signals`.")
        return

    with st.sidebar:
        st.header("Фильтры")
        inds = st.multiselect("Индикатор", list(data.INDICATOR_NAMES), format_func=data.INDICATOR_NAMES.get,
                              key="f_ind", placeholder="Все индикаторы")
        stats = st.multiselect("Статус", list(data.STATUS_NAMES), format_func=data.STATUS_NAMES.get, key="f_status",
                               placeholder="Все статусы")
        who = st.text_input("Служащий (часть ФИО)", key="f_who")

    rows = data.list_signals(conn, inds, stats, who)
    st.subheader(f"Сигналы: {len(rows)}")
    if not rows:
        st.info("Нет сигналов по выбранным фильтрам.")
        return
    st.dataframe(
        [{"№": r["id"], "Индикатор": r["indicator_name"], "Объект": r["object"], "Служащий": r["employee"],
          "Значение": r["value"], "Порог": r["threshold"], "Группа сравнения": r["peer_group"],
          "Статус": r["status_name"]} for r in rows],
        hide_index=True, use_container_width=True, height=280)

    options = [r["id"] for r in rows]
    labels = {r["id"]: f"№ {r['id']} · {r['indicator_name']} · {r['object']}" for r in rows}
    sid = st.selectbox("Открыть сигнал", options, format_func=labels.get, key="signal")
    d = data.signal_detail(conn, sid)

    tab_card, tab_graph, tab_doc = st.tabs(["Карточка", "Граф связей", "Документ"])

    with tab_card:
        st.markdown(f"### {d['indicator_name']} — {d['object']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Значение", d["value_text"])
        c2.metric("Порог", d["threshold_text"])
        c3.metric("Группа сравнения", d["peer_group"] or "—")
        st.info(d["explanation"])
        if d["employee"]:
            flagged, total = employee_overview(conn, d["employee"]["id"])
            st.markdown(f"**Служащий:** {d['employee']['name']}, {d['employee']['title'].lower()}. "
                        f"Решений с сигналами: **{flagged} из {total}** (контракты, где он ответственный или "
                        f"подписант). Единого «индекса» служащего нет.")
        if d["same_object"]:
            st.markdown("**Другие сигналы по этому объекту:** " + "; ".join(
                f"№ {x['id']} {data.INDICATOR_NAMES[x['indicator']]}" for x in d["same_object"]))
        st.markdown("**Основания (фрагменты документов):**")
        if not d["evidence"]:
            st.write("Документ-основание не найден в корпусе.")
        for ev in d["evidence"]:
            st.markdown(f"- {data.DOC_NAMES[ev['doc_type']]} № {ev['doc_number']}, стр. {ev['page']}: "
                        f"«{ev['text'][:300]}»")

        st.divider()
        st.markdown("#### Решение проверяющего")
        statuses = list(data.STATUS_NAMES)
        new_status = st.radio("Статус", statuses, index=statuses.index(d["status"]),
                              format_func=data.STATUS_NAMES.get, horizontal=True, key=f"status_{sid}")
        comment = st.text_area("Комментарий", value=d["reviewer_comment"] or "", key=f"comment_{sid}")
        if st.button("Сохранить решение", key=f"save_{sid}"):
            data.update_review(conn, sid, new_status, comment)
            st.success(f"Сохранено: {data.STATUS_NAMES[new_status]}.")

    with tab_graph:
        cache = get_graph(str(db), str(extracted))
        sub, key_nodes, path = data.signal_subgraph(conn, cache, sid)
        if cache.doc_stats is None:
            st.caption("Рёбра из документов не загружены — выполните `make extract`.")
        st.caption("Синие — служащие, фиолетовые — внешние лица, оранжевые — организации, зелёные — группы, "
                   "серые — закупки. Пунктир — связь из распознанного документа; красный — путь И2.")
        components.html(graph_html(sub, key_nodes, path), height=600)

    with tab_doc:
        docs = {}
        for ev in d["evidence"]:
            docs.setdefault(ev["document_id"], set()).add(ev["id"])
        if not docs:
            st.write("У сигнала нет документов-оснований.")
        else:
            doc_id = st.selectbox("Документ", list(docs), key=f"doc_{sid}",
                                  format_func=lambda i: data.document_info(conn, i)["title"])
            info = data.document_info(conn, doc_id)
            for n, page in enumerate(data.document_pages_html(conn, doc_id, docs[doc_id]), start=1):
                st.markdown(f"**Страница {n}**")
                st.markdown(f"<div style='border:1px solid #ddd;padding:12px;font-family:serif'>{page}</div>",
                            unsafe_allow_html=True)
            f = db.parent / info["path"]
            if f.exists():
                st.download_button("Скачать DOCX", f.read_bytes(), file_name=f.name, key=f"dl_{sid}")


main()
