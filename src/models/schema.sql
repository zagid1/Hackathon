-- Схема данных прототипа (PLAN.md, раздел 5), SQLite.
-- Отличия от раздела 5 (согласовать с командой):
--   * колонка source ('synthetic' | 'real') есть у всех основных сущностей, а не только у
--     employees/persons/organizations/relations/documents — требование брифа «пометка источника у
--     каждой записи». Связующие таблицы наследуют источник от родителя;
--   * documents: добавлены object_type/object_id (к какой закупке/группе относится документ),
--     doc_number, doc_date;
--   * dataset_meta: seed и параметры генерации (без времени запуска — ради детерминизма).
-- Деньги — REAL в рублях (получены из целых копеек), даты — TEXT в ISO 8601.

PRAGMA page_size = 4096;

-- Оргструктура ------------------------------------------------------------------------------
CREATE TABLE units (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES units(id),
    level       INTEGER NOT NULL CHECK (level IN (0, 1, 2)),     -- ведомство / департамент / отдел
    source      TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE positions (
    id            INTEGER PRIMARY KEY,
    unit_id       INTEGER NOT NULL REFERENCES units(id),
    title         TEXT    NOT NULL,
    function_code TEXT    NOT NULL CHECK (function_code IN ('PROC', 'LIC', 'CONTROL', 'HR', 'OTHER'))
);

CREATE TABLE position_authorities (
    position_id INTEGER NOT NULL REFERENCES positions(id),
    action      TEXT    NOT NULL CHECK (action IN ('SIGN_CONTRACT', 'SIGN_AMENDMENT', 'APPROVE_PROC',
                                                   'RESPONSIBLE_PROC')),
    PRIMARY KEY (position_id, action)
);

CREATE TABLE employees (
    id          INTEGER PRIMARY KEY,
    full_name   TEXT    NOT NULL,
    position_id INTEGER NOT NULL REFERENCES positions(id),
    hired_at    TEXT    NOT NULL,
    source      TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

-- Люди и организации вне госслужбы ----------------------------------------------------------
CREATE TABLE persons (
    id        INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    source    TEXT NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE organizations (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    inn           TEXT NOT NULL UNIQUE,
    ogrn          TEXT NOT NULL UNIQUE,
    okved         TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE org_roles (
    org_id    INTEGER NOT NULL REFERENCES organizations(id),
    person_id INTEGER NOT NULL REFERENCES persons(id),
    role      TEXT    NOT NULL CHECK (role IN ('DIRECTOR', 'FOUNDER')),
    PRIMARY KEY (org_id, person_id, role)
);

-- Документы (до groups/relations: на них ссылаются внешние ключи) -----------------------------
CREATE TABLE documents (
    id          INTEGER PRIMARY KEY,
    doc_type    TEXT NOT NULL CHECK (doc_type IN ('PROTOCOL', 'ORDER', 'CONTRACT')),
    path        TEXT NOT NULL,                  -- относительно data_dir
    source      TEXT NOT NULL CHECK (source IN ('synthetic', 'real')),
    object_type TEXT CHECK (object_type IN ('procurement', 'group', 'contract')),
    object_id   INTEGER,
    doc_number  TEXT,
    doc_date    TEXT
);

CREATE TABLE doc_fragments (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page        INTEGER NOT NULL,
    char_start  INTEGER NOT NULL,               -- смещения в тексте страницы, [start, end)
    char_end    INTEGER NOT NULL,
    text        TEXT    NOT NULL
);

-- Блок 1: связи и группы ----------------------------------------------------------------------
CREATE TABLE groups (
    id                INTEGER PRIMARY KEY,
    kind              TEXT NOT NULL CHECK (kind IN ('PROJECT', 'COMMISSION', 'WORKGROUP')),
    name              TEXT NOT NULL,
    created_by_doc_id INTEGER REFERENCES documents(id),
    source            TEXT NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE group_members (
    group_id    INTEGER NOT NULL REFERENCES groups(id),
    member_type TEXT    NOT NULL CHECK (member_type IN ('employee', 'person')),
    member_id   INTEGER NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('CHAIR', 'DEPUTY_CHAIR', 'MEMBER', 'SECRETARY', 'LEADER')),
    PRIMARY KEY (group_id, member_type, member_id)
);

CREATE TABLE relations (
    id              INTEGER PRIMARY KEY,
    a_type          TEXT    NOT NULL CHECK (a_type IN ('employee', 'person', 'organization')),
    a_id            INTEGER NOT NULL,
    b_type          TEXT    NOT NULL CHECK (b_type IN ('employee', 'person', 'organization')),
    b_id            INTEGER NOT NULL,
    rel_type        TEXT    NOT NULL CHECK (rel_type IN ('RELATIVE', 'EX_EMPLOYER', 'SAME_PROJECT',
                                                         'SAME_COMMISSION')),
    source          TEXT    NOT NULL CHECK (source IN ('synthetic', 'real')),
    evidence_doc_id INTEGER REFERENCES documents(id)
);

-- Блок 2: деятельность ------------------------------------------------------------------------
CREATE TABLE procurements (
    id                      INTEGER PRIMARY KEY,
    unit_id                 INTEGER NOT NULL REFERENCES units(id),       -- подразделение-заказчик
    okpd2                   TEXT    NOT NULL,
    method                  TEXT    NOT NULL CHECK (method IN ('AUCTION', 'TENDER', 'QUOTATION',
                                                               'SINGLE_SUPPLIER')),
    nmck                    REAL    NOT NULL,
    published_at            TEXT    NOT NULL,
    deadline_at             TEXT,                                        -- NULL у SINGLE_SUPPLIER
    commission_group_id     INTEGER REFERENCES groups(id),               -- NULL у SINGLE_SUPPLIER
    responsible_employee_id INTEGER NOT NULL REFERENCES employees(id),
    source                  TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE bids (
    id             INTEGER PRIMARY KEY,
    procurement_id INTEGER NOT NULL REFERENCES procurements(id),
    org_id         INTEGER NOT NULL REFERENCES organizations(id),
    price          REAL    NOT NULL,
    source         TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE contracts (
    id                 INTEGER PRIMARY KEY,
    procurement_id     INTEGER NOT NULL UNIQUE REFERENCES procurements(id),
    supplier_org_id    INTEGER NOT NULL REFERENCES organizations(id),
    price              REAL    NOT NULL,
    signed_at          TEXT    NOT NULL,
    signer_employee_id INTEGER NOT NULL REFERENCES employees(id),
    source             TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

CREATE TABLE amendments (
    id          INTEGER PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id),
    signed_at   TEXT    NOT NULL,
    price_delta REAL    NOT NULL,
    reason      TEXT    NOT NULL,
    source      TEXT    NOT NULL CHECK (source IN ('synthetic', 'real'))
);

-- Результат (заполняется на Этапе 2) ----------------------------------------------------------
CREATE TABLE signals (
    id                    INTEGER PRIMARY KEY,
    indicator             TEXT    NOT NULL,          -- I1, I2, I3, I4, I7
    object_type           TEXT    NOT NULL,          -- employee, procurement, contract
    object_id             INTEGER NOT NULL,
    employee_id           INTEGER REFERENCES employees(id),
    value                 REAL,
    threshold             REAL,
    peer_group            TEXT,
    explanation           TEXT    NOT NULL,
    evidence_fragment_ids TEXT    NOT NULL DEFAULT '[]',    -- JSON-список id из doc_fragments
    status                TEXT    NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'IN_WORK', 'REJECTED')),
    reviewer_comment      TEXT
);

-- Ground truth (только для оценки, в UI не показывать) ------------------------------------------
-- Гранулярность строки = уровень индикатора, который должен найти схему:
--   S1, S4, S5 -> object_type='contract'; S2 -> 'employee'; S3 -> 'employee' и 'procurement'.
CREATE TABLE injected_schemes (
    id          INTEGER PRIMARY KEY,
    scheme      TEXT    NOT NULL CHECK (scheme IN ('S1', 'S2', 'S3', 'S4', 'S5')),
    object_type TEXT    NOT NULL CHECK (object_type IN ('employee', 'procurement', 'contract')),
    object_id   INTEGER NOT NULL,
    employee_id INTEGER NOT NULL REFERENCES employees(id)
);

CREATE TABLE dataset_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_positions_unit ON positions(unit_id);
CREATE INDEX idx_employees_position ON employees(position_id);
CREATE INDEX idx_org_roles_person ON org_roles(person_id);
CREATE INDEX idx_fragments_document ON doc_fragments(document_id);
CREATE INDEX idx_group_members_member ON group_members(member_type, member_id);
CREATE INDEX idx_relations_a ON relations(a_type, a_id);
CREATE INDEX idx_relations_b ON relations(b_type, b_id);
CREATE INDEX idx_procurements_responsible ON procurements(responsible_employee_id);
CREATE INDEX idx_procurements_commission ON procurements(commission_group_id);
CREATE INDEX idx_bids_procurement ON bids(procurement_id);
CREATE INDEX idx_contracts_supplier ON contracts(supplier_org_id);
CREATE INDEX idx_contracts_signer ON contracts(signer_employee_id);
CREATE INDEX idx_amendments_contract ON amendments(contract_id);
CREATE INDEX idx_signals_object ON signals(object_type, object_id);
CREATE INDEX idx_injected_object ON injected_schemes(object_type, object_id);
