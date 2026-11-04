import json

import pytest

from src.extraction.ner import extract_entities, find_initials, find_orgs, normalize_fio
from src.generator.documents import read_docx_pages


@pytest.mark.parametrize("words, expected", [
    (("Покровской", "Марии", "Ильиничны"), "Покровская Мария Ильинична"),
    (("Шевченко", "Ильи", "Павловича"), "Шевченко Илья Павлович"),
    (("Иванову", "Анну", "Сергеевну"), "Иванова Анна Сергеевна"),
    (("Котова", "Никиту", "Сергеевича"), "Котов Никита Сергеевич"),
    (("Черных", "Ольги", "Никитичны"), "Черных Ольга Никитична"),
    (("Луцкую", "Евгению", "Дмитриевну"), "Луцкая Евгения Дмитриевна"),
    (("Лебедевой", "Алины", "Владимировны"), "Лебедева Алина Владимировна"),
    (("Ковалевой", "Марии", "Федоровны"), "Ковалева Мария Федоровна"),     # «ё» -> «е»
])
def test_normalize_fio(words, expected):
    assert normalize_fio(*words) == expected


def test_normalize_fio_requires_patronymic():
    assert normalize_fio("Комиссия", "Решила", "Признать") is None


def test_orgs_rules():
    text = "Победитель — Обществом с ограниченной ответственностью «Вектор-Строй», участник ПАО «Гранит»."
    orgs = find_orgs(text)
    assert [o["normalized"] for o in orgs] == ["ООО ВЕКТОР-СТРОЙ", "ПАО ГРАНИТ"]
    for o in orgs:
        assert text[o["span"][0]:o["span"][1]] == o["value"]


def test_initials_rules():
    found = find_initials("Председатель ____ И.П. Иванов, секретарь Петрова А. С.; Руководитель Л.С. Лукьянова")
    assert [f["normalized"] for f in found] == ["Иванов И. П.", "Петрова А. С.", "Лукьянова Л. С."]


def test_extract_entities_mixed_text():
    text = ("Комиссия в составе: председателя комиссии Покровской Марии Ильиничны, секретаря Котова Никиты "
            "Сергеевича рассмотрела заявку ООО «Ромашка». Подпись: И.И. Петров.")
    ents = extract_entities(text)
    persons = [e["normalized"] for e in ents if e["type"] == "PERSON"]
    assert persons == ["Покровская Мария Ильинична", "Котов Никита Сергеевич", "Петров И. И."]
    assert [e["normalized"] for e in ents if e["type"] == "ORG"] == ["ООО РОМАШКА"]
    assert extract_entities(text) == ents      # детерминированно


def test_quality_on_generated_corpus(small_build):
    """На документах генератора (3 шаблона на тип): границы и нормализация ФИО и организаций."""
    out, _ = small_build
    total = hit = norm_ok = init_total = init_hit = 0
    for ann_path in sorted((out / "docs").glob("*.json")):
        ann = json.loads(ann_path.read_text(encoding="utf-8"))
        pages = read_docx_pages(ann_path.with_suffix(".docx"))
        pred = {(e["page"], tuple(e["span"]), e["type"]): e for p, t in enumerate(pages, 1)
                for e in extract_entities(t, p)}
        for g in ann["entities"]:
            if g["type"] not in ("PERSON", "ORG"):
                continue
            p = pred.get((g["page"], tuple(g["span"]), g["type"]))
            if "." in g["value"] and g["type"] == "PERSON":
                init_total += 1
                init_hit += p is not None
                continue
            total += 1
            hit += p is not None
            norm_ok += p is not None and p["normalized"] == g["normalized"]
    assert total > 200 and init_total > 30
    assert hit / total >= 0.98 and norm_ok / total >= 0.97
    assert init_hit / init_total >= 0.95


def test_individual_entrepreneur_is_org_not_person():
    text = "1 | Индивидуальный предприниматель Борисов Кирилл Андреевич | 500312345614 | 598 500,00\nИП Петров П. П."
    ents = extract_entities(text)
    assert [(e["type"], e["normalized"]) for e in ents] == [("ORG", "ИП БОРИСОВ КИРИЛЛ АНДРЕЕВИЧ"),
                                                            ("ORG", "ИП ПЕТРОВ П. П.")]
