"""Заполнение шаблона паспорта проекта (10 блоков «Код прозрачности») фактами прототипа.

Запуск: python docs/passport/fill_passport.py ШАБЛОН.pptx docs/passport/passport.pptx
(нужен python-pptx; в requirements.txt проекта он не входит — это разовый инструмент оформления).

Заменяется только текст в квадратных скобках; оформление шаблона (шрифты, цвета, номера «01  ») сохраняется.
Поля, которые знает только команда (вуз, название команды, ФИО, опыт, название трека), остаются в скобках.
Блок 10 «Приложения» в шаблоне отсутствует (9 слайдов) — он создаётся копией слайда 7 по описанию из брифинга
организаторов (19.10.2026): презентация, репозиторий с инструкцией запуска, ролик, схемы, описание данных, тесты.
На титул добавляются поля «Прототип» и «Запуск» — брифинг требует в блоке 1 ссылку на прототип или порядок доступа.
Цифры качества — из reports/metrics.md (синтетика, seed 42 и отложенные seed 1–5).
"""

from __future__ import annotations

import copy
import sys

from pptx import Presentation

# (номер слайда, имя фигуры) -> абзацы, заменяющие абзацы-заглушки (содержащие «[» или «]»)
CONTENT: dict[tuple[int, str], list[str]] = {
    # 01 Карточка проекта
    (1, "TextBox 10"): ["Сигналы риска в решениях служащих с объяснением и документом-основанием"],
    (1, "TextBox 13"): ["04 — аналитика подразделений профилактики"],

    # 02 Проблема и целевая аудитория
    (2, "TextBox 8"): ["Риски в решениях служащих — закупки, полномочия, связи — ищут вручную и поздно"],
    (2, "TextBox 9"): ["39% конкурентных закупок по 44-ФЗ в 2023 г. — с одной заявкой (53% по объёму)",
                       "",
                       "Минфин России, 26.11.2024. Каждое такое решение — кандидат на разбор"],
    (2, "TextBox 12"): ["Отдел профилактики коррупции", "Отбор и разбор решений"],
    (2, "TextBox 15"): ["Короткий список решений с причиной", "Вывод о человеке — за проверяющим"],

    # 03 Цель и результаты
    (3, "TextBox 7"): ["Проверяющий получает список решений с признаками риска, причиной и документом-основанием"],
    (3, "TextBox 13"): ["Сигналы по 5 индикаторам с объяснением"],
    (3, "TextBox 14"): ["Recall внедрённых схем = 1,0"],
    (3, "TextBox 15"): ["Синтетика с внедрёнными схемами (make eval)"],
    (3, "TextBox 17"): ["Распознавание протоколов и приказов"],
    (3, "TextBox 18"): ["F1 на слепом наборе: ФИО 0,97, орг. 0,89"],
    (3, "TextBox 19"): ["Разметка генератора и документы в стиле ЕИС"],
    (3, "TextBox 21"): ["Точность и воспроизводимость сигналов"],
    (3, "TextBox 22"): ["precision@50 = 0,84; чистые контракты с сигналом — 2,5%"],
    (3, "TextBox 23"): ["Отложенные seed 1–5; одинаковый хэш при повторе"],

    # 04 Решение
    (4, "TextBox 8"): ["Смотрим на решения,", "а не на имущество"],
    (4, "TextBox 10"): ["Сверка имущества видит следствие; мы — сами решения",
                        "Правила и сравнение с коллегами, без облака и «чёрного ящика»"],
    (4, "TextBox 14"): ["Индикаторы И1–И4, И7 с порогами по коллегам"],
    (4, "TextBox 16"): ["Граф связей: родство, проекты, бывшие работодатели"],
    (4, "TextBox 18"): ["Распознавание документов и карточка с подсвеченным основанием"],

    # 05 Данные и аналитика
    (5, "TextBox 12"): ["Синтетика с пометкой source = synthetic (seed 42). Для пилота — открытые данные ЕИС "
                        "и кадровые сведения ведомства (273-ФЗ)"],
    (5, "TextBox 15"): ["1 ведомство, 150 служащих, 300 организаций, 2000 закупок за 2024–2025 гг., ~1500 документов; "
                        "честный шум и 5 внедрённых схем"],
    (5, "TextBox 18"): ["Правила и перцентили по группе коллег, точный тест случайности, графовый анализ, "
                        "NLP: Natasha + pymorphy3"],
    (5, "TextBox 21"): ["Recall/precision по внедрённым схемам, отложенные seed, F1 распознавания, слепой набор "
                        "документов, 99 автотестов"],
    (5, "TextBox 24"): ["У сигнала: правило, значение, порог, группа сравнения, текст объяснения и подсвеченный "
                        "фрагмент протокола или приказа; путь связи — на графе"],

    # 06 Архитектура и технологии
    (6, "TextBox 8"): ["Структура, полномочия, закупки, связи", "Маркеры: доля поставщика, родство, цена"],
    (6, "TextBox 10"): ["Python, SQLite, networkx, Natasha, Streamlit", "Открытые, работают без интернета"],
    (6, "TextBox 14"): ["Документы и БД"],
    (6, "TextBox 17"): ["Разбор документов"],
    (6, "TextBox 20"): ["Граф и индикаторы"],
    (6, "TextBox 23"): ["Сигналы в интерфейсе"],
    (6, "TextBox 25"): ["Фиксированный seed, без случайности и облачных LLM в конвейере: повторный прогон даёт тот же "
                        "хэш данных и сигналов на Windows и в Docker — закреплено тестами"],

    # 07 Безопасность, право и этика
    (7, "TextBox 12"): ["В прототипе нет: данные синтетические. В пилоте — ФИО и родство; минимизация, доступ "
                        "только подразделению"],
    (7, "TextBox 15"): ["Сигнал — не вывод: проверяющий видит основание и отклоняет ложный; пропуски — сверка "
                        "с ручной выборкой"],
    (7, "TextBox 18"): ["Статус сигнала, комментарий и любой вывод о служащем; рейтинга людей нет"],
    (7, "TextBox 21"): ["Синтетика; на реальных протоколах не проверено; только DOCX; И5, И6, И8 не реализованы"],
    (7, "TextBox 24"): ["Локально, без внешних API; роли и журнал решений — к пилоту; эталон скрыт"],

    # 08 Внедрение и эффект
    (8, "TextBox 15"): ["Выгрузка ЕИС и кадров, регламент"],
    (8, "TextBox 16"): ["Данные в схеме, доступ согласован"],
    (8, "TextBox 17"): ["1 ведомство, закупки 44-ФЗ"],
    (8, "TextBox 18"): ["Доступ к ЕИС по сертификату"],
    (8, "TextBox 21"): ["Разбор сигналов за год"],
    (8, "TextBox 22"): ["Precision ≥ 0,5 по оценке проверяющих"],
    (8, "TextBox 23"): ["Отдел профилактики"],
    (8, "TextBox 24"): ["Реальные протоколы, PDF"],
    (8, "TextBox 27"): ["Тиражирование, И5, И6, И8"],
    (8, "TextBox 28"): ["Регламент работы с сигналами утверждён"],
    (8, "TextBox 29"): ["Органы власти с закупками по 44-ФЗ"],
    (8, "TextBox 30"): ["Разные кадровые системы"],
    (8, "TextBox 32"): ["Короткий список решений с причиной; мера — время разбора и доля подтверждённых сигналов"],
    (8, "TextBox 34"): ["Объяснимые, воспроизводимые сигналы; решение о человеке принимает человек"],

    # 09 Команда (ФИО и опыт заполняет команда; роли — по распределению из PLAN.md)
    (9, "TextBox 14"): ["Распознавание"],
    (9, "TextBox 15"): ["Парсеры протоколов и приказов, реквизиты, NER"],
    (9, "TextBox 19"): ["Данные и граф"],
    (9, "TextBox 20"): ["Генератор синтетики, схемы риска, граф"],
    (9, "TextBox 24"): ["Аналитика и интерфейс"],
    (9, "TextBox 25"): ["Индикаторы, оценка качества, UI, паспорт"],
}

# Блок 10 «Приложения» (копия слайда 7): поля-заглушки копии и обычный текст заголовков.
BLOCK10_PLACEHOLDERS: dict[str, list[str]] = {
    "TextBox 12": ["Файл презентации на 10 минут защиты по шаблону организаторов [добавить в архив]"],
    "TextBox 15": ["github.com/zagid1/Hackathon · README: docker compose up --build, версии, шаги"],
    "TextBox 18": ["Демонстрация ключевого сценария до 10 мин [файл]; сценарий — docs/demo_script.md"],
    "TextBox 21": ["Схема данных — src/models/schema.sql; техсхема и данные — docs/TECHNICAL.md"],
    "TextBox 24": ["99 автотестов (make test); метрики качества — reports/metrics.md"],
}
BLOCK10_TEXT: dict[str, list[str]] = {
    "TextBox 1": ["10 / ПАСПОРТ ПРОЕКТА"],
    "TextBox 2": ["ПРИЛОЖЕНИЯ"],
    "TextBox 3": ["Что входит в архив и где это найти"],
    "TextBox 6": ["10/10"],
    "TextBox 8": ["Материал"],
    "TextBox 9": ["Где найти"],
    "TextBox 11": ["Презентация"],
    "TextBox 14": ["Репозиторий и запуск"],
    "TextBox 17": ["Ролик"],
    "TextBox 20": ["Схемы и описание данных"],
    "TextBox 23": ["Тесты и метрики"],
}
# Поля «Прототип» и «Запуск» на титуле: копии подписи/значения левой колонки, сдвинутые в правую.
TITLE_EXTRA = [("TextBox 12", "TextBox 13", "ПРОТОТИП", "github.com/zagid1/Hackathon"),
               ("TextBox 18", "TextBox 19", "ЗАПУСК", "docker compose up --build")]
RIGHT_COLUMN_X = int(6.82 * 914400)
REPO_HOST = "github.com/zagid1/Hackathon"
REPO_URL = "https://github.com/zagid1/Hackathon"

# Четвёртая строка таблицы команды и подсказка не нужны (в команде три человека).
DELETE = {(9, "TextBox 28"), (9, "TextBox 29"), (9, "TextBox 30"), (9, "TextBox 31"), (9, "TextBox 32")}


def _is_placeholder(par) -> bool:
    t = "".join(r.text for r in par.runs)
    return "[" in t or "]" in t


def fill(shape, texts: list[str]) -> None:
    from pptx.text.text import _Paragraph

    tf = shape.text_frame
    elems = [p._p for p in tf.paragraphs]
    marks = [i for i, p in enumerate(tf.paragraphs) if _is_placeholder(p)]
    if not marks:
        raise ValueError(f"в {shape.name} нет заглушки")
    # абзацы между первой и последней заглушкой (пустые разделители) тоже считаются частью поля
    slots = elems[marks[0]:marks[-1] + 1]
    while len(slots) < len(texts):                      # нужно больше абзацев — клонируем последний
        new = copy.deepcopy(slots[-1])
        slots[-1].addnext(new)
        slots.append(new)
    for p_el, text in zip(slots, texts):
        par = _Paragraph(p_el, tf)
        runs = par.runs
        if not runs:                                    # пустой абзац-разделитель
            if text:
                par.add_run().text = text
            continue
        bracket = [r for r in runs if "[" in r.text or "]" in r.text] or runs[:1]
        target = bracket[0]
        if "[" in target.text and target.text.index("[") > 0:   # «01  [Функция]» в одном прогоне
            target.text = target.text[: target.text.index("[")] + text
        else:
            target.text = text
        for r in bracket[1:]:
            r._r.getparent().remove(r._r)
    for p_el in slots[len(texts):]:                     # лишние абзацы заглушки удаляем
        p_el.getparent().remove(p_el)


def set_text(shape, texts: list[str]) -> None:
    """Заменить весь текст фигуры, сохранив оформление первого прогона каждого абзаца."""
    from pptx.text.text import _Paragraph

    tf = shape.text_frame
    pars = [p._p for p in tf.paragraphs]
    while len(pars) < len(texts):
        new = copy.deepcopy(pars[-1])
        pars[-1].addnext(new)
        pars.append(new)
    for p_el, text in zip(pars, texts):
        par = _Paragraph(p_el, tf)
        runs = par.runs
        if not runs:
            par.add_run().text = text
            continue
        runs[0].text = text
        for r in runs[1:]:
            r._r.getparent().remove(r._r)
    for p_el in pars[len(texts):]:
        p_el.getparent().remove(p_el)


def duplicate_slide(prs, index: int):
    """Копия слайда (фон и фигуры) в конец презентации. У исходных слайдов-таблиц нет картинок."""
    src = prs.slides[index]
    dst = prs.slides.add_slide(src.slide_layout)
    # python-pptx кэширует dst.shapes на текущем spTree — меняем его содержимое, а не сам элемент
    dst_tree, src_tree = dst._element.cSld.spTree, src._element.cSld.spTree
    for child in list(dst_tree):
        dst_tree.remove(child)
    for child in src_tree:
        dst_tree.append(copy.deepcopy(child))
    src_bg = src._element.cSld.bg
    if src_bg is not None:
        dst_tree.addprevious(copy.deepcopy(src_bg))
    return dst


def add_title_fields(slide) -> None:
    by_name = {sh.name: sh for sh in slide.shapes}
    for label_name, value_name, label, value in TITLE_EXTRA:
        for name, text in ((label_name, label), (value_name, value)):
            el = copy.deepcopy(by_name[name]._element)
            slide.shapes._spTree.append(el)
            shape = slide.shapes[-1]
            shape.left = RIGHT_COLUMN_X
            shape.name = f"{name} right"
            set_text(shape, [text])


def main(src: str, dst: str) -> None:
    prs = Presentation(src)
    block10 = duplicate_slide(prs, 6)          # копия слайда 7 (до заполнения — в ней ещё заглушки)
    add_title_fields(prs.slides[0])
    done = set()
    for i, slide in enumerate(prs.slides, start=1):
        for shape in list(slide.shapes):
            key = (i, shape.name)
            if key in DELETE:
                shape._element.getparent().remove(shape._element)
                done.add(key)
            elif key in CONTENT:
                fill(shape, CONTENT[key])
                done.add(key)
    for shape in block10.shapes:
        if shape.name in BLOCK10_PLACEHOLDERS:
            fill(shape, BLOCK10_PLACEHOLDERS[shape.name])
        elif shape.name in BLOCK10_TEXT:
            set_text(shape, BLOCK10_TEXT[shape.name])
    # слайд 9: без четвёртой строки карточка таблицы заканчивается у линии под третьей строкой
    team = prs.slides[8]
    line = next(sh for sh in team.shapes if sh.name == "Connector 27")
    for sh in team.shapes:
        if sh.shape_type == 1 and sh.top < line.top < sh.top + sh.height:      # AUTO_SHAPE-карточка
            sh.height = line.top + int(0.18 * 914400) - sh.top
    missing = (set(CONTENT) | DELETE) - done
    if missing:
        raise SystemExit(f"не найдены фигуры: {sorted(missing)}")
    # ссылка на репозиторий кликабельна везде, где упомянута
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for par in shape.text_frame.paragraphs:
                    for run in par.runs:
                        if REPO_HOST in run.text:
                            run.hyperlink.address = REPO_URL
    prs.save(dst)
    print(f"сохранено: {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
