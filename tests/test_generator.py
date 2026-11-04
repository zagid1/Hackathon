"""Инварианты синтетики и проверка внедрённых схем S1–S5 по самой БД."""

import datetime as dt
from collections import defaultdict

from src.law import legal_min_days

SOURCE_TABLES = ("units", "employees", "persons", "organizations", "relations", "groups", "procurements",
                 "bids", "contracts", "amendments", "documents")


def q(db, sql, *args):
    return db.execute(sql, args).fetchall()


def labels(db, scheme, object_type):
    return {r["object_id"]: r["employee_id"] for r in
            q(db, "SELECT object_id, employee_id FROM injected_schemes WHERE scheme = ? AND object_type = ?",
              scheme, object_type)}


def test_everything_marked_synthetic(db):
    for t in SOURCE_TABLES:
        assert [tuple(r) for r in q(db, f"SELECT DISTINCT source FROM {t}")] == [("synthetic",)], t
    assert dict(q(db, "SELECT key, value FROM dataset_meta"))["seed"] == "42"


def test_procurement_invariants(db):
    procs = q(db, "SELECT * FROM procurements")
    assert len(procs) == 2000
    for p in procs:
        pub = dt.date.fromisoformat(p["published_at"])
        assert dt.date(2024, 1, 1) <= pub <= dt.date(2025, 12, 31)
        if p["method"] == "SINGLE_SUPPLIER":
            assert p["deadline_at"] is None and p["commission_group_id"] is None and p["nmck"] <= 600_000
        else:
            days = (dt.date.fromisoformat(p["deadline_at"]) - pub).days
            assert days >= legal_min_days(p["method"], int(p["nmck"] * 100))
            assert p["commission_group_id"] is not None
    assert q(db, "SELECT count(*) FROM bids b JOIN procurements p ON p.id = b.procurement_id "
                 "WHERE p.method = 'SINGLE_SUPPLIER'")[0][0] == 0
    assert q(db, "SELECT count(*) FROM bids b JOIN procurements p ON p.id = b.procurement_id "
                 "WHERE b.price > p.nmck")[0][0] == 0


def test_contract_goes_to_lowest_bid(db):
    rows = q(db, """SELECT c.supplier_org_id, c.price,
                           (SELECT min(price) FROM bids WHERE procurement_id = p.id) AS best,
                           (SELECT org_id FROM bids WHERE procurement_id = p.id ORDER BY price, id LIMIT 1) AS org
                    FROM contracts c JOIN procurements p ON p.id = c.procurement_id
                    WHERE p.method != 'SINGLE_SUPPLIER'""")
    assert rows and all(r["price"] == r["best"] and r["supplier_org_id"] == r["org"] for r in rows)


def test_background_noise_present(db):
    """Фон не тривиален: есть единственные заявки, малые снижения цены и законные допсоглашения."""
    single = q(db, """SELECT avg(n = 1) FROM (SELECT p.id, count(b.id) n FROM procurements p
                      JOIN bids b ON b.procurement_id = p.id GROUP BY p.id)""")[0][0]
    assert 0.15 < single < 0.4
    amended = q(db, "SELECT count(DISTINCT contract_id) * 1.0 / (SELECT count(*) FROM contracts) FROM amendments")[0][0]
    assert 0.12 < amended < 0.2
    gt_contracts = set(labels(db, "S4", "contract"))
    low_drop = [r[0] for r in q(db, """SELECT c.id FROM contracts c JOIN procurements p ON p.id = c.procurement_id
                                      WHERE (SELECT count(*) FROM bids WHERE procurement_id = p.id) >= 2
                                      AND 1 - c.price / p.nmck < 0.005""")]
    assert len(set(low_drop) - gt_contracts) >= 10


def _relatives_orgs(db):
    rel = defaultdict(set)
    for e, p in q(db, "SELECT a_id, b_id FROM relations WHERE rel_type = 'RELATIVE'"):
        rel[e].add(p)
    org_people = defaultdict(set)
    for o, p in q(db, "SELECT org_id, person_id FROM org_roles"):
        org_people[o].add(p)
    return rel, org_people


def _participants(db, procurement_id):
    p = q(db, "SELECT responsible_employee_id, commission_group_id FROM procurements WHERE id = ?", procurement_id)[0]
    out = {p[0]}
    if p[1]:
        out |= {r[0] for r in q(db, "SELECT member_id FROM group_members WHERE group_id = ? "
                                    "AND member_type = 'employee'", p[1])}
    return out


def test_s1_affiliated_supplier(db):
    s1 = labels(db, "S1", "contract")
    assert len(s1) >= 20 and len(set(s1.values())) == 4
    rel, org_people = _relatives_orgs(db)
    for cid, emp in s1.items():
        c = q(db, "SELECT procurement_id, supplier_org_id FROM contracts WHERE id = ?", cid)[0]
        assert rel[emp] & org_people[c[1]], "директор/учредитель поставщика — родственник служащего"
        assert emp in _participants(db, c[0])


def test_background_has_no_direct_relative_conflicts(db):
    """Вне S1 поставщик не аффилирован (по родству) с ответственным, членами комиссии и подписантом."""
    s1 = set(labels(db, "S1", "contract"))
    rel, org_people = _relatives_orgs(db)
    for cid, pid, org, signer in q(db, "SELECT id, procurement_id, supplier_org_id, signer_employee_id FROM contracts"):
        if cid in s1:
            continue
        for e in _participants(db, pid) | {signer}:
            assert not (rel.get(e, set()) & org_people[org]), (cid, e)


def test_s2_concentration(db):
    s2 = labels(db, "S2", "employee")
    assert len(s2) == 3
    for emp in s2:
        rows = q(db, """SELECT sum(c.price) FROM contracts c JOIN procurements p ON p.id = c.procurement_id
                        WHERE p.responsible_employee_id = ? GROUP BY c.supplier_org_id ORDER BY 1 DESC""", emp)
        total = sum(r[0] for r in rows)
        assert rows[0][0] / total > 0.6
        n = q(db, "SELECT count(*) FROM contracts c JOIN procurements p ON p.id = c.procurement_id "
                  "WHERE p.responsible_employee_id = ?", emp)[0][0]
        assert n >= 5


def test_s3_restricted_competition(db):
    emps = labels(db, "S3", "employee")
    procs = labels(db, "S3", "procurement")
    assert len(emps) == 2 and len(procs) >= 10
    for pid, emp in procs.items():
        p = q(db, "SELECT * FROM procurements WHERE id = ?", pid)[0]
        assert p["responsible_employee_id"] == emp
        days = (dt.date.fromisoformat(p["deadline_at"]) - dt.date.fromisoformat(p["published_at"])).days
        assert days == legal_min_days(p["method"], int(p["nmck"] * 100))
        assert q(db, "SELECT count(*) FROM bids WHERE procurement_id = ?", pid)[0][0] == 1
    shares = dict(q(db, """SELECT p.responsible_employee_id, avg(n = 1) FROM procurements p
                          JOIN (SELECT procurement_id, count(*) n FROM bids GROUP BY 1) b ON b.procurement_id = p.id
                          GROUP BY 1"""))
    median = sorted(shares.values())[len(shares) // 2]
    assert all(shares[e] > 2 * median for e in emps)


def test_s4_price_inflation(db):
    s4 = labels(db, "S4", "contract")
    assert len(s4) >= 10
    for cid in s4:
        c = q(db, "SELECT c.price, p.nmck, p.id FROM contracts c JOIN procurements p ON p.id = c.procurement_id "
                  "WHERE c.id = ?", cid)[0]
        assert q(db, "SELECT count(*) FROM bids WHERE procurement_id = ?", c[2])[0][0] >= 2
        growth = q(db, "SELECT sum(price_delta) FROM amendments WHERE contract_id = ?", cid)[0][0] / c[0]
        assert growth >= 0.10
    # фоновые допсоглашения не дают роста >= 10%
    others = q(db, """SELECT c.id, sum(a.price_delta) / c.price FROM contracts c JOIN amendments a
                      ON a.contract_id = c.id GROUP BY c.id""")
    assert all(g < 0.0999 for cid, g in others if cid not in s4)


def test_s5_authority(db):
    s5 = labels(db, "S5", "contract")
    assert len(s5) >= 6 and len(set(s5.values())) == 2
    unauthorized = {r[0] for r in q(db, """SELECT c.id FROM contracts c JOIN employees e ON e.id = c.signer_employee_id
                    WHERE NOT EXISTS (SELECT 1 FROM position_authorities a WHERE a.position_id = e.position_id
                                      AND a.action = 'SIGN_CONTRACT')""")}
    assert unauthorized == set(s5)


def test_ground_truth_references_exist(db):
    for ot, table in (("contract", "contracts"), ("procurement", "procurements"), ("employee", "employees")):
        missing = q(db, f"SELECT count(*) FROM injected_schemes s WHERE object_type = ? "
                        f"AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = s.object_id)", ot)[0][0]
        assert missing == 0
