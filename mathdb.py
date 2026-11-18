"""Revisable mathematical concepts. Core commands use only the Python standard library."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from collections import deque
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import sys
import sysconfig
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

ROOT = Path(__file__).resolve().parent
# A filesystem path selects SQLite; a postgresql:// URL selects PostgreSQL.
DEFAULT_DB = os.environ.get("MATHDB_DATABASE") or ROOT / "data" / "math.sqlite"
NAMESPACE = uuid.UUID("b139d4a4-ce25-4141-b43b-3714b8ac2fcf")
MODEL = "BAAI/bge-small-en-v1.5"


def stable_id(kind, slug):
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{slug}"))


def normalize_identifier(scheme, value):
    scheme, value = scheme.lower().strip(), value.strip()
    if scheme == "doi":
        value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I).lower()
        if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
            raise ValueError("Invalid DOI")
    elif scheme == "arxiv":
        value = re.sub(r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)", "", value, flags=re.I)
        value = re.sub(r"\.pdf$", "", value)
        value = re.sub(r"v\d+$", "", value)
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})", value):
            raise ValueError("Invalid arXiv identifier")
    elif scheme == "isbn":
        value = re.sub(r"[\s-]", "", value).upper()
        valid10 = bool(re.fullmatch(r"\d{9}[\dX]", value)) and sum(
            (10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(value)
        ) % 11 == 0
        valid13 = bool(re.fullmatch(r"\d{13}", value)) and sum(
            int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)
        ) % 10 == 0
        if not (valid10 or valid13):
            raise ValueError("Invalid ISBN checksum")
        if valid10:
            base = "978" + value[:9]
            value = base + str((-sum(int(c) * (1 if i % 2 == 0 else 3)
                                    for i, c in enumerate(base))) % 10)
    elif scheme == "url":
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username:
            raise ValueError("Expected an HTTP(S) URL without credentials")
        value = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, parts.fragment))
    elif scheme == "zbl":
        value = re.sub(r"^Zbl\s*", "", value, flags=re.I)
        if not value:
            raise ValueError("Empty zbMATH identifier")
    else:
        raise ValueError(f"Unsupported identifier scheme: {scheme}")
    return scheme, value


def is_postgres(db):
    return getattr(db, "backend", None) == "postgres"


def is_postgres_url(path):
    return str(path).startswith(("postgres://", "postgresql://"))


def connect(path=DEFAULT_DB):
    if is_postgres_url(path):
        import pgcompat
        return pgcompat.connect(str(path))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def canonical_role(role):
    return {"uses": "relies_on", "presents": "explains", "defines": "explains",
            "proves": "explains"}.get(role, role)


def execute_schema(db, script):
    """Execute SQL including trigger bodies without executescript's implicit commit."""
    if is_postgres(db):
        db.executescript(script)
        return
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ""
    if statement.strip():
        db.execute(statement)


def initialize_postgres(db):
    """Create or update the PostgreSQL schema. It starts at SQLite schema version 10."""
    schema = ROOT / "schema_pg.sql"
    if not schema.exists():
        schema = Path(sysconfig.get_path("data")) / "share/the-shape-of-math/schema_pg.sql"
    with db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT to_regclass('schema_version') IS NOT NULL").fetchone()[0]
        if exists:
            version = db.execute("SELECT version FROM schema_version").fetchone()[0]
            if version != 10:
                raise ValueError(f"Unsupported database schema version: {version}")
        execute_schema(db, schema.read_text())


def initialize(db):
    if is_postgres(db):
        return initialize_postgres(db)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='idea'").fetchone():
        raise ValueError("This is a v1 ideas database. Use a fresh path for the concept model; v1 has been archived.")
    columns = {row[1] for row in db.execute("PRAGMA table_info(concept)")}
    if "scope" in columns:
        raise ValueError("This is a v2 database. Use a fresh path for the simplified concept model; v2 has been archived.")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if columns and version not in (3, 4, 5, 6, 7, 8, 9, 10):
        raise ValueError(f"Unsupported database schema version: {version}")
    schema = ROOT / "schema.sql"
    if not schema.exists():
        schema = Path(sysconfig.get_path("data")) / "share/the-shape-of-math/schema.sql"
    schema_text = schema.read_text()
    with db:
        db.execute("BEGIN IMMEDIATE")
        if columns and version < 7:
            before = [dict(r) for r in db.execute("SELECT * FROM source_concept ORDER BY id")]
            # These triggers reference the occurrence table or the renamed flag.
            for trigger in ("concept_changed_review", "source_coverage_changed", "source_concepts_insert",
                            "source_concepts_update", "source_concepts_delete", "source_artifact_insert",
                            "source_artifact_update", "source_artifact_delete"):
                db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            if version == 3:
                db.execute("ALTER TABLE concept ADD COLUMN prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(prerequisites_complete IN (0,1))")
                db.execute("ALTER TABLE source ADD COLUMN requirements_complete INTEGER NOT NULL DEFAULT 0 CHECK(requirements_complete IN (0,1))")
                db.execute("ALTER TABLE source ADD COLUMN introductions_complete INTEGER NOT NULL DEFAULT 0 CHECK(introductions_complete IN (0,1))")
            elif version == 5:
                db.execute("ALTER TABLE source RENAME COLUMN presentations_complete TO introductions_complete")
            previous_reviews = [dict(r) for r in db.execute("SELECT id,introductions_complete FROM source")]
            db.execute("UPDATE source SET introductions_complete=0")
            if version < 5:
                db.execute("ALTER TABLE source ADD COLUMN citations_complete INTEGER NOT NULL DEFAULT 0 CHECK(citations_complete IN (0,1))")
            occurrence_ddl = schema_text.split("CREATE TABLE IF NOT EXISTS source_concept (", 1)[1].split("\n);", 1)[0]
            db.execute("DROP VIEW IF EXISTS active_source_concept")
            db.execute("CREATE TABLE source_concept_v7 (" + occurrence_ddl + "\n)")
            # Merge duplicate roles at the same location, preserving every note
            # and retaining the earliest occurrence ID. Original rows are audited.
            grouped = {}
            for row in before:
                # All previous introduction claims mixed exposition and priority.
                # Preserve them as explanations pending an evidence-based audit.
                role = "explains" if row["role"] == "introduces" else canonical_role(row["role"])
                key = (row["source_id"], row["concept_id"], role, row["locator"])
                if key not in grouped:
                    grouped[key] = {**row, "role": key[2], "introduction_evidence": ""}
                elif row["note"] and row["note"] != grouped[key]["note"]:
                    grouped[key]["note"] += ("\n" if grouped[key]["note"] else "") + row["note"]
            db.executemany("INSERT INTO source_concept_v7 VALUES (:id,:source_id,:concept_id,:role,:locator,:note,:introduction_evidence)", grouped.values())
            db.execute("DROP TABLE source_concept")
            db.execute("ALTER TABLE source_concept_v7 RENAME TO source_concept")
            event(db, "schema_migration", "Separate evidence-backed original contributions from explanations; invalidate ambiguous introduction reviews",
                  {"schema_version": version, "source_concepts": before, "introduction_reviews": previous_reviews},
                  {"schema_version": 7, "source_concepts": list(grouped.values())})
        if columns and version < 8:
            before_reviews=[dict(r) for r in db.execute('SELECT id,kind,prerequisites_complete FROM concept')]
            for trigger in ('prerequisites_changed_insert','prerequisites_changed_delete','prerequisites_changed_update','concept_changed_review'):
                db.execute('DROP TRIGGER IF EXISTS '+trigger)
            db.execute("ALTER TABLE concept ADD COLUMN statement_prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(statement_prerequisites_complete IN (0,1))")
            db.execute("ALTER TABLE concept ADD COLUMN proof_prerequisites_complete INTEGER NOT NULL DEFAULT 0 CHECK(proof_prerequisites_complete IN (0,1))")
            db.execute("ALTER TABLE concept_dependency ADD COLUMN purpose TEXT NOT NULL DEFAULT 'unclassified' CHECK(purpose IN ('statement','proof','both','unclassified'))")
            # Definition/construction inputs concern understanding the definition.
            # The theorem distinction needs mathematical review, not inference
            # from logical/pedagogical basis or an old union-completeness flag.
            db.execute("UPDATE concept_dependency SET purpose='statement' WHERE dependent_id IN (SELECT id FROM concept WHERE kind NOT IN ('theorem','conjecture'))")
            db.execute("UPDATE concept SET statement_prerequisites_complete=prerequisites_complete WHERE kind NOT IN ('theorem','conjecture')")
            event(db,'schema_migration','Separate statement and proof prerequisites; retain theorem classifications as unknown until reviewed.',
                  {'schema_version':7,'reviews':before_reviews},{'schema_version':8,'theorem_edges':'unclassified'})
        old_review_trigger=db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='prerequisites_changed_update'").fetchone()
        repair_review_trigger=bool(old_review_trigger and "OLD.purpose IN ('statement','both')" not in old_review_trigger[0])
        if repair_review_trigger:db.execute('DROP TRIGGER prerequisites_changed_update')
        migrate_formalizations = columns and version == 9
        if migrate_formalizations:
            # SQLite CHECK constraints require rebuilding the parent and its link
            # table together. Preserve IDs, measurements, notes and review dates.
            for view in ('concept_formalization_loc', 'formalization_file_allocation'):
                db.execute('DROP VIEW IF EXISTS ' + view)
            for trigger in ('formalization_file_library_insert', 'formalization_file_library_update'):
                db.execute('DROP TRIGGER IF EXISTS ' + trigger)
            db.execute('ALTER TABLE concept_formalization_file RENAME TO concept_formalization_file_v9')
            db.execute('ALTER TABLE concept_formalization RENAME TO concept_formalization_v9')
        execute_schema(db, schema_text)
        if migrate_formalizations:
            db.execute('INSERT INTO concept_formalization SELECT * FROM concept_formalization_v9')
            db.execute('INSERT INTO concept_formalization_file SELECT * FROM concept_formalization_file_v9')
            db.execute('DROP TABLE concept_formalization_file_v9')
            db.execute('DROP TABLE concept_formalization_v9')
        if repair_review_trigger:
            event(db,'schema_trigger_correction','Adding or removing only the proof role of an unchanged statement dependency preserves its statement review.',
                  {'sql':old_review_trigger[0]},
                  {'sql':db.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='prerequisites_changed_update'").fetchone()[0]})
        if columns and version < 9:
            event(db, 'schema_migration', 'Add library formalization reviews, implementing files and shared file LOC estimates',
                  {'schema_version': 8}, {'schema_version': 9})
        if columns and version < 10:
            event(db, 'schema_migration', 'Distinguish dependency-only availability from native implementation/API contributions',
                  {'schema_version': 9}, {'schema_version': 10})


def lookup(db, table, slug):
    if table not in ("concept", "source"):
        raise ValueError("Invalid entity type")
    row = db.execute(f"SELECT * FROM {table} WHERE slug = ? OR id = ?", (slug, slug)).fetchone()
    if row is None:
        raise ValueError(f"Unknown {table}: {slug}")
    return row


def add_identifier(db, source_id, scheme, value):
    scheme, value = normalize_identifier(scheme, value)
    existing = db.execute("SELECT source_id FROM source_identifier WHERE scheme=? AND value=?", (scheme, value)).fetchone()
    if existing and existing[0] != source_id:
        raise ValueError(f"Identifier already belongs to another source: {scheme}:{value}; review identity explicitly")
    db.execute("INSERT INTO source_identifier VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (scheme, value, source_id))


def add_concept(db, item):
    ident = item.get("id", stable_id("concept", item["slug"]))
    if "scope" in item:
        raise ValueError("Concepts have a name and definition or theorem statement; the removed scope field is not accepted")
    db.execute("INSERT INTO concept(id,slug,title,kind,description,field,boundary) VALUES (?,?,?,?,?,?,?)",
               (ident, item["slug"], item["title"], item["kind"], item["description"], item["field"], int(item.get("boundary", False))))
    for alias in item.get("aliases", []):
        db.execute("INSERT INTO concept_alias VALUES (?,?)", (ident, alias))
    return ident


def add_edge(db, item):
    prereq = lookup(db, "concept", item["prerequisite"])["id"]
    dep = lookup(db, "concept", item["dependent"])["id"]
    evidence = lookup(db, "source", item["source"])["id"] if item.get("source") else None
    theorem=lookup(db,'concept',dep)['kind'] in ('theorem','conjecture')
    purpose=item.get('purpose','unclassified' if theorem else 'statement')
    if purpose in ('proof','both') and not theorem:
        raise ValueError('Proof prerequisites target theorem-shaped concepts')
    db.execute("""INSERT INTO concept_dependency(prerequisite_id,dependent_id,basis,rationale,evidence_source_id,locator,purpose)
                  VALUES (?,?,?,?,?,?,?)""",
               (prereq, dep, item["basis"], item["rationale"], evidence, item.get("locator"),purpose))


def add_link(db, item):
    source_id = lookup(db, "source", item["source"])["id"]
    concept_id = lookup(db, "concept", item["concept"])["id"]
    if lookup(db, "concept", item["concept"])["status"] != "active":
        raise ValueError("New links must target active concepts")
    key = (source_id, concept_id, canonical_role(item["role"]), item["locator"])
    existing = db.execute("SELECT id,note,introduction_evidence FROM source_concept WHERE source_id=? AND concept_id=? AND role=? AND locator=?", key).fetchone()
    note = item.get("note", "")
    evidence = item.get("introduction_evidence", "")
    if key[2] == "introduces" and (not isinstance(evidence, str) or not evidence.strip()):
        raise ValueError("introduces requires introduction_evidence for the source's original contribution; use explains for exposition or another proof")
    if existing:
        if evidence and evidence != existing["introduction_evidence"]:
            db.execute("UPDATE source_concept SET introduction_evidence=? WHERE id=?", (evidence, existing["id"]))
        if note and note not in existing["note"].split("\n"):
            db.execute("UPDATE source_concept SET note=? WHERE id=?",
                       (existing["note"] + ("\n" if existing["note"] else "") + note, existing["id"]))
    else:
        db.execute("INSERT INTO source_concept(source_id,concept_id,role,locator,note,introduction_evidence) VALUES (?,?,?,?,?,?)", (*key, note, evidence))


def extract_identifiers(text):
    """Extract explicit identifiers, without guessing identity from a title."""
    found = set()

    def collect(scheme, value):
        value = value.rstrip(".,;]}>\"'")
        while value.endswith(")") and value.count(")") > value.count("("):
            value = value[:-1]
        try:
            found.add(normalize_identifier(scheme, value))
        except ValueError:
            pass  # An imperfect text extraction is not a verified identifier.

    for value in re.findall(r'https?://[^\s<>"\']+', text, re.I):
        collect("url", value)
        if re.match(r"https?://arxiv\.org/(abs|pdf)/", value, re.I):
            collect("arxiv", value)
    for value in re.findall(r'(?<!\w)(10\.\d{4,9}/[^\s<>"\']+)', text, re.I):
        collect("doi", value)
    for value in re.findall(r"\barxiv\s*:?\s*((?:\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})(?:v\d+)?)", text, re.I):
        collect("arxiv", value)
    for value in re.findall(r"\bZbl\s*:?\s*(\d{4}\.\d+)", text, re.I):
        collect("zbl", value)
    for value in re.findall(r"\bISBN(?:-1[03])?\s*:?\s*([\dXx][\dXx -]{8,24}[\dXx])", text, re.I):
        collect("isbn", value)
    return sorted(found)


def citation_record(db, ident):
    row = db.execute("SELECT * FROM citation WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown citation: {ident}")
    out = dict(row)
    if out["pedagogically_necessary"] is not None:
        out["pedagogically_necessary"] = bool(out["pedagogically_necessary"])
    out["identifiers"] = [dict(r) for r in db.execute(
        "SELECT scheme,value FROM citation_identifier WHERE citation_id=? ORDER BY scheme,value", (ident,))]
    return out


def resolve_citation(db, ident):
    row = citation_record(db, ident)
    candidates = {r[0] for r in db.execute("""SELECT DISTINCT s.source_id FROM source_identifier s
        JOIN citation_identifier ci ON ci.scheme=s.scheme AND ci.value=s.value WHERE ci.citation_id=?""", (ident,))}
    if row["cited_source_id"]:
        candidates.add(row["cited_source_id"])
    if len(candidates) > 1:
        raise ValueError(f"Citation {ident} identifiers point to conflicting sources; review identity explicitly")
    if candidates:
        db.execute("UPDATE citation SET cited_source_id=? WHERE id=?", (next(iter(candidates)), ident))


def add_citation(db, item):
    necessary = item.get("pedagogically_necessary")
    if necessary is not None and type(necessary) is not bool:
        raise ValueError("pedagogically_necessary must be true, false or null")
    target = lookup(db, "source", item["cited_source"])["id"] if item.get("cited_source") else None
    ident = db.execute("""INSERT INTO citation(source_id,label,text,cited_source_id,pedagogically_necessary,needed_material)
        VALUES (?,?,?,?,?,?) RETURNING id""", (lookup(db, "source", item["source"])["id"], item.get("label"), item["text"],
                                 target, necessary, item.get("needed_material"))).fetchone()[0]
    identifiers = set(extract_identifiers(item["text"]))
    identifiers.update(normalize_identifier(*pair) for pair in item.get("identifiers", []))
    db.executemany("INSERT INTO citation_identifier VALUES (?,?,?)", [(ident, *pair) for pair in sorted(identifiers)])
    resolve_citation(db, ident)
    return ident


def revise_citation(db, ident, changes, reason):
    allowed = {"label", "text", "cited_source", "pedagogically_necessary", "needed_material", "identifiers"}
    if not changes or not set(changes) <= allowed or not reason.strip():
        raise ValueError("Expected citation fields and a revision reason")
    if "pedagogically_necessary" in changes and changes["pedagogically_necessary"] is not None and type(changes["pedagogically_necessary"]) is not bool:
        raise ValueError("pedagogically_necessary must be true, false or null")
    with db:
        before = citation_record(db, ident)
        values = {k: v for k, v in changes.items() if k not in ("cited_source", "identifiers")}
        if "text" in changes or "identifiers" in changes:
            db.execute("DELETE FROM citation_identifier WHERE citation_id=?", (ident,))
            identifiers = set(extract_identifiers(changes.get("text", before["text"])))
            identifiers.update(normalize_identifier(*pair) for pair in changes.get("identifiers", []))
            db.executemany("INSERT INTO citation_identifier VALUES (?,?,?)", [(ident, *pair) for pair in sorted(identifiers)])
        if "text" in changes:
            values["cited_source_id"] = None
        if "cited_source" in changes:
            values["cited_source_id"] = lookup(db, "source", changes["cited_source"])["id"] if changes["cited_source"] else None
        if values:
            db.execute(f"UPDATE citation SET {','.join(k + '=?' for k in values)} WHERE id=?", (*values.values(), ident))
        resolve_citation(db, ident)
        event(db, "revise_citation", reason, before, citation_record(db, ident))


def resolve_citations(db, source, reason):
    if not reason.strip():
        raise ValueError("A resolution reason is required")
    with db:
        sid = lookup(db, "source", source)["id"]
        before = [citation_record(db, r[0]) for r in db.execute("SELECT id FROM citation WHERE source_id=? ORDER BY id", (sid,))]
        for row in before:
            db.executemany("INSERT INTO citation_identifier VALUES (?,?,?) ON CONFLICT DO NOTHING",
                           [(row["id"], *pair) for pair in extract_identifiers(row["text"])])
            resolve_citation(db, row["id"])
        after = [citation_record(db, row["id"]) for row in before]
        event(db, "resolve_citations", reason, before, after)
    return after


def add_related(db, item):
    a, b = sorted(lookup(db, "concept", item[k])["id"] for k in ("concept_a", "concept_b"))
    evidence = lookup(db, "source", item["source"])["id"] if item.get("source") else None
    db.execute("""INSERT INTO concept_related(concept_a_id,concept_b_id,rationale,evidence_source_id,locator)
                  VALUES (?,?,?,?,?)""", (a, b, item["rationale"], evidence, item.get("locator")))


def related(db, concept):
    ident = lookup(db, "concept", concept)["id"]
    return [dict(r) for r in db.execute("""SELECT r.id,c.slug,c.title,r.rationale,r.evidence_source_id,r.locator
        FROM concept_related r JOIN concept c ON c.id=CASE WHEN r.concept_a_id=?
        THEN r.concept_b_id ELSE r.concept_a_id END
        WHERE r.concept_a_id=? OR r.concept_b_id=? ORDER BY c.title""", (ident, ident, ident))]


def set_completeness(db, kind, slug, changes, reason):
    allowed = {"concept": {"prerequisites_complete","statement_prerequisites_complete","proof_prerequisites_complete"},
               "source": {"requirements_complete", "introductions_complete", "citations_complete"}}
    if (kind not in allowed or not changes or not set(changes) <= allowed[kind]
            or any(type(value) is not bool for value in changes.values()) or not reason.strip()):
        raise ValueError("Expected appropriate completion flags, boolean judgments and a review reason")
    with db:
        before = dict(lookup(db, kind, slug))
        if kind == "concept" and before["status"] != "active":
            raise ValueError("Cannot review a superseded concept")
        if kind=='concept':
            changes=dict(changes)
            theorem=before['kind'] in ('theorem','conjecture')
            unknown=db.execute("SELECT 1 FROM concept_dependency WHERE dependent_id=? AND purpose='unclassified'",(before['id'],)).fetchone()
            if unknown and any(changes.get(k) for k in ('statement_prerequisites_complete','proof_prerequisites_complete')):
                raise ValueError('Classify incoming statement/proof dependencies before certifying typed coverage')
            if not theorem and changes.get('proof_prerequisites_complete'):
                raise ValueError('Proof coverage is a judgment for theorem-shaped concepts')
            if 'prerequisites_complete' in changes:
                # Compatibility for older explicit reviews; never infer a typed
                # theorem review while its incoming roles remain unclassified.
                if not unknown:
                    changes['statement_prerequisites_complete']=changes['prerequisites_complete']
                    if theorem:changes['proof_prerequisites_complete']=changes['prerequisites_complete']
            else:
                statement=changes.get('statement_prerequisites_complete',before['statement_prerequisites_complete'])
                proof=changes.get('proof_prerequisites_complete',before['proof_prerequisites_complete'])
                changes['prerequisites_complete']=bool(statement and (proof or not theorem))
        db.execute(f"UPDATE {kind} SET {','.join(k + '=?' for k in changes)} WHERE id=?",
                   (*changes.values(), before["id"]))
        event(db, "review_" + kind, reason, before, dict(lookup(db, kind, slug)))


def event(db, operation, reason, before, after):
    db.execute("INSERT INTO curation_event(operation,reason,before_json,after_json) VALUES (?,?,?,?)",
               (operation, reason, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))


def ingest(db, payload):
    """An atomic, append-only batch. A repeated slug is an error, never an overwrite."""
    unknown = set(payload) - {"sources", "concepts", "dependencies", "related_concepts", "source_concepts", "source_relations", "citations", "formalization_libraries", "formalization_files", "formalizations", "note"}
    if unknown:
        raise ValueError(f"Unrecognized ingestion fields: {sorted(unknown)}. Use the v7 concept format.")
    with atomic(db):
        for item in payload.get("sources", []):
            missing={'slug','title','authors','field','status','coverage','summary','dependency_review','identifiers'}-set(item)
            if missing:
                raise ValueError(f"Source {item.get('slug','<unnamed>')} is missing required fields: {', '.join(sorted(missing))}")
            if not isinstance(item.get('authors'),list) or not all(isinstance(name,str) for name in item['authors']):
                raise ValueError('authors must be an array of names')
            ident = item.get("id", stable_id("source", item["slug"]))
            db.execute("""INSERT INTO source(id,slug,title,authors,year,field,status,coverage,summary,dependency_review)
                          VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       (ident, item["slug"], item["title"], json.dumps(item["authors"], ensure_ascii=False),
                        item.get("year"), item["field"], item["status"], item["coverage"], item["summary"], item["dependency_review"]))
            if not item["identifiers"]:
                raise ValueError("Every source needs an external identifier")
            for scheme, value in item["identifiers"]:
                add_identifier(db, ident, scheme, value)
            for artifact in item.get("artifacts", []):
                db.execute("""INSERT INTO source_artifact(source_id,url,version,accessed_at,sha256,local_path,note)
                              VALUES (?,?,?,?,?,?,?)""",
                           (ident, artifact["url"], artifact.get("version", ""), artifact["accessed_at"],
                            artifact.get("sha256"), artifact.get("local_path"), artifact.get("note", "")))
        for item in payload.get("concepts", []):
            add_concept(db, item)
        for item in payload.get("dependencies", []):
            add_edge(db, item)
        for item in payload.get("related_concepts", []):
            add_related(db, item)
        for item in payload.get("source_concepts", []):
            add_link(db, item)
        for item in payload.get("source_relations", []):
            db.execute("""INSERT INTO source_relation(dependent_id,prerequisite_id,kind,fact,locator,rationale,general_availability)
                          VALUES (?,?,?,?,?,?,?)""",
                       (lookup(db, "source", item["dependent"])["id"], lookup(db, "source", item["prerequisite"])["id"],
                        item["kind"], item["fact"], item["locator"], item["rationale"], item["general_availability"]))
        for item in payload.get("citations", []):
            add_citation(db, item)
        reason = payload.get('note', 'Manual batch')
        for item in payload.get('formalization_libraries', []):
            save_library(db, item, reason)
        for item in payload.get('formalization_files', []):
            save_formalization_file(db, item, reason)
        for item in payload.get('formalizations', []):
            require_fields(item, ('concept', 'library', 'status', 'evidence', 'files'), ('concept', 'library', 'status', 'evidence', 'files'))
            save_formalization(db, item['concept'], item['library'],
                              {k: item[k] for k in ('status', 'evidence', 'files')}, reason)
        event(db, "ingest", reason, {}, payload)


def revise(db, slug, changes, reason):
    allowed = {"title", "kind", "description", "field", "boundary"}
    if not changes or not set(changes) <= allowed:
        raise ValueError("Editable fields: title, kind, description, field, boundary")
    with db:
        before = dict(lookup(db, "concept", slug))
        if before["status"] != "active":
            raise ValueError("Cannot revise a superseded concept")
        if "title" in changes and changes["title"] != before["title"]:
            db.execute("INSERT INTO concept_alias VALUES (?,?) ON CONFLICT DO NOTHING", (before["id"], before["title"]))
        db.execute(f"UPDATE concept SET {','.join(k + '=?' for k in changes)} WHERE id=?",
                   (*changes.values(), before["id"]))
        affected = [r[0] for r in db.execute("SELECT DISTINCT source_id FROM source_concept WHERE concept_id=?", (before["id"],))]
        db.executemany("UPDATE source SET status='draft' WHERE id=? AND status='reviewed'", [(s,) for s in affected])
        event(db, "revise", reason, before, dict(lookup(db, "concept", slug)))


def retirement_inventory(db, slugs):
    """Exact current references for a retirement without an equivalent replacement."""
    old=[dict(lookup(db,'concept',slug)) for slug in slugs]
    ids={r['id'] for r in old}
    edges=[dict(r) for r in db.execute('SELECT * FROM concept_dependency')]
    return {'concepts':old,
            'incoming':[r for r in edges if r['dependent_id'] in ids],
            'outgoing':[r for r in edges if r['prerequisite_id'] in ids],
            'source_occurrences':[dict(r) for r in db.execute('SELECT * FROM source_concept') if r['concept_id'] in ids],
            'aliases':[dict(r) for r in db.execute('SELECT * FROM concept_alias') if r['concept_id'] in ids],
            'related':[dict(r) for r in db.execute('SELECT * FROM concept_related') if r['concept_a_id'] in ids or r['concept_b_id'] in ids],
            'formalizations':[formalization_record(db,r['id']) for r in db.execute('SELECT id,concept_id FROM concept_formalization') if r['concept_id'] in ids]}


def reorganize(db, plan):
    """Explicit split/merge/retire routes account for every old reference.

    edge_routes and link_routes map old integer IDs to replacement rows; an empty
    replacement requires a reason. Old occurrences remain as historical evidence.
    The entire operation, including audit data and new concepts, commits or rolls back.
    """
    if plan["operation"] not in ("split", "merge", "retire") or not plan.get("reason", "").strip():
        raise ValueError("Expected split/merge/retire and a reason")
    with atomic(db):
        old = [dict(lookup(db, "concept", slug)) for slug in plan["from"]]
        if not old or len({x["id"] for x in old}) != len(old) or any(x["status"] != "active" for x in old):
            raise ValueError("Distinct active source concepts required")
        if plan["operation"] == "split" and (len(old) != 1 or len(plan["to"]) < 2):
            raise ValueError("A split needs one old concept and at least two replacements")
        if plan["operation"] == "merge" and (len(old) < 2 or len(plan["to"]) != 1):
            raise ValueError("A merge needs at least two old concepts and one replacement")
        retiring=plan['operation']=='retire'
        if retiring and plan['to']:
            raise ValueError('Retirement has no equivalent replacement; to must be empty')
        old_ids = {x["id"] for x in old}
        aliases=[dict(r) for r in db.execute('SELECT * FROM concept_alias') if r['concept_id'] in old_ids]
        if retiring:
            current=retirement_inventory(db,plan['from'])
            expected=plan.get('incident_inventory',{})
            canonical=lambda rows:sorted(json.dumps(r,sort_keys=True) for r in rows)
            if set(current)!=set(expected) or any(canonical(current[k])!=canonical(expected[k]) for k in current):
                raise ValueError('Retirement requires the exact current complete incident_inventory')
            dispositions=plan.get('alias_dispositions',[])
            old_slugs={r['id']:r['slug'] for r in old}
            pairs={(old_slugs[r['concept_id']],r['alias']) for r in aliases}
            supplied=[(r.get('concept'),r.get('alias')) for r in dispositions]
            if (len(supplied)!=len(pairs) or set(supplied)!=pairs or
                    any(r.get('action')!='historical_only' or not r.get('reason','').strip() for r in dispositions)):
                raise ValueError('Retirement must review every alias as historical_only with a reason')
        edges = [dict(r) for r in db.execute("SELECT * FROM concept_dependency")
                 if r["prerequisite_id"] in old_ids or r["dependent_id"] in old_ids]
        links = [dict(r) for r in db.execute("SELECT * FROM source_concept") if r["concept_id"] in old_ids]
        neighbors = [dict(r) for r in db.execute("SELECT * FROM concept_related")
                     if r["concept_a_id"] in old_ids or r["concept_b_id"] in old_ids]
        formalization_reviews = [formalization_record(db, r['id']) for r in db.execute('SELECT id,concept_id FROM concept_formalization')
                                if r['concept_id'] in old_ids]
        for name, rows in (("edge_routes", edges), ("link_routes", links), ("related_routes", neighbors),
                           ('formalization_routes', formalization_reviews)):
            if set(plan.get(name, {})) != {str(r["id"]) for r in rows}:
                raise ValueError(f"{name} must account for exactly these IDs: {[r['id'] for r in rows]}")
            for route in plan.get(name, {}).values():
                if retiring and route['replacements']:
                    raise ValueError('Retirement routes cannot invent equivalent replacements')
                if not route["replacements"] and not route.get("reason", "").strip():
                    raise ValueError("Dropping an edge/occurrence requires an explicit reason")
        new_ids = {add_concept(db, item) for item in plan["to"]}
        db.executemany("DELETE FROM concept_dependency WHERE id=?", [(e["id"],) for e in edges])
        db.executemany("DELETE FROM concept_related WHERE id=?", [(r["id"],) for r in neighbors])
        for row in old:
            db.execute("UPDATE concept SET status='superseded' WHERE id=?", (row["id"],))
            db.execute("DELETE FROM concept_embedding WHERE concept_id=?", (row["id"],))
        for edge in edges:
            for replacement in plan["edge_routes"][str(edge["id"])]["replacements"]:
                p = lookup(db, "concept", replacement["prerequisite"])["id"]
                d = lookup(db, "concept", replacement["dependent"])["id"]
                # Routing can replace only the old endpoint(s); unrelated edits are separate.
                for orig, new in ((edge["prerequisite_id"], p), (edge["dependent_id"], d)):
                    if (orig in old_ids and new not in new_ids) or (orig not in old_ids and orig != new):
                        raise ValueError("Edge route changed an unrelated endpoint")
                add_edge(db, replacement)
        for neighbor in neighbors:
            original = {neighbor["concept_a_id"], neighbor["concept_b_id"]}
            for replacement in plan["related_routes"][str(neighbor["id"])]["replacements"]:
                endpoints = {lookup(db, "concept", replacement[k])["id"] for k in ("concept_a", "concept_b")}
                if endpoints - new_ids != original - old_ids or not endpoints & new_ids:
                    raise ValueError("Related route changed an unrelated endpoint")
                add_related(db, replacement)
        for link in links:
            for replacement in plan["link_routes"][str(link["id"])]["replacements"]:
                route = {"concept": replacement} if isinstance(replacement, str) else replacement
                if set(route) - {"concept", "role", "locator", "note", "introduction_evidence"}:
                    raise ValueError("Occurrence route may change its concept, role, location, note and origin evidence only")
                ident = lookup(db, "concept", route["concept"])["id"]
                if ident not in new_ids:
                    raise ValueError("Occurrence route must target a replacement concept")
                if link["role"] == "introduces" and (isinstance(replacement, str) or "role" not in route):
                    raise ValueError("Route an introduction explicitly with its reviewed role and introduction_evidence")
                add_link(db, {"source": link["source_id"], "role": link["role"],
                              "locator": link["locator"], "note": link["note"], **route})
        routed_reviews = set()
        for review in formalization_reviews:
            for route in plan['formalization_routes'][str(review['id'])]['replacements']:
                require_fields(route, ('concept', 'library', 'status', 'evidence', 'files'),
                               ('concept', 'library', 'status', 'evidence', 'files'))
                ident = lookup(db, 'concept', route['concept'])['id']
                if ident not in new_ids or route['library'] != review['library_slug']:
                    raise ValueError('Formalization routes must target a replacement concept in the same library')
                key = (ident, route['library'])
                if key in routed_reviews:
                    raise ValueError('Consolidate merged formalizations into one review per replacement/library')
                routed_reviews.add(key)
                save_formalization(db, route['concept'], route['library'],
                                   {k: route[k] for k in ('status', 'evidence', 'files')}, plan['reason'])
        for edge in plan.get("new_dependencies", []):
            if lookup(db, "concept", edge["prerequisite"])["id"] not in new_ids and lookup(db, "concept", edge["dependent"])["id"] not in new_ids:
                raise ValueError("New internal edges must touch a replacement concept")
            add_edge(db, edge)
        affected = {r["source_id"] for r in links}
        db.executemany("UPDATE source SET status='draft' WHERE id=? AND status='reviewed'", [(s,) for s in affected])
        event(db, plan["operation"], plan["reason"], {"concepts": old, "edges": edges, "links": links, "related": neighbors,
                                                     'aliases':aliases,'formalizations': formalization_reviews}, plan)


@contextmanager
def atomic(db):
    """Nest mutations without committing a caller's ingestion/API transaction."""
    db.execute('SAVEPOINT formalization_mutation')
    try:
        yield
    except BaseException:
        db.execute('ROLLBACK TO formalization_mutation')
        db.execute('RELEASE formalization_mutation')
        raise
    else:
        db.execute('RELEASE formalization_mutation')


def require_fields(item, allowed, required=()):
    if not isinstance(item, dict):
        raise ValueError('Expected a JSON object')
    if set(item) - set(allowed) or set(required) - set(item):
        raise ValueError(f'Expected fields {sorted(required)}; allowed fields {sorted(allowed)}')


def library_record(db, slug):
    row = db.execute('SELECT * FROM formalization_library WHERE slug=?', (slug,)).fetchone()
    if row is None:
        raise ValueError(f'Unknown formalization library: {slug}')
    return dict(row)


def save_library(db, item, reason):
    require_fields(item, ('slug', 'name', 'repository_url'), ('slug', 'name'))
    if not isinstance(item['slug'], str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', item['slug']):
        raise ValueError('Library slug must use lowercase letters, digits and hyphens')
    if not isinstance(item['name'], str) or not item['name'].strip() or not reason.strip():
        raise ValueError('Library name and reason are required')
    with atomic(db):
        before = db.execute('SELECT * FROM formalization_library WHERE slug=?', (item['slug'],)).fetchone()
        url = item.get('repository_url', before['repository_url'] if before else None)
        if url is not None:
            url = normalize_identifier('url', url)[1].rstrip('/')
        db.execute('''INSERT INTO formalization_library(slug,name,repository_url) VALUES (?,?,?)
            ON CONFLICT(slug) DO UPDATE SET name=excluded.name,repository_url=excluded.repository_url''',
            (item['slug'], item['name'], url))
        out = library_record(db, item['slug'])
        event(db, 'save_formalization_library', reason, dict(before) if before else {}, out)
        return out


def formalization_path(path):
    if (not isinstance(path, str) or not path or path != path.strip() or '\\' in path
            or any(ord(c) < 32 for c in path) or path.startswith('/')
            or any(part in ('', '.', '..') for part in path.split('/'))
            or ':' in path or not path.endswith('.lean')):
        raise ValueError('Expected a canonical repository-relative .lean file path')
    return path


def save_formalization_file(db, item, reason):
    """Store a measured whole-file physical line count, or clear a stale measurement."""
    require_fields(item, ('library', 'path', 'loc', 'revision', 'measured_at', 'sha256'), ('library', 'path', 'loc'))
    library_record(db, item['library'])
    path = formalization_path(item['path'])
    loc = item['loc']
    if (loc is not None and (type(loc) is not int or loc < 0)) or not reason.strip():
        raise ValueError('LOC must be a nonnegative integer or null; a reason is required')
    revision = item.get('revision')
    measured_at = item.get('measured_at')
    sha256 = item.get('sha256')
    if loc is not None:
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError('A file measurement requires the inspected repository revision')
        measured_at = measured_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        try:
            stamp = datetime.fromisoformat(measured_at.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Missing timezone')
        except (ValueError, AttributeError, TypeError):
            raise ValueError('measured_at must be an ISO timestamp with timezone') from None
        if sha256 is not None and (not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256)):
            raise ValueError('Expected a lowercase SHA-256 hex digest')
    elif any(v is not None for v in (revision, measured_at, sha256)):
        raise ValueError('Clearing LOC also clears its revision, timestamp and hash')
    with atomic(db):
        before = db.execute('SELECT * FROM formalization_file WHERE library_slug=? AND path=?', (item['library'], path)).fetchone()
        db.execute('''INSERT INTO formalization_file(library_slug,path,loc,revision,measured_at,sha256) VALUES (?,?,?,?,?,?)
            ON CONFLICT(library_slug,path) DO UPDATE SET loc=excluded.loc,revision=excluded.revision,
                measured_at=excluded.measured_at,sha256=excluded.sha256''',
            (item['library'], path, loc, revision, measured_at, sha256))
        out = dict(db.execute('SELECT * FROM formalization_file WHERE library_slug=? AND path=?', (item['library'], path)).fetchone())
        event(db, 'measure_formalization_file', reason, dict(before) if before else {}, out)
        return out


def formalization_record(db, ident):
    row = db.execute('SELECT * FROM concept_formalization WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise ValueError(f'Unknown formalization review: {ident}')
    out = dict(row)
    out['files'] = [dict(r) for r in db.execute('''SELECT f.*,link.declarations,link.note
        FROM concept_formalization_file link JOIN formalization_file f ON f.id=link.file_id
        WHERE link.formalization_id=? ORDER BY f.path''', (ident,))]
    return out


def save_formalization(db, concept, library, item, reason):
    """Replace one concept/library review and its implementing-file set atomically."""
    require_fields(item, ('status', 'evidence', 'files'), ('status', 'evidence', 'files'))
    c = lookup(db, 'concept', concept)
    library_record(db, library)
    if c['status'] != 'active':
        raise ValueError('Cannot review formalization of a superseded concept')
    if item['status'] not in ('formalized', 'partial', 'inherited', 'not_formalized', 'unknown'):
        raise ValueError('Expected formalized, partial, inherited, not_formalized or unknown')
    if not isinstance(item['evidence'], str) or not item['evidence'].strip() or not reason.strip():
        raise ValueError('Formalization evidence and a reason are required')
    files = item['files']
    if not isinstance(files, list) or bool(files) != (item['status'] in ('formalized', 'partial')):
        raise ValueError('Formalized/partial reviews require implementing files; inherited/unknown/not_formalized reviews require an empty file list')
    seen = set()
    for f in files:
        require_fields(f, ('path', 'declarations', 'note'), ('path', 'note'))
        path = formalization_path(f['path'])
        if path in seen:
            raise ValueError('Duplicate implementing file in a concept/library review')
        seen.add(path)
        if not isinstance(f['note'], str) or not f['note'].strip() or not isinstance(f.get('declarations', ''), str):
            raise ValueError('Each file needs a note explaining the definition/theorem/API it implements')
    with atomic(db):
        before = db.execute('SELECT id FROM concept_formalization WHERE concept_id=? AND library_slug=?', (c['id'], library)).fetchone()
        before = formalization_record(db, before[0]) if before else {}
        db.execute('''INSERT INTO concept_formalization(concept_id,library_slug,status,evidence,concept_revision)
            VALUES (?,?,?,?,?) ON CONFLICT(concept_id,library_slug) DO UPDATE SET status=excluded.status,
            evidence=excluded.evidence,concept_revision=excluded.concept_revision,
            reviewed_at=?''',
            (c['id'], library, item['status'], item['evidence'], c['revision'],
             datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
        ident = db.execute('SELECT id FROM concept_formalization WHERE concept_id=? AND library_slug=?', (c['id'], library)).fetchone()[0]
        db.execute('DELETE FROM concept_formalization_file WHERE formalization_id=?', (ident,))
        for f in files:
            db.execute('INSERT INTO formalization_file(library_slug,path) VALUES (?,?) ON CONFLICT DO NOTHING', (library, f['path']))
            file_id = db.execute('SELECT id FROM formalization_file WHERE library_slug=? AND path=?', (library, f['path'])).fetchone()[0]
            db.execute('INSERT INTO concept_formalization_file(formalization_id,file_id,declarations,note) VALUES (?,?,?,?)',
                       (ident, file_id, f.get('declarations', ''), f['note']))
        out = formalization_record(db, ident)
        event(db, 'review_formalization', reason, before, out)
        return out


def formalizations(db, concept=None, library=None, status=None):
    """Current status and equal-share LOC for active concepts, including unknowns.

    Missing measurements yield estimated_loc=null and a separate known_loc subtotal.
    Counts are independent per library and include partial implementations.
    """
    with atomic(db):
        return _formalizations(db, concept, library, status)


def _formalizations(db, concept, library, status):
    args, where = [], ["c.status='active'"]
    if concept is not None:
        where.append('c.id=?')
        args.append(lookup(db, 'concept', concept)['id'])
    if library is not None:
        library_record(db, library)
        where.append('lib.slug=?')
        args.append(library)
    if status is not None and status not in ('formalized', 'partial', 'inherited', 'not_formalized', 'unknown'):
        raise ValueError('Invalid formalization status')
    result = [dict(r) for r in db.execute('''SELECT c.id AS concept_id,c.slug AS concept,c.title,c.kind AS concept_kind,
        lib.slug AS library,lib.name AS library_name,lib.repository_url,
        cf.id AS review_id,cf.status AS recorded_status,cf.evidence,cf.reviewed_at,
        CASE WHEN cf.concept_revision=c.revision THEN cf.status ELSE 'unknown' END AS status,
        CASE WHEN cf.concept_revision<>c.revision THEN 1 ELSE 0 END AS review_needed,
        coalesce(estimate.file_count,0) AS file_count,coalesce(estimate.measured_files,0) AS measured_files,
        estimate.estimated_loc,estimate.known_loc
        FROM concept c CROSS JOIN formalization_library lib
        LEFT JOIN concept_formalization cf ON cf.concept_id=c.id AND cf.library_slug=lib.slug
        LEFT JOIN concept_formalization_loc estimate ON estimate.formalization_id=cf.id
        WHERE ''' + ' AND '.join(where) + ' ORDER BY c.title,lib.name', args)]
    files = {}
    for r in db.execute('''SELECT link.formalization_id,f.*,link.declarations,link.note,
        a.mapped_concepts,a.allocated_loc FROM concept_formalization_file link
        JOIN formalization_file f ON f.id=link.file_id
        LEFT JOIN formalization_file_allocation a ON a.id=f.id ORDER BY f.path'''):
        f = dict(r)
        files.setdefault(f.pop('formalization_id'), []).append(f)
    out = []
    for r in result:
        if status is not None and r['status'] != status:
            continue
        r['statement_only'] = r['concept_kind'] == 'conjecture'
        if r['status'] == 'inherited':
            r['estimated_loc'] = r['known_loc'] = 0.0
        r['review_needed'] = bool(r['review_needed'])
        r['files'] = [dict(f) for f in files.get(r['review_id'], [])]
        for f in r['files']:
            # Old reviews retain their evidence but no longer consume a file share.
            if r['status'] not in ('formalized', 'partial'):
                f['allocated_loc'] = None
            f['url'] = (r['repository_url'].rstrip('/') + '/blob/' + quote(f['revision'], safe='')
                        + '/' + quote(f['path'], safe='/')) if r['repository_url'] and f['revision'] else None
        out.append(r)
    return out


def measure_formalization_files(db, library, root, reason, revision='HEAD'):
    """Count committed bytes of mapped files at an explicitly selected revision.

    Git object reads ensure LOC/hash actually correspond to the stored revision,
    even if a worktree file has local edits. Missing files abort the entire batch.
    """
    import subprocess
    library_record(db, library)
    root = Path(root).resolve()
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout
    try:
        top = Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve()
        if top != root:
            raise ValueError('Use the repository root, not a subdirectory')
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError('Expected a repository revision')
        revision = git('rev-parse', '--verify', '--end-of-options', revision + '^{commit}').decode().strip()
        paths = [r[0] for r in db.execute('''SELECT DISTINCT f.path FROM formalization_file f
            JOIN concept_formalization_file link ON link.file_id=f.id
            JOIN concept_formalization cf ON cf.id=link.formalization_id JOIN concept c ON c.id=cf.concept_id
            WHERE f.library_slug=? AND c.status='active' AND c.revision=cf.concept_revision
            AND cf.status IN ('formalized','partial') ORDER BY f.path''', (library,))]
        measured = []
        for path in paths:
            formalization_path(path)
            mode = git('ls-tree', revision, '--', path).decode().split()[0]
            if mode not in ('100644', '100755'):
                raise ValueError(f'Expected a regular tracked file: {path}')
            content = git('show', f'{revision}:{path}')
            measured.append(dict(library=library, path=path, loc=content.count(b'\n') + int(bool(content) and not content.endswith(b'\n')),
                                 revision=revision, sha256=hashlib.sha256(content).hexdigest()))
    except (subprocess.CalledProcessError, IndexError) as ex:
        raise ValueError('Could not read a mapped file at the selected revision; check the repository and file paths') from ex
    with atomic(db):
        # Core save operations use the caller-owned transaction when nested.
        for item in measured:
            save_formalization_file(db, item, reason)
    return {'library': library, 'revision': revision, 'files_measured': len(measured)}


def closure(db, source_slug, mode='statement'):
    sid = lookup(db, "source", source_slug)["id"]
    nodes={}
    for r in db.execute("SELECT concept_id FROM active_source_concept WHERE source_id=? AND role='relies_on'",(sid,)):
        for node in prerequisite_cone(db,r[0],mode)['nodes']:nodes[node['id']]=node
    return sorted(nodes.values(),key=lambda r:r['title'])


def source_requirements(db, source_slug, mode='statement'):
    """A source's explicit prerequisite frontier and inherited reading background.

    Introduction and explanation occurrences never imply prior knowledge.
    Concepts needed for the source's own proof must be judged and recorded
    explicitly as relies_on links.
    """
    sid = lookup(db, "source", source_slug)["id"]
    occurrences = [dict(r) for r in db.execute("SELECT * FROM active_source_concept WHERE source_id=? AND role='relies_on'", (sid,))]
    candidates = {r["concept_id"] for r in occurrences}
    cones = {ident: prerequisite_cone(db, ident, mode) for ident in candidates}
    covered = {node["id"] for ident, cone in cones.items() for node in cone["nodes"] if node["id"] != ident}
    roots = candidates - covered
    records = {r["id"]: dict(r) for r in closure(db, source_slug, mode)}
    direct, inherited = [], []
    for ident, record in records.items():
        record["occurrences"] = [r for r in occurrences if r["concept_id"] == ident]
        if ident in roots:
            direct.append(record)
        else:
            record["via"] = sorted(records[root]["slug"] for root in roots
                                     if any(n["id"] == ident for n in cones[root]["nodes"]))
            inherited.append(record)
    return {"direct": sorted(direct, key=lambda r: r["title"]),
            "inherited": sorted(inherited, key=lambda r: r["title"])}


def dependency_in_mode(edge, mode):
    if mode not in ('statement','proof','all'):
        raise ValueError('Prerequisite mode must be statement, proof or all')
    return mode=='all' or edge['purpose'] in (('statement','both') if mode=='statement' else ('statement','proof','both'))


def coverage_complete(concept, mode):
    if mode=='statement':return bool(concept['statement_prerequisites_complete'])
    if mode=='proof':
        return bool(concept['statement_prerequisites_complete'] and
                    (concept['kind'] not in ('theorem','conjecture') or concept['proof_prerequisites_complete']))
    return bool(concept['prerequisites_complete'])


def prerequisite_cone(db, slug, mode='statement'):
    """The entire recorded ancestor DAG, including the root, with longest-path depths."""
    root = lookup(db, "concept", slug)
    if root["status"] != "active":
        raise ValueError("Cannot explore a superseded concept")
    if mode not in ('statement','proof','all'):raise ValueError('Prerequisite mode must be statement, proof or all')
    # Only the cone is read: a recursive walk up the selected prerequisite edges.
    purposes={'statement':"('statement','both')",'proof':"('statement','proof','both')"}.get(mode)
    in_mode=f"d.purpose IN {purposes}" if purposes else "1=1"
    cone=f"""WITH RECURSIVE cone(id) AS (SELECT ? UNION
        SELECT d.prerequisite_id FROM concept_dependency d JOIN cone ON d.dependent_id=cone.id WHERE {in_mode})"""
    # Every edge into a cone node: the selected ones are the cone's edges, and the
    # rest give the unclassified inputs and the proof frontier.
    all_edges=[dict(r) for r in db.execute(cone+" SELECT d.* FROM concept_dependency d WHERE d.dependent_id IN (SELECT id FROM cone) ORDER BY d.id", (root['id'],))]
    nodes={r['id']:dict(r) for r in db.execute(cone+" SELECT c.* FROM concept c WHERE c.id IN (SELECT id FROM cone)", (root['id'],))}
    edges=[e for e in all_edges if dependency_in_mode(e,mode) and e['prerequisite_id'] in nodes]
    parents = {ident: [] for ident in nodes}
    incoming = {ident: 0 for ident in nodes}
    for edge in edges:
        parents[edge["dependent_id"]].append(edge["prerequisite_id"])
        incoming[edge["prerequisite_id"]] += 1
    depths = {root["id"]: 0}
    ready = deque([root["id"]])
    while ready:
        child = ready.popleft()
        for parent in parents[child]:
            depths[parent] = max(depths.get(parent, 0), depths[child] + 1)
            incoming[parent] -= 1
            if incoming[parent] == 0:
                ready.append(parent)
    if len(depths) != len(nodes) or any(incoming.values()):
        raise ValueError("Concept graph contains a cycle")
    for ident, row in nodes.items():
        row["depth"] = depths[ident]
        row['coverage_complete']=coverage_complete(row,mode)
    ordered = sorted(nodes.values(), key=lambda r: (r["depth"], r["title"], r["id"]))
    unclassified=[e for e in all_edges if e['dependent_id'] in nodes and e['purpose']=='unclassified']
    proof_frontier=[e for e in all_edges if e['dependent_id'] in nodes and e['purpose'] in ('proof','both') and e['prerequisite_id'] not in nodes]
    return {"root_id": root["id"], 'mode':mode, "nodes": ordered, "edges": edges,
            'unclassified_dependencies':unclassified,'proof_frontier':proof_frontier,
            "unreviewed": [r["slug"] for r in ordered if not r['coverage_complete']],
            "leaves": [r["slug"] for r in ordered if not parents[r["id"]]],
            "max_depth": max(depths.values()), "all_reviewed": not unclassified and all(r['coverage_complete'] for r in ordered)}


def reduction_plan(db, root=None):
    """Find redundant edges, with witnesses consisting only of retained edges."""
    edges = prerequisite_cone(db, root, 'all')["edges"] if root else [dict(r) for r in db.execute("SELECT * FROM concept_dependency ORDER BY id")]
    children = {}
    for edge in edges:
        children.setdefault(edge["prerequisite_id"], []).append(edge)

    def path(start, end, excluded, mode):
        previous = {start: None}
        ready = deque([start])
        while ready:
            current = ready.popleft()
            for edge in children.get(current, []):
                target = edge["dependent_id"]
                if edge["id"] in excluded or target in previous or not dependency_in_mode(edge,mode):
                    continue
                # A proof imports other theorems as black boxes: a proof-only
                # input of an intermediate theorem is not thereby an input of
                # this proof. Proof-only edges may only be the final step.
                if mode == 'proof' and edge['purpose'] == 'proof' and target != end:
                    continue
                previous[target] = edge
                if target == end:
                    result = []
                    while previous[target] is not None:
                        step = previous[target]
                        result.append(step)
                        target = step["prerequisite_id"]
                    return list(reversed(result))
                ready.append(target)
        return None

    redundant = {e["id"] for e in edges if e['purpose']!='unclassified' and
                 path(e["prerequisite_id"], e["dependent_id"], {e["id"]},'statement' if e['purpose'] in ('statement','both') else 'proof')}
    slugs = {r["id"]: r["slug"] for r in db.execute("SELECT id,slug FROM concept")}
    removed = []
    for edge in edges:
        if edge["id"] not in redundant:
            continue
        mode='statement' if edge['purpose'] in ('statement','both') else 'proof'
        witness = path(edge["prerequisite_id"], edge["dependent_id"], redundant,mode)
        if witness is None:
            raise ValueError("Reduction failed to preserve a prerequisite path")
        removed.append({"edge": edge, "path": [slugs[edge["prerequisite_id"]]] + [slugs[e["dependent_id"]] for e in witness],
                        "path_edge_ids": [e["id"] for e in witness],'preserved_mode':mode})
    return {"root": root, "removed": removed, "retained_edges": len(edges) - len(removed)}


def reduce_dependencies(db, reason, root=None):
    if not reason.strip():
        raise ValueError("A reduction reason is required")
    with db:
        plan = reduction_plan(db, root)
        flags=('prerequisites_complete','statement_prerequisites_complete','proof_prerequisites_complete')
        complete = {r['id']:{k:r[k] for k in flags} for r in db.execute('SELECT * FROM concept')}
        for item in plan["removed"]:
            db.execute("DELETE FROM concept_dependency WHERE id=?", (item["edge"]["id"],))
        # No new knowledge is required and reachability is unchanged. Preserve
        # explicit reviews despite the conservative SQL deletion trigger.
        targets = {item["edge"]["dependent_id"] for item in plan["removed"]}
        db.executemany('UPDATE concept SET prerequisites_complete=?,statement_prerequisites_complete=?,proof_prerequisites_complete=? WHERE id=?',
                       [(*[complete[i][k] for k in flags],i) for i in targets])
        event(db, "transitive_reduction", reason,
              {"edges": [x["edge"] for x in plan["removed"]], "reviews": {i: complete[i] for i in targets}}, plan)
    return plan


def snapshot(db):
    tables = ("concept", "concept_alias", "concept_dependency", "concept_related", "source", "source_identifier", "source_artifact", "source_concept", "source_relation", "citation", "citation_identifier", "formalization_library", "formalization_file", "concept_formalization", "concept_formalization_file")
    if is_postgres(db):
        # PostgreSQL has no rowid; order by primary key.
        keys = {r[0]: r[1] for r in db.execute("""SELECT c.relname, string_agg(a.attname, ',' ORDER BY k.ord)
            FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
            WHERE i.indisprimary AND c.relnamespace=to_regnamespace(current_schema()) GROUP BY c.relname""")}
        return {table: [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY {keys[table]}")] for table in tables}
    return {table: [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in tables}


def verify(db):
    errors = []
    if not is_postgres(db):
        # PostgreSQL enforces foreign keys and page integrity itself.
        errors += [f"Foreign key: {tuple(r)}" for r in db.execute("PRAGMA foreign_key_check")]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            errors.append(integrity)
    active = {r["id"] for r in db.execute("SELECT id FROM concept WHERE status='active'")}
    indegree = {i: 0 for i in active}
    children = {i: [] for i in active}
    for row in db.execute("SELECT prerequisite_id,dependent_id FROM concept_dependency"):
        p, d = row
        if p not in active or d not in active:
            errors.append("Dependency touches a superseded concept")
            continue
        children[p].append(d)
        indegree[d] += 1
    queue = [i for i in active if indegree[i] == 0]
    visited = 0
    while queue:
        item = queue.pop()
        visited += 1
        for child in children[item]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(active):
        errors.append("Concept graph contains a cycle")
    for row in db.execute("SELECT slug,id,authors FROM source"):
        try:authors=json.loads(row['authors'])
        except (TypeError,json.JSONDecodeError):authors=None
        if not isinstance(authors,list) or not all(isinstance(name,str) for name in authors):
            errors.append(f"Source authors must be an array of names: {row['slug']}")
        if not db.execute("SELECT 1 FROM source_identifier WHERE source_id=?", (row["id"],)).fetchone():
            errors.append(f"Source without identifier: {row['slug']}")
    for row in db.execute("SELECT * FROM concept_related"):
        if row["concept_a_id"] not in active or row["concept_b_id"] not in active:
            errors.append("Related link touches a superseded concept")
    for row in db.execute('SELECT * FROM formalization_file'):
        try:
            formalization_path(row['path'])
        except ValueError as ex:
            errors.append(str(ex))
    for row in db.execute('''SELECT cf.id,cf.status,count(link.file_id) AS files FROM concept_formalization cf
        LEFT JOIN concept_formalization_file link ON link.formalization_id=cf.id GROUP BY cf.id'''):
        if bool(row['files']) != (row['status'] in ('formalized', 'partial')):
            errors.append(f"Formalization review {row['id']} has an inconsistent implementing-file list")
    if db.execute('''SELECT 1 FROM concept_formalization_file link
        JOIN concept_formalization cf ON cf.id=link.formalization_id JOIN formalization_file f ON f.id=link.file_id
        WHERE cf.library_slug<>f.library_slug''').fetchone():
        errors.append('Formalization file belongs to a different library')
    for row in db.execute("""SELECT e.*,i.title,i.kind,i.description,i.status,m.dimensions FROM concept_embedding e
                             JOIN concept i ON i.id=e.concept_id JOIN embedding_model m ON m.id=e.model_id"""):
        if row["status"] != "active" or content_hash(row) != row["content_sha256"]:
            errors.append(f"Stale embedding: {row['concept_id']}")
        if len(row["vector"]) != 4 * row["dimensions"]:
            errors.append(f"Invalid embedding length: {row['concept_id']}")
    if errors:
        raise ValueError("\n".join(errors))
    return {"active_concepts": len(active), "concept_dependencies": sum(len(v) for v in children.values()),
            "citations": db.execute("SELECT count(*) FROM citation").fetchone()[0],
            "related_concepts": db.execute("SELECT count(*) FROM concept_related").fetchone()[0],
            "formalization_reviews": db.execute('SELECT count(*) FROM concept_formalization').fetchone()[0],
            "formalization_files": db.execute('SELECT count(*) FROM formalization_file').fetchone()[0],
            "sources": db.execute("SELECT count(*) FROM source").fetchone()[0],
            "ingested_sources": db.execute("SELECT count(*) FROM source WHERE status <> 'catalogued'").fetchone()[0],
            "strict_source_dependencies": db.execute("SELECT count(*) FROM strict_source_dependency").fetchone()[0],
            "vectors": db.execute("SELECT count(*) FROM concept_embedding").fetchone()[0], "integrity": "ok", "dag": True}


def content_hash(row):
    return hashlib.sha256(embedding_text(row).encode()).hexdigest()


def embedding_text(row):
    return f"{row['title']}. {row['description']}"


def load_model():
    try:
        from fastembed import TextEmbedding
    except ImportError as ex:
        raise ValueError('Install embeddings with: uv sync --extra embeddings') from ex
    model = TextEmbedding(MODEL, cache_dir=str(ROOT / ".cache/embeddings"), threads=2, providers=["CPUExecutionProvider"])
    # Hash tokenizer and weights, so two different encoders never share a vector space.
    model_dir = Path(model.model._model_dir)  # FastEmbed 0.9.1; version pinned in pyproject.toml.
    files = sorted(p for p in model_dir.rglob("*") if p.is_file() and p.suffix in (".onnx", ".json", ".txt"))
    if not files:
        raise ValueError("Cannot fingerprint embedding artifacts")
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(model_dir)).encode())
        with path.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                digest.update(chunk)
    import importlib.metadata
    config = {"engine": "fastembed", "version": importlib.metadata.version("fastembed"),
              "onnxruntime": importlib.metadata.version("onnxruntime"), "provider": "CPUExecutionProvider",
              "document_format": "title. description; concepts-v3", "query": "query_embed", "normalized": True}
    fingerprint = digest.hexdigest()
    model_id = hashlib.sha256((MODEL + fingerprint + json.dumps(config, sort_keys=True)).encode()).hexdigest()
    return model, model_id, fingerprint, config


def normalized(values):
    values = [float(x) for x in values]
    norm = math.sqrt(sum(x*x for x in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Invalid model output")
    return [x / norm for x in values]


def embed(db):
    model, mid, fingerprint, config = load_model()
    rows = db.execute("SELECT * FROM concept WHERE status='active' ORDER BY id").fetchall()
    pending = [r for r in rows if not db.execute(
        "SELECT 1 FROM concept_embedding WHERE concept_id=? AND model_id=? AND content_sha256=?",
        (r["id"], mid, content_hash(r))).fetchone()]
    with db:
        db.execute("INSERT INTO embedding_model VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING", (mid, MODEL, fingerprint, 384, json.dumps(config)))
        texts = [embedding_text(r) for r in pending]
        if texts:
            encoded = model.model.tokenizer.encode_batch(texts)
            if any(len(item.ids) >= 512 for item in encoded):
                raise ValueError("A concept reaches the encoder's 512-token limit; shorten its text before embedding")
        vectors = model.embed(texts) if pending else []
        for row, vector in zip(pending, vectors, strict=True):
            v = normalized(vector)
            if len(v) != 384:
                raise ValueError("Unexpected embedding dimension")
            db.execute("""INSERT INTO concept_embedding VALUES (?,?,?,?) ON CONFLICT(concept_id,model_id)
                DO UPDATE SET content_sha256=excluded.content_sha256,vector=excluded.vector""",
                       (row["id"], mid, content_hash(row), struct.pack("<384f", *v)))
    return {"model": MODEL, "model_id": mid, "artifact_sha256": fingerprint, "embedded": len(pending), "dimensions": 384}


def search(db, query, limit=5):
    if limit < 1:
        raise ValueError("limit must be positive")
    model, mid, _, _ = load_model()
    rows = db.execute("""SELECT i.*,e.vector,e.content_sha256 FROM concept_embedding e JOIN concept i ON i.id=e.concept_id
                         WHERE e.model_id=? AND i.status='active'""", (mid,)).fetchall()
    if not rows:
        raise ValueError("No vectors for this model fingerprint; run embed first")
    q = normalized(next(model.query_embed(query)))
    scored = []
    for row in rows:
        if content_hash(row) == row["content_sha256"]:
            v = struct.unpack(f"<{len(q)}f", row["vector"])
            scored.append({"slug": row["slug"], "title": row["title"], "score": round(sum(a*b for a, b in zip(q, v)), 4)})
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    ingest_p = commands.add_parser("ingest")
    ingest_p.add_argument("file", type=Path)
    commands.add_parser("verify")
    formalization_p = commands.add_parser('formalization', help='Review implementing files and estimate their LOC shares')
    formalization_commands = formalization_p.add_subparsers(dest='formalization_command', required=True)
    report_p = formalization_commands.add_parser('report')
    report_p.add_argument('--concept')
    report_p.add_argument('--library')
    report_p.add_argument('--status', choices=('formalized', 'partial', 'inherited', 'not_formalized', 'unknown'))
    for name in ('library', 'file', 'set', 'measure'):
        sub = formalization_commands.add_parser(name)
        if name == 'set':
            sub.add_argument('concept')
            sub.add_argument('library')
        if name == 'measure':
            sub.add_argument('library')
            sub.add_argument('root', type=Path)
            sub.add_argument('--revision', default='HEAD', help='Count the reviewed commit; defaults to HEAD')
        else:
            sub.add_argument('item', help='JSON object')
        sub.add_argument('--reason', required=True)
    commands.add_parser("embed")
    export_p = commands.add_parser("export")
    export_p.add_argument("file", type=Path)
    search_p = commands.add_parser("search")
    search_p.add_argument("query")
    search_p.add_argument("--limit", type=int, default=5)
    show_p = commands.add_parser("show")
    show_p.add_argument("kind", choices=("concept", "source"))
    show_p.add_argument("slug")
    closure_p = commands.add_parser("prerequisites")
    closure_p.add_argument("source")
    closure_p.add_argument('--mode',choices=('statement','proof','all'),default='statement')
    cone_p = commands.add_parser("cone", help="Show every recorded prerequisite of a concept")
    cone_p.add_argument("concept")
    cone_p.add_argument('--mode',choices=('statement','proof','all'),default='statement')
    reduce_p = commands.add_parser("reduce", help="Audited transitive reduction, preserving reachability")
    reduce_p.add_argument("--concept", help="Restrict to this concept's entire prerequisite cone")
    reduce_p.add_argument("--dry-run", action="store_true")
    reduce_p.add_argument("--reason")
    revise_p = commands.add_parser("revise")
    revise_p.add_argument("concept")
    revise_p.add_argument("changes", help="JSON object")
    revise_p.add_argument("--reason", required=True)
    reorg_p = commands.add_parser("reorganize")
    reorg_p.add_argument("plan", type=Path)
    review_p = commands.add_parser("review", help="Record an explicit immediate-coverage judgment")
    review_p.add_argument("kind", choices=("concept", "source"))
    review_p.add_argument("slug")
    for flag in ("prerequisites", "statement-prerequisites", "proof-prerequisites", "requirements", "introductions", "citations"):
        review_p.add_argument("--" + flag, choices=("complete", "incomplete"))
    review_p.add_argument("--reason", required=True)
    link_p = commands.add_parser("link", help="Record a source's relationship to a concept")
    link_p.add_argument("source")
    link_p.add_argument("concept")
    link_p.add_argument("role", choices=("relies_on", "introduces", "explains", "discusses"))
    link_p.add_argument("--locator", required=True)
    link_p.add_argument("--note", default="")
    link_p.add_argument("--introduction-evidence", default="")
    link_p.add_argument("--reason", required=True)
    citation_p = commands.add_parser("citation", help="Capture, assess or resolve a bibliography entry")
    citation_commands = citation_p.add_subparsers(dest="citation_command", required=True)
    citation_add = citation_commands.add_parser("add")
    citation_add.add_argument("source")
    citation_add.add_argument("text")
    citation_add.add_argument("--label")
    citation_add.add_argument("--identifier", nargs=2, action="append", default=[], metavar=("SCHEME", "VALUE"))
    citation_add.add_argument("--cited-source")
    citation_add.add_argument("--pedagogically-necessary", choices=("yes", "no", "unknown"), default="unknown")
    citation_add.add_argument("--needed-material")
    citation_add.add_argument("--reason", required=True)
    citation_revise = citation_commands.add_parser("revise")
    citation_revise.add_argument("id", type=int)
    citation_revise.add_argument("changes", help="JSON object; identifiers replace manually supplied identifiers")
    citation_revise.add_argument("--reason", required=True)
    citation_resolve = citation_commands.add_parser("resolve")
    citation_resolve.add_argument("source")
    citation_resolve.add_argument("--reason", required=True)
    citation_delete = citation_commands.add_parser("delete")
    citation_delete.add_argument("id", type=int)
    citation_delete.add_argument("--reason", required=True)
    for command in ("relate", "unrelate"):
        related_p = commands.add_parser(command)
        related_p.add_argument("concept_a")
        related_p.add_argument("concept_b")
        related_p.add_argument("--reason", required=True)
        if command == "relate":
            related_p.add_argument("--source")
            related_p.add_argument("--locator")
    args = parser.parse_args()
    try:
        if hasattr(args, "reason") and args.reason is not None and not args.reason.strip():
            raise ValueError("A nonempty reason is required")
        with connect(args.db) as db:
            if args.command == "init":
                initialize(db)
                out = {"database": str(args.db), "initialized": True}
            elif args.command == "ingest":
                ingest(db, json.loads(args.file.read_text()))
                out = verify(db)
            elif args.command == "verify":
                out = verify(db)
            elif args.command == 'formalization':
                if args.formalization_command == 'report':
                    out = formalizations(db, args.concept, args.library, args.status)
                elif args.formalization_command == 'library':
                    out = save_library(db, json.loads(args.item), args.reason)
                elif args.formalization_command == 'file':
                    out = save_formalization_file(db, json.loads(args.item), args.reason)
                elif args.formalization_command == 'set':
                    out = save_formalization(db, args.concept, args.library, json.loads(args.item), args.reason)
                else:
                    out = measure_formalization_files(db, args.library, args.root, args.reason, args.revision)
            elif args.command == "export":
                args.file.write_text(json.dumps(snapshot(db), ensure_ascii=False, indent=2) + "\n")
                out = {"exported": str(args.file)}
            elif args.command == "embed":
                out = embed(db)
            elif args.command == "search":
                out = search(db, args.query, args.limit)
            elif args.command == "prerequisites":
                out = [dict(r) for r in closure(db, args.source,args.mode)]
            elif args.command == "cone":
                out = prerequisite_cone(db, args.concept,args.mode)
            elif args.command == "reduce":
                if args.dry_run:
                    out = reduction_plan(db, args.concept)
                elif args.reason:
                    out = reduce_dependencies(db, args.reason, args.concept)
                else:
                    raise ValueError("Applying a reduction requires --reason")
            elif args.command == "revise":
                revise(db, args.concept, json.loads(args.changes), args.reason)
                out = dict(lookup(db, "concept", args.concept))
            elif args.command == "reorganize":
                reorganize(db, json.loads(args.plan.read_text()))
                out = verify(db)
            elif args.command == "review":
                changes = {flag + "_complete": getattr(args, flag) == "complete"
                           for flag in ("prerequisites", "statement_prerequisites", "proof_prerequisites", "requirements", "introductions", "citations")
                           if getattr(args, flag) is not None}
                set_completeness(db, args.kind, args.slug, changes, args.reason)
                out = dict(lookup(db, args.kind, args.slug))
            elif args.command == "citation":
                if args.citation_command == "add":
                    with db:
                        item = {k: getattr(args, k) for k in ("source", "text", "label", "cited_source", "needed_material")}
                        item["identifiers"] = args.identifier
                        item["pedagogically_necessary"] = {"yes": True, "no": False, "unknown": None}[args.pedagogically_necessary]
                        out = citation_record(db, add_citation(db, item))
                        event(db, "add_citation", args.reason, {}, out)
                elif args.citation_command == "revise":
                    revise_citation(db, args.id, json.loads(args.changes), args.reason)
                    out = citation_record(db, args.id)
                elif args.citation_command == "resolve":
                    out = resolve_citations(db, args.source, args.reason)
                else:
                    with db:
                        before = citation_record(db, args.id)
                        db.execute("DELETE FROM citation WHERE id=?", (args.id,))
                        event(db, "delete_citation", args.reason, before, {})
                    out = {"deleted_citation": args.id}
            elif args.command == "link":
                with db:
                    item = {k: getattr(args, k) for k in ("source", "concept", "role", "locator", "note", "introduction_evidence")}
                    add_link(db, item)
                    event(db, "link", args.reason, {}, item)
                out = item
            elif args.command in ("relate", "unrelate"):
                with db:
                    a, b = sorted(lookup(db, "concept", getattr(args, k))["id"] for k in ("concept_a", "concept_b"))
                    before = [dict(r) for r in db.execute("SELECT * FROM concept_related WHERE concept_a_id=? AND concept_b_id=?", (a, b))]
                    if args.command == "relate":
                        item = dict(concept_a=args.concept_a, concept_b=args.concept_b,
                                    rationale=args.reason, source=args.source, locator=args.locator)
                        add_related(db, item)
                    else:
                        db.execute("DELETE FROM concept_related WHERE concept_a_id=? AND concept_b_id=?", (a, b))
                    out = related(db, args.concept_a)
                    event(db, args.command, args.reason, before, out)
            elif args.kind == "concept":
                row = lookup(db, "concept", args.slug)
                out = dict(row)
                out["prerequisites"] = [dict(r) for r in db.execute("""SELECT i.slug,i.title,d.basis,d.rationale,d.purpose FROM concept_dependency d
                    JOIN concept i ON i.id=d.prerequisite_id WHERE d.dependent_id=?""", (row["id"],))]
                out["occurrences"] = [dict(r) for r in db.execute("""SELECT s.slug,s.title,si.role,si.locator,si.note,si.introduction_evidence FROM source_concept si
                    JOIN source s ON s.id=si.source_id WHERE si.concept_id=?""", (row["id"],))]
                out["related"] = related(db, args.slug)
                out['formalizations'] = formalizations(db, concept=args.slug)
            else:
                row = lookup(db, "source", args.slug)
                out = dict(row)
                out["identifiers"] = [dict(r) for r in db.execute("SELECT scheme,value FROM source_identifier WHERE source_id=?", (row["id"],))]
                out["concepts"] = [dict(r) for r in db.execute("""SELECT i.slug,i.title,i.kind,i.description,si.role,si.locator,si.note,si.introduction_evidence FROM active_source_concept si
                    JOIN concept i ON i.id=si.concept_id WHERE si.source_id=?""", (row["id"],))]
                out["prerequisite_closure"] = [r["slug"] for r in closure(db, args.slug)]
                out["requirements"] = source_requirements(db, args.slug)
                for role in ("relies_on", "introduces"):
                    out[role] = sorted({c["slug"] for c in out["concepts"] if c["role"] == role})
                out["citations"] = [citation_record(db, r[0]) for r in db.execute(
                    "SELECT id FROM citation WHERE source_id=? ORDER BY id", (row["id"],))]
            print(json.dumps(out, ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error, OSError, KeyError) as ex:
        parser.exit(1, f"mathdb: {ex}\n")


if __name__ == "__main__":
    main()
