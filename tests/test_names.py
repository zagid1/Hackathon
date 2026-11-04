import random

import pytest

from src.generator.names import FEMALE, MALE, NameFactory, PersonName, patronymic, surname_base, surname_for_gender


@pytest.mark.parametrize("pn, case, expected", [
    (PersonName("Иванов", "Иван", "Иванович", MALE), "gen", "Иванова Ивана Ивановича"),
    (PersonName("Иванов", "Иван", "Иванович", MALE), "dat", "Иванову Ивану Ивановичу"),
    (PersonName("Иванова", "Анна", "Сергеевна", FEMALE), "gen", "Ивановой Анны Сергеевны"),
    (PersonName("Иванова", "Анна", "Сергеевна", FEMALE), "acc", "Иванову Анну Сергеевну"),
    (PersonName("Покровская", "Мария", "Ильинична", FEMALE), "gen", "Покровской Марии Ильиничны"),
    (PersonName("Покровская", "Мария", "Ильинична", FEMALE), "acc", "Покровскую Марию Ильиничну"),
    (PersonName("Покровский", "Игорь", "Юрьевич", MALE), "gen", "Покровского Игоря Юрьевича"),
    (PersonName("Шевченко", "Илья", "Павлович", MALE), "gen", "Шевченко Ильи Павловича"),
    (PersonName("Черных", "Ольга", "Никитична", FEMALE), "gen", "Черных Ольги Никитичны"),
    (PersonName("Смирнов", "Павел", "Ильич", MALE), "acc", "Смирнова Павла Ильича"),
    (PersonName("Петрова", "Наталья", "Олеговна", FEMALE), "dat", "Петровой Наталье Олеговне"),
    (PersonName("Котов", "Никита", "Сергеевич", MALE), "acc", "Котова Никиту Сергеевича"),
])
def test_declension(pn, case, expected):
    assert pn.case(case) == expected
    assert pn.case("nom") == pn.full


def test_patronymics_and_surnames():
    assert patronymic("Илья", MALE) == "Ильич" and patronymic("Илья", FEMALE) == "Ильинична"
    assert patronymic("Павел", MALE) == "Павлович" and patronymic("Павел", FEMALE) == "Павловна"
    assert patronymic("Юрий", MALE) == "Юрьевич" and patronymic("Иван", FEMALE) == "Ивановна"
    assert surname_for_gender("Покровский", FEMALE) == "Покровская"
    assert surname_for_gender("Шевченко", FEMALE) == "Шевченко"
    for base in ("Иванов", "Покровский", "Черных"):
        assert surname_base(PersonName(surname_for_gender(base, FEMALE), "Анна", "Ивановна", FEMALE)) == base


def test_initials():
    pn = PersonName("Иванов", "Иван", "Петрович", MALE)
    assert pn.initials_after() == "Иванов И. П."
    assert pn.initials_before() == "И.П. Иванов"


def test_factory_unique_and_deterministic():
    a = [NameFactory(random.Random("s")).new().full for _ in range(1)]
    f1, f2 = NameFactory(random.Random("s")), NameFactory(random.Random("s"))
    n1 = [f1.new().full for _ in range(500)]
    n2 = [f2.new().full for _ in range(500)]
    assert n1 == n2 and len(set(n1)) == 500 and a[0] == n1[0]
