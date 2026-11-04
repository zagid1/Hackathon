"""Документы-основания: протоколы закупочных комиссий и приказы о создании групп (DOCX)
+ разметка сущностей (ground truth для модуля распознавания, формат раздела 8 PLAN.md).

Каноническая модель текста (по ней считаются page и span в doc_fragments и в разметке):
* документ делится на страницы явными разрывами страницы (<w:br w:type="page"/>);
* текст страницы = блоки страницы, соединённые "\\n";
* блок — абзац (paragraph.text, разрыв строки внутри абзаца = "\\n") или строка таблицы
  (тексты ячеек через " | ");
* span = [start, end) в тексте страницы; page считается с 1.
Функция read_docx_pages() реализует ровно эту модель — её можно переиспользовать в extraction.

На тип документа — 3 шаблона формулировок (падежи ФИО, таблица/список, формат сумм,
полное/краткое наименование организации, неразрывные пробелы, переносы строк).

Детерминированность DOCX: фиксированные core properties и время элементов zip-архива.
Побайтное совпадение файлов гарантируется в одном окружении (одна версия zlib).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from src.models.entities import DocFragment, DocType, Document, GroupKind, Method

from .common import World
from .companies import LEGAL_FORM_FULL, LEGAL_FORM_FULL_INS, normalize_org_name
from .names import PersonName
from .org import HEAD
from .procurement import ProcMeta

MONTHS = ("", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
          "октября", "ноября", "декабря")
NBSP = " "
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

METHOD_NOM = {Method.AUCTION: "электронный аукцион", Method.TENDER: "открытый конкурс в электронной форме",
              Method.QUOTATION: "запрос котировок в электронной форме"}
METHOD_GEN = {Method.AUCTION: "электронного аукциона", Method.TENDER: "открытого конкурса в электронной форме",
              Method.QUOTATION: "запроса котировок в электронной форме"}

ROLE_TITLES = {
    GroupKind.COMMISSION: {"CHAIR": "председатель комиссии", "DEPUTY_CHAIR": "заместитель председателя комиссии",
                           "MEMBER": "член комиссии", "SECRETARY": "секретарь комиссии"},
    GroupKind.WORKGROUP: {"LEADER": "руководитель рабочей группы", "MEMBER": "член рабочей группы",
                          "SECRETARY": "секретарь рабочей группы"},
    GroupKind.PROJECT: {"LEADER": "руководитель проектной группы", "MEMBER": "член проектной группы"},
}
GROUP_HEAD_CASES = {  # именительный -> (родительный, винительный)
    "Единая комиссия": ("единой комиссии", "единую комиссию"),
    "Рабочая группа": ("рабочей группы", "рабочую группу"),
    "Проектная группа": ("проектной группы", "проектную группу"),
}


# ---------------------------------------------------------------------------------------------
# Форматирование

def date_long(d: dt.date) -> str:
    return f"«{d.day:02d}» {MONTHS[d.month]} {d.year} г."


def date_short(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def _group_thousands(n: int, sep: str) -> str:
    return f"{n:,}".replace(",", sep)


def money(kop: int, fmt: str) -> str:
    r, k = divmod(kop, 100)
    if fmt == "spaced":         # 1 250 000,00 руб.
        return f"{_group_thousands(r, ' ')},{k:02d} руб."
    if fmt == "nbsp":           # 1 250 000,00 руб. с неразрывными пробелами
        return f"{_group_thousands(r, NBSP)},{k:02d}{NBSP}руб."
    if fmt == "plain":          # 1250000.00 рублей
        return f"{r}.{k:02d} рублей"
    if fmt == "kop":            # 1 250 000 руб. 00 коп.
        return f"{_group_thousands(r, ' ')} руб. {k:02d} коп."
    if fmt == "table":          # 1 250 000,00
        return f"{_group_thousands(r, ' ')},{k:02d}"
    raise ValueError(fmt)


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:]


def group_name_case(name: str, case: str) -> str:
    for head, (gen, acc) in GROUP_HEAD_CASES.items():
        if name.startswith(head):
            return {"gen": gen, "acc": acc}[case] + name[len(head):]
    return name


def reg_number(unit_id: int, published: str, pid: int) -> str:
    return f"0373100{unit_id:03d}{published[2:4]}{pid:07d}"


# ---------------------------------------------------------------------------------------------
# Построитель документа с учётом смещений

@dataclass
class Ent:
    text: str
    type: str                       # PERSON, ORG, INN, OGRN, MONEY
    normalized: Any = None
    role: Optional[str] = None
    ref: Optional[str] = None       # ссылка на строку БД: employee:12, person:7, organization:5
    key: Optional[str] = None       # идентификатор для relations (например, ORG:ООО РОМАШКА)


Seg = Union[str, Ent]


@dataclass
class Block:
    kind: str                       # p | row
    parts: list[list[Seg]]          # абзац: [segs]; строка таблицы: [segs ячейки 1, segs ячейки 2, ...]
    style: Optional[str] = None     # title | center | header
    rels: list[dict] = field(default_factory=list)


@dataclass
class BuiltDoc:
    pages: list[str]
    blocks: list[tuple[int, int, int, Block]]        # (page, start, end, block)
    entities: list[dict]
    relations: list[dict]


def _no_double_dot(segs: list[Seg]) -> list[Seg]:
    """«1 000,00 руб.» + «.» -> без второй точки в конце предложения."""
    out: list[Seg] = []
    for seg in segs:
        prev = out[-1] if out else None
        prev_text = prev.text if isinstance(prev, Ent) else (prev or "")
        if isinstance(seg, str) and seg.startswith(".") and prev_text.endswith("."):
            seg = seg[1:]
            if not seg:
                continue
        out.append(seg)
    return out


class DocBuilder:
    def __init__(self) -> None:
        self.pages: list[list[Block]] = [[]]

    def p(self, *segs: Seg, style: Optional[str] = None) -> Block:
        b = Block("p", [_no_double_dot(list(segs))], style)
        self.pages[-1].append(b)
        return b

    def row(self, *cells: Union[Seg, list[Seg]], style: Optional[str] = None) -> Block:
        b = Block("row", [c if isinstance(c, list) else [c] for c in cells], style)
        self.pages[-1].append(b)
        return b

    def page_break(self) -> None:
        self.pages.append([])

    def build(self) -> BuiltDoc:
        page_texts, blocks, entities, relations = [], [], [], []
        for page_no, page in enumerate(self.pages, start=1):
            pos = 0
            texts = []
            for b in page:
                start = pos
                cursor = pos
                cell_texts = []
                for ci, cell in enumerate(b.parts):
                    if ci:
                        cursor += 3            # " | "
                    chunk = []
                    for seg in cell:
                        t = seg.text if isinstance(seg, Ent) else seg
                        if isinstance(seg, Ent):
                            e = {"type": seg.type, "value": seg.text, "page": page_no,
                                 "span": [cursor, cursor + len(t)]}
                            if seg.normalized is not None:
                                e["normalized"] = seg.normalized
                            if seg.type == "INN":
                                e["valid_checksum"] = True
                            if seg.role:
                                e["role"] = seg.role
                            if seg.ref:
                                e["ref"] = seg.ref
                            entities.append(e)
                        chunk.append(t)
                        cursor += len(t)
                    cell_texts.append("".join(chunk))
                text = " | ".join(cell_texts)
                assert len(text) == cursor - start
                texts.append(text)
                pos = cursor + 1               # "\n" между блоками
                blocks.append((page_no, start, cursor, b))
                for r in b.rels:
                    relations.append({**r, "page": page_no, "evidence_span": [start, cursor]})
            page_texts.append("\n".join(texts))
        return BuiltDoc(page_texts, blocks, entities, relations)


# ---------------------------------------------------------------------------------------------
# Сущности

def person_ent(w: World, kind: str, ref_id: int, form: str, role: Optional[str] = None) -> Ent:
    pn: PersonName = w.employees[ref_id].name if kind == "employee" else w.person_names[ref_id]
    if form in ("nom", "gen", "dat", "acc"):
        text = pn.case(form)
    elif form == "init_after":
        text = pn.initials_after()
    else:
        text = pn.initials_before()
    return Ent(text, "PERSON", pn.full, role, f"{kind}:{ref_id}", f"PERSON:{pn.full}")


def org_ent(w: World, org_id: int, full: bool = False, role: Optional[str] = None, ins: bool = False) -> Ent:
    """full — полное наименование формы; ins — в творительном падеже («с Обществом ...»)."""
    o = w.orgs[org_id]
    forms = LEGAL_FORM_FULL_INS if ins else LEGAL_FORM_FULL
    text = f"{forms[o.legal_form]} «{o.core}»" if full else o.name
    norm = normalize_org_name(o.legal_form, o.core)
    return Ent(text, "ORG", norm, role, f"organization:{org_id}", f"ORG:{norm}")


def inn_ent(w: World, org_id: int) -> Ent:
    return Ent(w.orgs[org_id].inn, "INN", ref=f"organization:{org_id}")


def ogrn_ent(w: World, org_id: int) -> Ent:
    return Ent(w.orgs[org_id].ogrn, "OGRN", ref=f"organization:{org_id}")


def money_ent(kop: int, fmt: str, role: str) -> Ent:
    return Ent(money(kop, fmt), "MONEY", kop / 100, role, key=f"MONEY:{kop // 100}.{kop % 100:02d}")


# ---------------------------------------------------------------------------------------------
# Протоколы

def _kop(x: float) -> int:
    return int(round(x * 100))


def build_protocol(w: World, pid: int, pm: ProcMeta, variant: int, order_info) -> BuiltDoc:
    ds = w.ds
    proc = ds.procurements[pid - 1]
    bids = [ds.bids[i - 1] for i in pm.bid_ids]
    contract = ds.contracts[pm.contract_id - 1]
    group = w.groups[proc.commission_group_id]
    members = [(mid, role) for mt, mid, role in group.members if mt == "employee"]
    reg = reg_number(proc.unit_id, proc.published_at, pid)
    nmck = _kop(proc.nmck)
    win_org = contract.supplier_org_id
    win_price = _kop(contract.price)
    single = len(bids) == 1
    titles = ROLE_TITLES[GroupKind.COMMISSION]
    role_code = {r: f"COMMISSION_{r}" for r in titles}
    target = f"PROCUREMENT:{pid}"
    agency = w.units[1]
    b = DocBuilder()

    def bid_rel(blk: Block, org_id: int, kop: int) -> None:
        o = w.orgs[org_id]
        blk.rels.append({"type": "BID", "from": f"ORG:{normalize_org_name(o.legal_form, o.core)}",
                         "to": f"MONEY:{kop // 100}.{kop % 100:02d}"})

    def win_rel(blk: Block) -> None:
        o = w.orgs[win_org]
        blk.rels.append({"type": "WINNER", "from": f"ORG:{normalize_org_name(o.legal_form, o.core)}",
                         "to": target})

    if variant == 0:
        b.p("ПРОТОКОЛ ПОДВЕДЕНИЯ ИТОГОВ ОПРЕДЕЛЕНИЯ ПОСТАВЩИКА (ПОДРЯДЧИКА, ИСПОЛНИТЕЛЯ)", style="title")
        b.p(f"№ {reg}-3", style="center")
        b.p(f"г. Москва\n{date_long(pm.protocol_date)}")
        b.p(f"Заказчик: {agency}")
        b.p(f"Способ определения поставщика: {METHOD_NOM[proc.method]}")
        b.p(f"Объект закупки: {pm.subject} (ОКПД2 {proc.okpd2})")
        b.p("Начальная (максимальная) цена контракта: ", money_ent(nmck, "spaced", "NMCK"))
        b.p(f"Заседание проводит {lower_first(group.name)}, созданная приказом от "
            f"{date_short(order_info.doc_date)} № {order_info.doc_number}. Присутствовали:")
        for mid, role in members:
            b.p(f"{titles[role].capitalize()}: ", person_ent(w, "employee", mid, "nom", role_code[role]))
        b.p("Кворум имеется, комиссия правомочна.")
        b.page_break()
        b.p("Сведения об участниках закупки и предложениях о цене контракта:")
        for i, bid in enumerate(bids, start=1):
            k = _kop(bid.price)
            blk = b.p(f"{i}. ", org_ent(w, bid.org_id, role="BIDDER"), ", ИНН ", inn_ent(w, bid.org_id),
                      ", предложение о цене контракта: ", money_ent(k, "spaced", "BID"))
            bid_rel(blk, bid.org_id, k)
        if single:
            blk = b.p("Решение комиссии: в связи с подачей только одной заявки определение поставщика признано "
                      "несостоявшимся (ч. 1 ст. 52 44-ФЗ). Контракт заключается с единственным участником ",
                      org_ent(w, win_org, role="WINNER"), " по цене ", money_ent(win_price, "spaced", "CONTRACT_PRICE"),
                      ".")
        else:
            blk = b.p("Решение комиссии: признать победителем ", org_ent(w, win_org, role="WINNER"), " (ИНН ",
                      inn_ent(w, win_org), ") с предложением о цене контракта ",
                      money_ent(win_price, "spaced", "CONTRACT_PRICE"), ".")
        win_rel(blk)
        b.p(f"Результаты голосования: «за» — {len(members)}, «против» — 0.")
        for mid, role in members:
            b.p(f"{titles[role].capitalize()} ____________ ",
                person_ent(w, "employee", mid, "init_before", role_code[role]))

    elif variant == 1:
        b.p(f"ПРОТОКОЛ\nподведения итогов {METHOD_GEN[proc.method]}", style="title")
        b.p(f"{date_short(pm.protocol_date)}    № {reg}")
        b.p(f"Предмет закупки: {pm.subject}. Код по ОКПД2: {proc.okpd2}. НМЦК: ", money_ent(nmck, "plain", "NMCK"))
        segs: list[Seg] = ["Комиссия в составе:"]
        prefix = {"CHAIR": " председателя комиссии ", "DEPUTY_CHAIR": ", заместителя председателя ",
                  "SECRETARY": ",\nсекретаря комиссии "}
        first_member = True
        for mid, role in members:
            if role == "MEMBER":
                segs.append(", членов комиссии " if first_member else ", ")
                first_member = False
            else:
                segs.append(prefix[role])
            segs.append(person_ent(w, "employee", mid, "gen", role_code[role]))
        segs.append(" рассмотрела заявки участников закупки.")
        b.p(*segs)
        b.page_break()
        b.p("Таблица 1. Предложения участников закупки")
        b.row("№", "Участник закупки", "ИНН", "Цена, руб.", style="header")
        for i, bid in enumerate(bids, start=1):
            k = _kop(bid.price)
            blk = b.row(str(i), org_ent(w, bid.org_id, role="BIDDER"), inn_ent(w, bid.org_id),
                        money_ent(k, "table", "BID"))
            bid_rel(blk, bid.org_id, k)
        blk = b.p("По результатам рассмотрения комиссия решила: ",
                  "заключить контракт с единственным участником " if single else "победителем признан участник ",
                  org_ent(w, win_org, role="WINNER"), ", предложивший цену контракта ",
                  money_ent(win_price, "spaced", "CONTRACT_PRICE"), ".")
        win_rel(blk)
        segs = ["Подписи членов комиссии: "]
        for i, (mid, role) in enumerate(members):
            if i:
                segs.append(", ")
            segs.append(person_ent(w, "employee", mid, "init_after", role_code[role]))
        b.p(*segs)

    else:
        b.p(f"Протокол № {reg}-2\nрассмотрения и оценки заявок на участие в закупке", style="title")
        b.p(f"Дата подписания протокола: {date_long(pm.protocol_date)}")
        b.p(f"Наименование объекта закупки: {pm.subject}; НМЦК ", money_ent(nmck, "kop", "NMCK"))
        b.p("Состав комиссии:")
        order = [m for m in members if m[1] == "SECRETARY"] + [m for m in members if m[1] != "SECRETARY"]
        for mid, role in order:
            b.p(person_ent(w, "employee", mid, "nom", role_code[role]), f" — {titles[role]}")
        b.page_break()
        b.p("Поступившие предложения:")
        for bid in bids:
            k = _kop(bid.price)
            blk = b.p("Предложение ", money_ent(k, "nbsp", "BID"), " — ",
                      org_ent(w, bid.org_id, full=True, role="BIDDER"), " (ИНН ", inn_ent(w, bid.org_id),
                      ", ОГРН ", ogrn_ent(w, bid.org_id), ")")
            bid_rel(blk, bid.org_id, k)
        blk = b.p("Комиссия единогласно решила заключить контракт с ", org_ent(w, win_org, full=True, role="WINNER", ins=True),
                  " на сумму ", money_ent(win_price, "kop", "CONTRACT_PRICE"),
                  " (единственная заявка)." if single else ".")
        win_rel(blk)
    return b.build()


# ---------------------------------------------------------------------------------------------
# Приказы

def _member_ent(w: World, kind: str, mtype: str, mid: int, role: str, form: str) -> Ent:
    return person_ent(w, mtype, mid, form, f"{kind}_{role}")


def _who(w: World, mtype: str, mid: int) -> list[Seg]:
    if mtype == "employee":
        return [lower_first(w.employees[mid].title)]
    org_id = next(o for o, p in sorted(w.org_director.items()) if p == mid) if mid in w.org_director.values() \
        else next(o for o, ps in sorted(w.org_founders.items()) if mid in ps)
    return ["представитель ", org_ent(w, org_id, role="AFFILIATION"), " (по согласованию)"]


def build_order(w: World, gid: int, variant: int) -> BuiltDoc:
    gi = w.groups[gid]
    titles = ROLE_TITLES[gi.kind]
    head = next(e.id for e in w.employees.values() if e.role == HEAD)
    b = DocBuilder()
    target = f"GROUP:{gid}"

    def member_rel(blk: Block, mtype: str, mid: int, role: str) -> None:
        pn = w.employees[mid].name if mtype == "employee" else w.person_names[mid]
        blk.rels.append({"type": "MEMBER", "from": f"PERSON:{pn.full}", "to": target, "role": role})

    basis = ("В соответствии со статьей 39 Федерального закона от 05.04.2013 № 44-ФЗ «О контрактной системе "
             "в сфере закупок товаров, работ, услуг для обеспечения государственных и муниципальных нужд»"
             if gi.kind == GroupKind.COMMISSION else "В целях организации работы")

    if variant == 0:
        b.p("ПРИКАЗ", style="title")
        b.p(f"{date_long(gi.doc_date)}    № {gi.doc_number}")
        b.p(f"О создании {group_name_case(gi.name, 'gen')}", style="center")
        b.p(f"{basis} приказываю:")
        b.p(f"1. Создать {group_name_case(gi.name, 'acc')} в следующем составе:")
        for mtype, mid, role in gi.members:
            blk = b.p(_member_ent(w, gi.kind, mtype, mid, role, "nom"), " — ", *_who(w, mtype, mid),
                      f" ({titles[role]});")
            member_rel(blk, mtype, mid, role)
        b.p("2. Контроль за исполнением настоящего приказа оставляю за собой.")
        b.p("Руководитель    ", person_ent(w, "employee", head, "init_before", "SIGNATORY"))
    elif variant == 1:
        b.p(f"ПРИКАЗ\nоб утверждении состава {group_name_case(gi.name, 'gen')}", style="title")
        b.p(f"№ {gi.doc_number} от {date_short(gi.doc_date)}")
        b.p(f"{basis}\nприказываю:")
        b.p(f"1. Утвердить состав {group_name_case(gi.name, 'gen')}.")
        n = 2
        for want, verb in (("CHAIR", "председателем"), ("LEADER", "руководителем"),
                           ("DEPUTY_CHAIR", "заместителем председателя")):
            for mtype, mid, role in gi.members:
                if role == want:
                    blk = b.p(f"{n}. Назначить {verb} ", _member_ent(w, gi.kind, mtype, mid, role, "acc"),
                              ", ", *_who(w, mtype, mid), ".")
                    member_rel(blk, mtype, mid, role)
                    n += 1
        plain = [(t, i, r) for t, i, r in gi.members if r == "MEMBER"]
        if plain:
            segs: list[Seg] = [f"{n}. Включить в состав в качестве членов: "]
            for k, (mtype, mid, role) in enumerate(plain):
                if k:
                    segs.append(";\n" if k % 2 == 0 else "; ")
                segs += [_member_ent(w, gi.kind, mtype, mid, role, "acc"), " (", *_who(w, mtype, mid), ")"]
            segs.append(".")
            blk = b.p(*segs)
            for mtype, mid, role in plain:
                member_rel(blk, mtype, mid, role)
            n += 1
        for mtype, mid, role in gi.members:
            if role == "SECRETARY":
                blk = b.p(f"{n}. Назначить секретарем ", _member_ent(w, gi.kind, mtype, mid, role, "acc"), ".")
                member_rel(blk, mtype, mid, role)
                n += 1
        b.p("Руководитель ведомства ", person_ent(w, "employee", head, "init_after", "SIGNATORY"))
    else:
        b.p("ПРИКАЗ", style="title")
        b.p(f"г. Москва, {date_short(gi.doc_date)}, № {gi.doc_number}")
        b.p(f"О создании {group_name_case(gi.name, 'gen')}", style="center")
        b.p(f"{basis} приказываю создать {group_name_case(gi.name, 'acc')} в составе согласно таблице.")
        b.page_break()
        b.p("Приложение к приказу. Состав группы")
        b.row("ФИО", "Должность / организация", "Роль", style="header")
        for mtype, mid, role in gi.members:
            blk = b.row(_member_ent(w, gi.kind, mtype, mid, role, "nom"), _who(w, mtype, mid), titles[role])
            member_rel(blk, mtype, mid, role)
        b.p("Руководитель    ", person_ent(w, "employee", head, "init_before", "SIGNATORY"))
    return b.build()


# ---------------------------------------------------------------------------------------------
# Рендеринг и чтение DOCX

def render_docx(built: BuiltDoc, title: str, doc_date: dt.date) -> bytes:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    d = docx.Document()
    cp = d.core_properties
    stamp = dt.datetime(doc_date.year, doc_date.month, doc_date.day, 9, 0, 0)
    cp.author = "synthetic generator"
    cp.last_modified_by = "synthetic generator"
    cp.title = title
    cp.comments = "Синтетический документ (source = synthetic)"
    cp.created = stamp
    cp.modified = stamp
    cp.last_printed = stamp
    cp.revision = 1

    def seg_text(seg: Seg) -> str:
        return seg.text if isinstance(seg, Ent) else seg

    pages: dict[int, list[Block]] = {}
    for page, _, _, blk in built.blocks:
        pages.setdefault(page, []).append(blk)
    for page in sorted(pages):
        if page > 1:
            d.add_page_break()
        blocks = pages[page]
        i = 0
        while i < len(blocks):
            blk = blocks[i]
            if blk.kind == "p":
                para = d.add_paragraph()
                if blk.style in ("title", "center"):
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for seg in blk.parts[0]:
                    run = para.add_run(seg_text(seg))
                    if blk.style == "title":
                        run.bold = True
                i += 1
                continue
            j = i
            while j < len(blocks) and blocks[j].kind == "row":
                j += 1
            rows = blocks[i:j]
            table = d.add_table(rows=len(rows), cols=len(rows[0].parts))
            table.style = "Table Grid"
            for r, rb in enumerate(rows):
                for c, cell in enumerate(rb.parts):
                    table.cell(r, c).text = "".join(seg_text(s) for s in cell)
                    if rb.style == "header":
                        for run in table.cell(r, c).paragraphs[0].runs:
                            run.bold = True
            i = j

    raw = io.BytesIO()
    d.save(raw)
    return normalize_zip(raw.getvalue())


def normalize_zip(data: bytes) -> bytes:
    """Переупаковывает zip с фиксированными временем и атрибутами элементов."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3
            zi.external_attr = 0o644 << 16
            dst.writestr(zi, src.read(info.filename), compresslevel=6)
    return out.getvalue()


def read_docx_pages(path: Union[str, Path, io.BytesIO]) -> list[str]:
    """Тексты страниц DOCX по канонической модели (см. docstring модуля)."""
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(path)
    pages: list[list[str]] = [[]]
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, d)
            text = para.text
            if not text and child.xpath('.//w:br[@w:type="page"]'):
                pages.append([])
                continue
            pages[-1].append(text)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, d).rows:
                pages[-1].append(" | ".join(c.text for c in row.cells))
    return ["\n".join(p) for p in pages]


# ---------------------------------------------------------------------------------------------
# Сборка всех документов

def _variant(w: World, kind: str, obj_id: int) -> int:
    return w.rng(f"doc:{kind}:{obj_id}").randrange(3)


def build_documents(w: World, meta: dict[int, ProcMeta], scheme_procurements: set[int],
                    out_dir: Optional[Path] = None) -> None:
    """Строки documents/doc_fragments всегда; DOCX + JSON-разметка — если задан out_dir."""
    cfg = w.cfg.get("documents", {})
    ds = w.ds
    docs_subdir = w.cfg["paths"]["docs_subdir"]
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[int, str, int, Document, BuiltDoc, str]] = []

    for gid in sorted(w.groups):
        gi = w.groups[gid]
        name = f"order_{gid:03d}"
        built = build_order(w, gid, _variant(w, "order", gid))
        doc = Document(gi.doc_id, DocType.ORDER, f"{docs_subdir}/{name}.docx", object_type="group",
                       object_id=gid, doc_number=gi.doc_number, doc_date=gi.doc_date.isoformat())
        jobs.append((gi.doc_id, name, gid, doc, built, f"Приказ № {gi.doc_number}"))

    eligible = [pid for pid, pm in sorted(meta.items()) if pm.bid_ids and pm.contract_id is not None]
    limit = cfg.get("max_protocols")
    if limit is not None:
        first = [p for p in eligible if p in scheme_procurements]
        rest = [p for p in eligible if p not in scheme_procurements]
        eligible = sorted(first + rest[: max(0, limit - len(first))])
    for pid in eligible:
        pm = meta[pid]
        proc = ds.procurements[pid - 1]
        order_info = w.groups[proc.commission_group_id]
        name = f"protocol_{pid:04d}"
        built = build_protocol(w, pid, pm, _variant(w, "protocol", pid), order_info)
        doc_id = w.doc_ids.next()
        number = f"{reg_number(proc.unit_id, proc.published_at, pid)}"
        doc = Document(doc_id, DocType.PROTOCOL, f"{docs_subdir}/{name}.docx", object_type="procurement",
                       object_id=pid, doc_number=number, doc_date=pm.protocol_date.isoformat())
        jobs.append((doc_id, name, pid, doc, built, f"Протокол № {number}"))

    jobs.sort(key=lambda j: j[0])
    frag_id = 0
    for doc_id, name, _, doc, built, title in jobs:
        ds.documents.append(doc)
        for page, start, end, blk in built.blocks:
            frag_id += 1
            ds.doc_fragments.append(DocFragment(frag_id, doc_id, page, start, end,
                                                built.pages[page - 1][start:end]))
        if out_dir is not None:
            data = render_docx(built, title, dt.date.fromisoformat(doc.doc_date))
            (out_dir / f"{name}.docx").write_bytes(data)
            ann = {"doc_id": name, "doc_type": doc.doc_type, "db_document_id": doc_id,
                   "pages": len(built.pages), "entities": built.entities, "relations": built.relations}
            (out_dir / f"{name}.json").write_text(
                json.dumps(ann, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                newline="\n")
