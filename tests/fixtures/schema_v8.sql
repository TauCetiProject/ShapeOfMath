PRAGMA foreign_keys = ON;
PRAGMA user_version = 8;

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
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
    prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(prerequisites_complete IN (0, 1)),
    statement_prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(statement_prerequisites_complete IN (0,1)),
    proof_prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(proof_prerequisites_complete IN (0,1))
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
    dependency_review TEXT NOT NULL,
    requirements_complete INTEGER NOT NULL DEFAULT 0 CHECK(requirements_complete IN (0, 1)),
    introductions_complete INTEGER NOT NULL DEFAULT 0 CHECK(introductions_complete IN (0, 1)),
    citations_complete INTEGER NOT NULL DEFAULT 0 CHECK(citations_complete IN (0, 1))
);
CREATE TABLE IF NOT EXISTS source_identifier (
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES source(id),
    PRIMARY KEY (scheme, value)
);
-- A bibliography entry can exist before its referenced source is identified.
CREATE TABLE IF NOT EXISTS citation (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    label TEXT CHECK(label IS NULL OR length(trim(label)) > 0),
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    cited_source_id TEXT REFERENCES source(id),
    pedagogically_necessary INTEGER CHECK(pedagogically_necessary IN (0,1)),
    needed_material TEXT,
    UNIQUE(source_id, label)
);
CREATE INDEX IF NOT EXISTS citation_target ON citation(cited_source_id);
CREATE TABLE IF NOT EXISTS citation_identifier (
    citation_id INTEGER NOT NULL REFERENCES citation(id) ON DELETE CASCADE,
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(citation_id, scheme, value)
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
    purpose TEXT NOT NULL DEFAULT 'unclassified' CHECK(purpose IN ('statement','proof','both','unclassified')),
    CHECK(prerequisite_id <> dependent_id),
    UNIQUE(prerequisite_id, dependent_id)
);
CREATE INDEX IF NOT EXISTS concept_dependency_reverse ON concept_dependency(dependent_id);
CREATE TRIGGER IF NOT EXISTS dependency_purpose_insert BEFORE INSERT ON concept_dependency
WHEN NEW.purpose IN ('proof','both') BEGIN
    SELECT RAISE(ABORT,'proof prerequisites target theorem-shaped concepts')
    WHERE (SELECT kind FROM concept WHERE id=NEW.dependent_id) NOT IN ('theorem','conjecture');
END;
CREATE TRIGGER IF NOT EXISTS dependency_purpose_update BEFORE UPDATE ON concept_dependency
WHEN NEW.purpose IN ('proof','both') BEGIN
    SELECT RAISE(ABORT,'proof prerequisites target theorem-shaped concepts')
    WHERE (SELECT kind FROM concept WHERE id=NEW.dependent_id) NOT IN ('theorem','conjecture');
END;
CREATE TRIGGER IF NOT EXISTS dependency_kind_update BEFORE UPDATE OF kind ON concept
WHEN NEW.kind NOT IN ('theorem','conjecture') BEGIN
    SELECT RAISE(ABORT,'reclassify proof prerequisites before changing theorem kind')
    WHERE EXISTS(SELECT 1 FROM concept_dependency WHERE dependent_id=NEW.id AND purpose IN ('proof','both'));
END;
CREATE TABLE IF NOT EXISTS source_concept (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    concept_id TEXT NOT NULL REFERENCES concept(id),
    role TEXT NOT NULL CHECK(role IN ('relies_on', 'introduces', 'explains', 'discusses')),
    locator TEXT NOT NULL CHECK(length(trim(locator)) > 0),
    note TEXT NOT NULL,
    introduction_evidence TEXT NOT NULL DEFAULT '',
    CHECK(role <> 'introduces' OR length(trim(introduction_evidence)) > 0),
    UNIQUE(source_id, concept_id, role, locator)
);
-- Canonical ordering makes this an undirected relation, separate from the DAG.
CREATE TABLE IF NOT EXISTS concept_related (
    id INTEGER PRIMARY KEY,
    concept_a_id TEXT NOT NULL REFERENCES concept(id),
    concept_b_id TEXT NOT NULL REFERENCES concept(id),
    rationale TEXT NOT NULL CHECK(length(trim(rationale)) > 0),
    evidence_source_id TEXT REFERENCES source(id),
    locator TEXT,
    CHECK(concept_a_id < concept_b_id),
    UNIQUE(concept_a_id, concept_b_id)
);
CREATE INDEX IF NOT EXISTS concept_related_reverse ON concept_related(concept_b_id);
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

-- Completion is a local review judgment, never inferred from graph traversal.
CREATE TRIGGER IF NOT EXISTS prerequisites_changed_insert AFTER INSERT ON concept_dependency BEGIN
    UPDATE concept SET prerequisites_complete=0,
        statement_prerequisites_complete=CASE WHEN NEW.purpose='proof' THEN statement_prerequisites_complete ELSE 0 END,
        proof_prerequisites_complete=0 WHERE id=NEW.dependent_id;
END;
CREATE TRIGGER IF NOT EXISTS prerequisites_changed_delete AFTER DELETE ON concept_dependency BEGIN
    UPDATE concept SET prerequisites_complete=0,
        statement_prerequisites_complete=CASE WHEN OLD.purpose='proof' THEN statement_prerequisites_complete ELSE 0 END,
        proof_prerequisites_complete=0 WHERE id=OLD.dependent_id;
END;
CREATE TRIGGER IF NOT EXISTS prerequisites_changed_update AFTER UPDATE ON concept_dependency BEGIN
    UPDATE concept SET prerequisites_complete=0,
        statement_prerequisites_complete=CASE WHEN OLD.purpose='proof' AND NEW.purpose='proof' THEN statement_prerequisites_complete ELSE 0 END,
        proof_prerequisites_complete=0
        WHERE id IN (OLD.dependent_id,NEW.dependent_id);
END;
CREATE TRIGGER IF NOT EXISTS concept_changed_review AFTER UPDATE OF title,kind,description,status ON concept
WHEN OLD.title IS NOT NEW.title OR OLD.kind IS NOT NEW.kind OR OLD.description IS NOT NEW.description OR OLD.status IS NOT NEW.status BEGIN
    UPDATE concept SET prerequisites_complete=0,statement_prerequisites_complete=0,proof_prerequisites_complete=0 WHERE id=NEW.id OR id IN (
        SELECT dependent_id FROM concept_dependency WHERE prerequisite_id=NEW.id);
    UPDATE source SET requirements_complete=0 WHERE id IN (
        SELECT source_id FROM source_concept WHERE concept_id=NEW.id AND role='relies_on');
    UPDATE source SET introductions_complete=0 WHERE id IN (
        SELECT source_id FROM source_concept WHERE concept_id=NEW.id AND role='introduces');
END;
CREATE TRIGGER IF NOT EXISTS related_active_insert BEFORE INSERT ON concept_related BEGIN
    SELECT RAISE(ABORT, 'related endpoint is superseded') WHERE EXISTS (
        SELECT 1 FROM concept WHERE id IN (NEW.concept_a_id,NEW.concept_b_id) AND status <> 'active');
END;
CREATE TRIGGER IF NOT EXISTS related_active_update BEFORE UPDATE ON concept_related BEGIN
    SELECT RAISE(ABORT, 'related endpoint is superseded') WHERE EXISTS (
        SELECT 1 FROM concept WHERE id IN (NEW.concept_a_id,NEW.concept_b_id) AND status <> 'active');
END;
CREATE TRIGGER IF NOT EXISTS no_superseded_related BEFORE UPDATE OF status ON concept
WHEN NEW.status='superseded' BEGIN
    SELECT RAISE(ABORT, 'reroute related links before superseding a concept') WHERE EXISTS (
        SELECT 1 FROM concept_related WHERE concept_a_id=OLD.id OR concept_b_id=OLD.id);
END;
CREATE TRIGGER IF NOT EXISTS source_coverage_changed AFTER UPDATE OF coverage ON source
WHEN NEW.coverage IS NOT OLD.coverage BEGIN
    UPDATE source SET requirements_complete=0,introductions_complete=0,citations_complete=0 WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS source_concepts_insert AFTER INSERT ON source_concept BEGIN
    UPDATE source SET requirements_complete=0 WHERE id=NEW.source_id AND NEW.role='relies_on';
    UPDATE source SET introductions_complete=0 WHERE id=NEW.source_id AND NEW.role='introduces';
END;
CREATE TRIGGER IF NOT EXISTS source_concepts_delete AFTER DELETE ON source_concept BEGIN
    UPDATE source SET requirements_complete=0 WHERE id=OLD.source_id AND OLD.role='relies_on';
    UPDATE source SET introductions_complete=0 WHERE id=OLD.source_id AND OLD.role='introduces';
END;
CREATE TRIGGER IF NOT EXISTS source_concepts_update AFTER UPDATE ON source_concept WHEN OLD.source_id IS NOT NEW.source_id OR OLD.concept_id IS NOT NEW.concept_id OR OLD.role IS NOT NEW.role OR OLD.introduction_evidence IS NOT NEW.introduction_evidence BEGIN
    UPDATE source SET requirements_complete=0 WHERE id=OLD.source_id AND OLD.role='relies_on';
    UPDATE source SET introductions_complete=0 WHERE id=OLD.source_id AND OLD.role='introduces';
    UPDATE source SET requirements_complete=0 WHERE id=NEW.source_id AND NEW.role='relies_on';
    UPDATE source SET introductions_complete=0 WHERE id=NEW.source_id AND NEW.role='introduces';
END;
CREATE TRIGGER IF NOT EXISTS source_artifact_insert AFTER INSERT ON source_artifact BEGIN
    UPDATE source SET requirements_complete=0,introductions_complete=0,citations_complete=0 WHERE id=NEW.source_id;
END;
CREATE TRIGGER IF NOT EXISTS source_artifact_delete AFTER DELETE ON source_artifact BEGIN
    UPDATE source SET requirements_complete=0,introductions_complete=0,citations_complete=0 WHERE id=OLD.source_id;
END;
CREATE TRIGGER IF NOT EXISTS source_artifact_update AFTER UPDATE ON source_artifact BEGIN
    UPDATE source SET requirements_complete=0,introductions_complete=0,citations_complete=0 WHERE id=OLD.source_id;
    UPDATE source SET requirements_complete=0,introductions_complete=0,citations_complete=0 WHERE id=NEW.source_id;
END;

-- Capturing bibliography entries is independent of resolving or assessing them.
CREATE TRIGGER IF NOT EXISTS citation_insert AFTER INSERT ON citation BEGIN
    UPDATE source SET citations_complete=0 WHERE id=NEW.source_id;
END;
CREATE TRIGGER IF NOT EXISTS citation_delete AFTER DELETE ON citation BEGIN
    UPDATE source SET citations_complete=0 WHERE id=OLD.source_id;
END;
CREATE TRIGGER IF NOT EXISTS citation_update AFTER UPDATE OF source_id,label,text ON citation
WHEN OLD.source_id IS NOT NEW.source_id OR OLD.label IS NOT NEW.label OR OLD.text IS NOT NEW.text BEGIN
    UPDATE source SET citations_complete=0 WHERE id IN (OLD.source_id,NEW.source_id);
END;
