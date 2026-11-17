PRAGMA foreign_keys = ON;
PRAGMA user_version = 3;

CREATE TABLE IF NOT EXISTS concept (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 200),
    kind TEXT NOT NULL CHECK(kind IN ('definition', 'theorem', 'construction', 'conjecture')),
    description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 1500
        AND instr(description, char(10)) = 0 AND instr(description, char(13)) = 0),
    field TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'superseded')),
    boundary INTEGER NOT NULL DEFAULT 0 CHECK(boundary IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0)
);
CREATE TABLE IF NOT EXISTS concept_alias (
    concept_id TEXT NOT NULL REFERENCES concept(id),
    alias TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (concept_id, alias)
);
CREATE TABLE IF NOT EXISTS source (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    year INTEGER,
    field TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('catalogued', 'draft', 'reviewed')),
    coverage TEXT NOT NULL,
    summary TEXT NOT NULL,
    dependency_review TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_identifier (
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source(id),
    PRIMARY KEY (scheme, value)
);
CREATE TABLE IF NOT EXISTS source_artifact (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    url TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '',
    accessed_at TEXT NOT NULL,
    sha256 TEXT,
    local_path TEXT,
    note TEXT NOT NULL,
    UNIQUE(source_id, url, version)
);
-- Direction is ALWAYS prerequisite -> dependent.
CREATE TABLE IF NOT EXISTS concept_dependency (
    id INTEGER PRIMARY KEY,
    prerequisite_id TEXT NOT NULL REFERENCES concept(id),
    dependent_id TEXT NOT NULL REFERENCES concept(id),
    basis TEXT NOT NULL CHECK(basis IN ('logical', 'pedagogical', 'both')),
    rationale TEXT NOT NULL CHECK(length(trim(rationale)) > 0),
    evidence_source_id TEXT REFERENCES source(id),
    locator TEXT,
    CHECK(prerequisite_id <> dependent_id),
    UNIQUE(prerequisite_id, dependent_id)
);
CREATE INDEX IF NOT EXISTS concept_dependency_reverse ON concept_dependency(dependent_id);
CREATE TABLE IF NOT EXISTS source_concept (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    concept_id TEXT NOT NULL REFERENCES concept(id),
    role TEXT NOT NULL CHECK(role IN ('uses', 'defines', 'proves', 'discusses')),
    locator TEXT NOT NULL CHECK(length(trim(locator)) > 0),
    note TEXT NOT NULL,
    UNIQUE(source_id, concept_id, role, locator)
);
-- A citation is not a strict dependency. Store reviewed examples of both.
CREATE TABLE IF NOT EXISTS source_relation (
    id INTEGER PRIMARY KEY,
    dependent_id TEXT NOT NULL REFERENCES source(id),
    prerequisite_id TEXT NOT NULL REFERENCES source(id),
    kind TEXT NOT NULL CHECK(kind IN ('citation', 'historical', 'strict_dependency')),
    fact TEXT NOT NULL,
    locator TEXT NOT NULL,
    rationale TEXT NOT NULL,
    general_availability TEXT NOT NULL,
    UNIQUE(dependent_id, prerequisite_id, kind, fact),
    CHECK(dependent_id <> prerequisite_id),
    CHECK(kind <> 'strict_dependency' OR
          (length(trim(fact)) > 0 AND length(trim(locator)) > 0 AND
           length(trim(rationale)) > 0 AND length(trim(general_availability)) > 0))
);
CREATE TABLE IF NOT EXISTS embedding_model (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    configuration TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS concept_embedding (
    concept_id TEXT NOT NULL REFERENCES concept(id),
    model_id TEXT NOT NULL REFERENCES embedding_model(id),
    content_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL,
    PRIMARY KEY(concept_id, model_id)
);
CREATE TABLE IF NOT EXISTS curation_event (
    id INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    operation TEXT NOT NULL,
    reason TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS concept_dag_insert BEFORE INSERT ON concept_dependency BEGIN
    SELECT RAISE(ABORT, 'dependency endpoint is superseded') WHERE EXISTS (
        SELECT 1 FROM concept WHERE id IN (NEW.prerequisite_id, NEW.dependent_id)
        AND status <> 'active');
    SELECT RAISE(ABORT, 'concept dependency would create a cycle') WHERE EXISTS (
        WITH RECURSIVE reachable(id) AS (
            SELECT NEW.dependent_id UNION
            SELECT d.dependent_id FROM concept_dependency d JOIN reachable r ON d.prerequisite_id = r.id
        ) SELECT 1 FROM reachable WHERE id = NEW.prerequisite_id
    );
END;
CREATE TRIGGER IF NOT EXISTS concept_dag_update BEFORE UPDATE ON concept_dependency BEGIN
    SELECT RAISE(ABORT, 'dependency endpoint is superseded') WHERE EXISTS (
        SELECT 1 FROM concept WHERE id IN (NEW.prerequisite_id, NEW.dependent_id)
        AND status <> 'active');
    SELECT RAISE(ABORT, 'concept dependency would create a cycle') WHERE EXISTS (
        WITH RECURSIVE reachable(id) AS (
            SELECT NEW.dependent_id UNION
            SELECT d.dependent_id FROM concept_dependency d JOIN reachable r ON d.prerequisite_id = r.id
            WHERE d.id <> OLD.id
        ) SELECT 1 FROM reachable WHERE id = NEW.prerequisite_id
    );
END;
CREATE TRIGGER IF NOT EXISTS no_superseded_endpoint BEFORE UPDATE OF status ON concept
WHEN NEW.status = 'superseded' BEGIN
    SELECT RAISE(ABORT, 'reroute dependencies before superseding an concept') WHERE EXISTS (
        SELECT 1 FROM concept_dependency WHERE prerequisite_id = OLD.id OR dependent_id = OLD.id);
END;
CREATE TRIGGER IF NOT EXISTS invalidate_embedding AFTER UPDATE OF title, kind, description ON concept BEGIN
    DELETE FROM concept_embedding WHERE concept_id = NEW.id;
    UPDATE concept SET revision = OLD.revision + 1 WHERE id = NEW.id;
END;

CREATE VIEW IF NOT EXISTS active_source_concept AS
SELECT si.* FROM source_concept si JOIN concept i ON i.id = si.concept_id WHERE i.status = 'active';
CREATE VIEW IF NOT EXISTS strict_source_dependency AS
SELECT * FROM source_relation WHERE kind = 'strict_dependency';
