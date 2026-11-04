"""Русские ФИО и их склонение (именительный, родительный, дательный, винительный падежи).

Списки подобраны так, чтобы склонение по правилам было корректным: фамилии на -ов/-ев/-ин,
-ский/-цкий и несклоняемые на -ко/-их/-ых. Склонённые формы нужны документам генератора,
а модуль распознавания должен уметь нормализовать их обратно в именительный падеж.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

MALE = "M"
FEMALE = "F"
CASES = ("nom", "gen", "dat", "acc")

SURNAMES = (
    "Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Михайлов", "Новиков",
    "Федоров", "Морозов", "Волков", "Алексеев", "Лебедев", "Семенов", "Егоров", "Павлов", "Козлов",
    "Степанов", "Николаев", "Орлов", "Андреев", "Макаров", "Никитин", "Захаров", "Зайцев", "Соловьев",
    "Борисов", "Яковлев", "Григорьев", "Романов", "Воробьев", "Сергеев", "Кузьмин", "Фролов",
    "Александров", "Дмитриев", "Королев", "Гусев", "Киселев", "Ильин", "Максимов", "Поляков",
    "Сорокин", "Виноградов", "Ковалев", "Белов", "Медведев", "Антонов", "Тарасов", "Жуков", "Баранов",
    "Филиппов", "Комаров", "Давыдов", "Беляев", "Герасимов", "Богданов", "Осипов", "Сидоров",
    "Матвеев", "Титов", "Марков", "Миронов", "Крылов", "Куликов", "Карпов", "Власов", "Мельников",
    "Денисов", "Гаврилов", "Тихонов", "Казаков", "Афанасьев", "Данилов", "Савельев", "Тимофеев",
    "Фомин", "Чернов", "Абрамов", "Мартынов", "Ефимов", "Федотов", "Щербаков", "Назаров", "Калинин",
    "Исаев", "Быков", "Маслов", "Родионов", "Коновалов", "Лазарев", "Воронин", "Климов", "Филатов",
    "Голубев", "Кудрявцев", "Прохоров", "Наумов", "Потапов", "Трофимов", "Леонов", "Соболев",
    "Ермаков", "Колесников", "Гончаров", "Емельянов", "Никифоров", "Котов", "Гришин", "Ефремов",
    "Архипов", "Громов", "Кириллов", "Малышев", "Панов", "Моисеев", "Румянцев", "Акимов", "Бирюков",
    "Горбунов", "Анисимов", "Галкин", "Лукьянов", "Михеев", "Скворцов", "Юдин", "Белоусов", "Нестеров",
    "Симонов", "Харитонов", "Князев", "Цветков", "Левин", "Логинов", "Горшков", "Савин", "Краснов",
    "Демидов", "Елисеев", "Рыбаков", "Сафонов", "Плотников", "Фадеев", "Молчанов", "Литвинов",
    "Ершов", "Ушаков", "Рябов", "Мухин", "Калашников", "Лобанов", "Бородин", "Платонов", "Некрасов",
    "Покровский", "Никольский", "Петровский", "Вишневский", "Яблонский", "Ковальский", "Жуковский",
    "Луцкий", "Белецкий", "Шевченко", "Кравченко", "Бондаренко", "Ткаченко", "Черных", "Седых",
)

MALE_NAMES = (
    "Александр", "Алексей", "Андрей", "Антон", "Артем", "Борис", "Вадим", "Василий", "Виктор",
    "Владимир", "Владислав", "Георгий", "Григорий", "Денис", "Дмитрий", "Евгений", "Егор", "Иван",
    "Игорь", "Илья", "Кирилл", "Константин", "Максим", "Михаил", "Никита", "Николай", "Олег", "Павел",
    "Роман", "Сергей", "Станислав", "Степан", "Тимофей", "Юрий", "Ярослав", "Федор", "Леонид",
    "Матвей", "Глеб", "Аркадий",
)

FEMALE_NAMES = (
    "Анна", "Мария", "Елена", "Ольга", "Татьяна", "Наталья", "Ирина", "Светлана", "Екатерина", "Юлия",
    "Анастасия", "Марина", "Ксения", "Дарья", "Виктория", "Людмила", "Галина", "Надежда", "Вера",
    "Оксана", "Евгения", "Алина", "Полина", "Валентина", "Лариса", "Софья", "Кристина", "Алла",
    "Жанна", "Нина",
)

# Отчества, которые не образуются простым «+ович/+овна».
_PATRONYMIC_EXCEPTIONS = {
    "Алексей": ("Алексеевич", "Алексеевна"),
    "Андрей": ("Андреевич", "Андреевна"),
    "Василий": ("Васильевич", "Васильевна"),
    "Георгий": ("Георгиевич", "Георгиевна"),
    "Григорий": ("Григорьевич", "Григорьевна"),
    "Дмитрий": ("Дмитриевич", "Дмитриевна"),
    "Евгений": ("Евгеньевич", "Евгеньевна"),
    "Игорь": ("Игоревич", "Игоревна"),
    "Илья": ("Ильич", "Ильинична"),
    "Никита": ("Никитич", "Никитична"),
    "Николай": ("Николаевич", "Николаевна"),
    "Павел": ("Павлович", "Павловна"),
    "Сергей": ("Сергеевич", "Сергеевна"),
    "Юрий": ("Юрьевич", "Юрьевна"),
    "Аркадий": ("Аркадьевич", "Аркадьевна"),
    "Матвей": ("Матвеевич", "Матвеевна"),
    "Тимофей": ("Тимофеевич", "Тимофеевна"),
}

_HUSHING = set("гкхжчшщ")
_INDECLINABLE_ENDINGS = ("ко", "их", "ых")


def patronymic(father_name: str, gender: str) -> str:
    m, f = _PATRONYMIC_EXCEPTIONS.get(father_name, (father_name + "ович", father_name + "овна"))
    return m if gender == MALE else f


def surname_for_gender(base_male: str, gender: str) -> str:
    if gender == MALE or base_male.endswith(_INDECLINABLE_ENDINGS):
        return base_male
    if base_male.endswith("ий"):  # -ский, -цкий
        return base_male[:-2] + "ая"
    return base_male + "а"


def _decline_surname(s: str, gender: str, case: str) -> str:
    if case == "nom" or s.endswith(_INDECLINABLE_ENDINGS):
        return s
    if gender == MALE:
        if s.endswith("ий"):
            return s[:-2] + {"gen": "ого", "dat": "ому", "acc": "ого"}[case]
        return s + {"gen": "а", "dat": "у", "acc": "а"}[case]
    if s.endswith("ая"):
        return s[:-2] + {"gen": "ой", "dat": "ой", "acc": "ую"}[case]
    return s[:-1] + {"gen": "ой", "dat": "ой", "acc": "у"}[case]


def _decline_first_decl(word: str, case: str) -> str:
    """Слова на -а/-я (Анна, Мария, Наталья, Илья, Никита)."""
    if word.endswith("ия"):
        return word[:-1] + {"gen": "и", "dat": "и", "acc": "ю"}[case]
    if word.endswith("ья"):
        return word[:-1] + {"gen": "и", "dat": "е", "acc": "ю"}[case]
    if word.endswith("я"):
        return word[:-1] + {"gen": "и", "dat": "е", "acc": "ю"}[case]
    gen = "и" if word[-2] in _HUSHING else "ы"
    return word[:-1] + {"gen": gen, "dat": "е", "acc": "у"}[case]


def _decline_name(n: str, gender: str, case: str) -> str:
    if case == "nom":
        return n
    if n.endswith(("а", "я")):
        return _decline_first_decl(n, case)
    if gender == FEMALE:  # в списке женских имён все на -а/-я
        return n
    if n == "Павел":
        n = "Павл"
    if n.endswith(("й", "ь")):
        return n[:-1] + {"gen": "я", "dat": "ю", "acc": "я"}[case]
    return n + {"gen": "а", "dat": "у", "acc": "а"}[case]


def _decline_patronymic(p: str, gender: str, case: str) -> str:
    if case == "nom":
        return p
    if gender == MALE:
        return p + {"gen": "а", "dat": "у", "acc": "а"}[case]
    return p[:-1] + {"gen": "ы", "dat": "е", "acc": "у"}[case]


@dataclass(frozen=True)
class PersonName:
    surname: str  # уже в форме нужного рода
    name: str
    patronymic: str
    gender: str

    @property
    def full(self) -> str:
        return f"{self.surname} {self.name} {self.patronymic}"

    def case(self, case: str) -> str:
        if case not in CASES:
            raise ValueError(case)
        g = self.gender
        return " ".join((_decline_surname(self.surname, g, case), _decline_name(self.name, g, case),
                         _decline_patronymic(self.patronymic, g, case)))

    def initials_after(self) -> str:
        """«Иванов И. И.»"""
        return f"{self.surname} {self.name[0]}. {self.patronymic[0]}."

    def initials_before(self) -> str:
        """«И.И. Иванов»"""
        return f"{self.name[0]}.{self.patronymic[0]}. {self.surname}"


class NameFactory:
    """Выдаёт уникальные ФИО (полные тёзки не допускаются — проще сопоставлять с документами)."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.used: set[str] = set()

    def _take(self, make) -> PersonName:
        for _ in range(10_000):
            pn = make()
            if pn.full not in self.used:
                self.used.add(pn.full)
                return pn
        raise RuntimeError("не удалось подобрать уникальное ФИО")

    def new(self, gender: str | None = None, surname_base: str | None = None) -> PersonName:
        rng = self.rng

        def make() -> PersonName:
            g = gender or (MALE if rng.random() < 0.5 else FEMALE)
            base = surname_base or rng.choice(SURNAMES)
            first = rng.choice(MALE_NAMES if g == MALE else FEMALE_NAMES)
            father = rng.choice(MALE_NAMES)
            return PersonName(surname_for_gender(base, g), first, patronymic(father, g), g)

        return self._take(make)


def surname_base(pn: PersonName) -> str:
    """Мужская (базовая) форма фамилии — для генерации родственников с той же фамилией."""
    s = pn.surname
    if pn.gender == MALE or s.endswith(_INDECLINABLE_ENDINGS):
        return s
    if s.endswith("ая"):
        return s[:-2] + "ий"
    return s[:-1]
