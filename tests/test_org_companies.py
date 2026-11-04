import random

from src.generator.companies import (inn10_check_digit, is_valid_inn10, is_valid_ogrn, make_inn, make_ogrn,
                                     normalize_org_name)


def test_known_requisites():
    # реквизиты ПАО Сбербанк из открытых источников
    assert is_valid_inn10("7707083893")
    assert is_valid_ogrn("1027700132195")
    assert not is_valid_inn10("7707083894")
    assert not is_valid_ogrn("1027700132196")


def test_generated_requisites_valid():
    import datetime as dt
    rng = random.Random(1)
    for _ in range(200):
        inn = make_inn(rng)
        assert is_valid_inn10(inn) and inn10_check_digit(inn[:9]) == int(inn[9])
        assert is_valid_ogrn(make_ogrn(rng, inn, dt.date(2015, 5, 5)))


def test_normalize_org_name():
    assert normalize_org_name("ООО", "Ромашка") == "ООО РОМАШКА"


def test_org_structure(db):
    levels = dict(db.execute("SELECT level, count(*) FROM units GROUP BY level").fetchall())
    assert levels == {0: 1, 1: 5, 2: 20}
    assert db.execute("SELECT count(*) FROM employees").fetchone()[0] == 150
    proc = db.execute("SELECT count(*) FROM employees e JOIN positions p ON p.id = e.position_id "
                      "WHERE p.function_code = 'PROC'").fetchone()[0]
    assert proc == 30
    # у каждого отдела есть начальник
    no_head = db.execute("SELECT count(*) FROM units u WHERE level = 2 AND NOT EXISTS (SELECT 1 FROM positions p "
                         "JOIN employees e ON e.position_id = p.id WHERE p.unit_id = u.id "
                         "AND p.title LIKE 'Начальник отдела%')").fetchone()[0]
    assert no_head == 0
    # право подписи — только у руководства, директоров и замдиректора департамента закупок
    signers = [r[0] for r in db.execute("SELECT p.title FROM positions p JOIN position_authorities a "
                                        "ON a.position_id = p.id WHERE a.action = 'SIGN_CONTRACT'")]
    assert all(t.startswith(("Руководитель", "Заместитель руководителя", "Директор Департамента",
                             "Заместитель директора Департамента закупок")) for t in signers)


def test_organizations(db):
    rows = db.execute("SELECT inn, ogrn FROM organizations").fetchall()
    assert len(rows) == 300
    assert all(is_valid_inn10(i) and is_valid_ogrn(o) for i, o in rows)
    directors = dict(db.execute("SELECT org_id, count(*) FROM org_roles WHERE role = 'DIRECTOR' GROUP BY 1"))
    assert len(directors) == 300 and set(directors.values()) == {1}


def test_relatives_share(db):
    n = db.execute("SELECT count(DISTINCT a_id) FROM relations WHERE rel_type = 'RELATIVE' "
                   "AND a_type = 'employee'").fetchone()[0]
    assert 12 <= n <= 18   # ~10% от 150
