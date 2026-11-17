import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import mathdb as m


def concept(slug):
    return dict(slug=slug, title=slug.title(), kind="definition",
                description=f"The mathematical construction {slug}.", field="Test")


def source(slug="paper"):
    return dict(slug=slug, title=slug, authors=["Test"], year=2026, field="Test", status="reviewed",
                coverage="Test fixture", summary="Test", dependency_review="Test",
                identifiers=[["doi", f"10.1234/{slug}"]])


def edge(p, d):
    return dict(prerequisite=p, dependent=d, basis="both", rationale="Required in this account.")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = m.connect(Path(self.temp.name) / "test.sqlite")
        m.initialize(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def seed(self, slugs=("a", "b", "c"), edges=()):
        m.ingest(self.db, dict(sources=[source()], concepts=[concept(x) for x in slugs], dependencies=list(edges)))

    def test_identifier_aliases_and_collisions(self):
        self.seed()
        sid = m.lookup(self.db, "source", "paper")["id"]
        m.add_identifier(self.db, sid, "doi", "https://doi.org/10.1234/PAPER")
        self.assertEqual(self.db.execute("SELECT count(*) FROM source_identifier").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "another source"):
            m.ingest(self.db, dict(sources=[{**source("other"), "identifiers": [["doi", "DOI:10.1234/paper"]]}]))
        self.assertEqual(self.db.execute("SELECT count(*) FROM source").fetchone()[0], 1)

    def test_source_author_string_cannot_break_browsing_or_partially_import_a_batch(self):
        invalid={**source('bad'),'authors':'Author One; Author Two'}
        with self.assertRaisesRegex(ValueError,'authors must be an array'):
            m.ingest(self.db,{'sources':[source('valid'),invalid]})
        self.assertEqual(self.db.execute('SELECT count(*) FROM source').fetchone()[0],0)

    def test_arxiv_versions_and_isbn_equivalence(self):
        self.assertEqual(m.normalize_identifier("arxiv", "https://arxiv.org/pdf/1002.3496v1.pdf"), ("arxiv", "1002.3496"))
        self.assertEqual(m.normalize_identifier("isbn", "3-540-06585-7"), ("isbn", "9783540065852"))
        with self.assertRaisesRegex(ValueError, "checksum"):
            m.normalize_identifier("isbn", "9783540065853")

    def test_insert_cycle_rejected_and_batch_rolls_back(self):
        self.seed(edges=[edge("a", "b"), edge("b", "c")])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cycle"):
            m.ingest(self.db, dict(concepts=[concept("new")], dependencies=[edge("c", "a")]))
        self.assertIsNone(self.db.execute("SELECT 1 FROM concept WHERE slug='new'").fetchone())
        self.assertEqual(m.verify(self.db)["concept_dependencies"], 2)

    def test_sql_update_cannot_bypass_dag(self):
        self.seed(edges=[edge("a", "b"), edge("b", "c")])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cycle"):
            with self.db:
                self.db.execute("UPDATE concept_dependency SET prerequisite_id=? WHERE dependent_id=?",
                                (m.lookup(self.db, "concept", "c")["id"], m.lookup(self.db, "concept", "b")["id"]))
        self.assertTrue(m.verify(self.db)["dag"])

    def test_paragraph_and_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            m.ingest(self.db, dict(concepts=[{**concept("a"), "description": "First paragraph.\nSecond paragraph."}]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO concept_alias VALUES ('nonexistent','alias')")

    def test_prerequisites_include_dependencies_of_new_constructions(self):
        self.seed(edges=[edge("a", "b"), edge("b", "c")])
        with self.db:
            m.add_link(self.db, dict(source="paper", concept="c", role="proves", locator="§1"))
        self.assertEqual({r["slug"] for r in m.closure(self.db, "paper")}, set())
        with self.db:
            m.add_link(self.db, dict(source="paper", concept="b", role="relies_on", locator="Proof input"))
        self.assertEqual({r["slug"] for r in m.closure(self.db, "paper")}, {"a", "b"})

    def test_revision_invalidates_vectors_and_preserves_identity(self):
        self.seed()
        before = dict(m.lookup(self.db, "concept", "a"))
        with self.db:
            self.db.execute("INSERT INTO embedding_model VALUES ('test','test','hash',1,'{}')")
            self.db.execute("INSERT INTO concept_embedding VALUES (?,'test',?,?)", (before["id"], m.content_hash(before), b'\x00\x00\x80\x3f'))
            m.add_link(self.db, dict(source="paper", concept="a", role="uses", locator="§1"))
        m.revise(self.db, "a", {"title": "A better label"}, "Calibrate vocabulary")
        after = m.lookup(self.db, "concept", "a")
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["revision"], 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM concept_embedding").fetchone()[0], 0)
        self.assertEqual(m.lookup(self.db, "source", "paper")["status"], "draft")
        self.assertEqual(self.db.execute("SELECT alias FROM concept_alias").fetchone()[0], "A")

    def split_plan(self):
        rows = [dict(r) for r in self.db.execute("SELECT * FROM concept_dependency ORDER BY id")]
        link = self.db.execute("SELECT id FROM source_concept").fetchone()[0]
        return dict(operation="split", reason="Distinguish the two constructions", **{"from": ["b"]},
                    to=[concept("b1"), concept("b2")],
                    edge_routes={str(rows[0]["id"]): {"replacements": [edge("a", "b1")]},
                                 str(rows[1]["id"]): {"replacements": [edge("b2", "c")]}},
                    link_routes={str(link): {"replacements": ["b1", "b2"]}},
                    new_dependencies=[edge("b1", "b2")])

    def split_seed(self):
        self.seed(edges=[edge("a", "b"), edge("b", "c")])
        with self.db:
            m.add_link(self.db, dict(source="paper", concept="b", role="uses", locator="§1", note="Original evidence"))

    def test_split_requires_complete_routes(self):
        self.split_seed()
        plan = self.split_plan()
        plan["edge_routes"].pop(next(iter(plan["edge_routes"])))
        with self.assertRaisesRegex(ValueError, "account for exactly"):
            m.reorganize(self.db, plan)
        self.assertEqual(m.lookup(self.db, "concept", "b")["status"], "active")
        self.assertEqual(self.db.execute("SELECT count(*) FROM concept").fetchone()[0], 3)

    def test_split_preserves_evidence_and_marks_old_concept(self):
        self.split_seed()
        m.reorganize(self.db, self.split_plan())
        self.assertEqual(m.lookup(self.db, "concept", "b")["status"], "superseded")
        self.assertEqual(self.db.execute("SELECT count(*) FROM source_concept").fetchone()[0], 3)
        self.assertEqual(self.db.execute("SELECT count(*) FROM active_source_concept").fetchone()[0], 2)
        self.assertEqual(m.verify(self.db)["active_concepts"], 4)
        self.assertEqual(self.db.execute("SELECT operation FROM curation_event ORDER BY id DESC").fetchone()[0], "split")

    def test_reorganization_cycle_is_atomic(self):
        self.split_seed()
        plan = self.split_plan()
        plan["new_dependencies"] = [edge("b1", "b2"), edge("c", "b1")]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cycle"):
            m.reorganize(self.db, plan)
        self.assertEqual(m.verify(self.db)["active_concepts"], 3)
        self.assertEqual(m.lookup(self.db, "concept", "b")["status"], "active")
        self.assertEqual(self.db.execute("SELECT count(*) FROM curation_event").fetchone()[0], 1)

    def test_merge_with_explicit_internal_edge_removal(self):
        self.seed(slugs=("a", "b"), edges=[edge("a", "b")])
        eid = self.db.execute("SELECT id FROM concept_dependency").fetchone()[0]
        m.reorganize(self.db, dict(operation="merge", reason="Same concept at this granularity",
                                  **{"from": ["a", "b"]}, to=[concept("ab")],
                                  edge_routes={str(eid): {"replacements": [], "reason": "Internal distinction removed"}}, link_routes={}))
        self.assertEqual(m.verify(self.db)["active_concepts"], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM concept WHERE status='superseded'").fetchone()[0], 2)

    def test_strict_source_edge_requires_justification(self):
        m.ingest(self.db, dict(sources=[source("one"), source("two")]))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("""INSERT INTO source_relation(dependent_id,prerequisite_id,kind,fact,locator,rationale,general_availability)
                               VALUES (?,?,'strict_dependency','','§2','Citation alone','')""",
                            (m.lookup(self.db, "source", "one")["id"], m.lookup(self.db, "source", "two")["id"]))

    def test_complete_real_sample(self):
        payload = json.loads((m.ROOT / "data/seed.json").read_text())
        m.ingest(self.db, payload)
        stats = m.verify(self.db)
        self.assertEqual(stats["ingested_sources"], 7)
        self.assertGreater(stats["active_concepts"], 50)
        # Every root explicitly marks the current prerequisite frontier.
        roots = self.db.execute("""SELECT i.slug,i.boundary FROM concept i WHERE NOT EXISTS
            (SELECT 1 FROM concept_dependency d WHERE d.dependent_id=i.id)""").fetchall()
        self.assertTrue(roots)
        self.assertTrue(all(r["boundary"] for r in roots), roots)
        # No duplicate identifier can accidentally create a second work record.
        before = stats.copy()
        with self.assertRaises(sqlite3.IntegrityError):
            m.ingest(self.db, copy.deepcopy(payload))
        self.assertEqual(m.verify(self.db), before)

    def test_concepts_require_valid_type(self):
        for changes in ({"kind": "method"},):
            with self.assertRaises(sqlite3.IntegrityError):
                m.ingest(self.db, dict(concepts=[{**concept("a"), **changes}]))
        self.assertEqual(self.db.execute("SELECT count(*) FROM concept").fetchone()[0], 0)

    def test_old_ingestion_format_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "v7 concept format"):
            m.ingest(self.db, {"ideas": []})

    def test_description_change_invalidates_vector(self):
        self.seed()
        before = dict(m.lookup(self.db, "concept", "a"))
        with self.db:
            self.db.execute("INSERT INTO embedding_model VALUES ('test','test','hash',1,'{}')")
            self.db.execute("INSERT INTO concept_embedding VALUES (?,'test',?,?)", (before["id"], m.content_hash(before), b'\x00\x00\x80\x3f'))
        m.revise(self.db, "a", {"description": "A corrected short definition."}, "Disambiguate the definition")
        self.assertEqual(self.db.execute("SELECT count(*) FROM concept_embedding").fetchone()[0], 0)

    def test_named_theorems_are_single_records(self):
        payload = json.loads((m.ROOT / "data/seed.json").read_text())
        m.ingest(self.db, payload)
        for slug in ("finite-ramsey", "erdos-szekeres-monotone", "erdos-szekeres-convex", "erdos-szekeres-cups-caps", "sperner-lemma"):
            row = m.lookup(self.db, "concept", slug)
            self.assertEqual(row["kind"], "theorem")
            self.assertTrue(row["description"].strip())
        slugs = {c["slug"] for c in payload["concepts"]}
        self.assertFalse(slugs & {"ramsey-recursion", "geometric-coloring", "convex-extraction", "pairing", "etemadi-method"})

    def test_concepts_have_no_scope_field(self):
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(concept)")}
        self.assertNotIn("scope", columns)
        with self.assertRaisesRegex(ValueError, "removed scope field"):
            m.ingest(self.db, {"concepts": [{**concept("a"), "scope": "Not accepted"}]})

    def test_author_papers_keep_the_essential_distinctions(self):
        payload = json.loads((m.ROOT / "data/seed.json").read_text())
        m.ingest(self.db, payload)
        statement = m.lookup(self.db, "concept", "g2-braid-surjectivity")["description"]
        self.assertIn("ℂ(q)", statement)
        self.assertNotEqual(m.lookup(self.db, "concept", "rational-form")["id"],
                            m.lookup(self.db, "concept", "complete-rational-form")["id"])
        self.assertIn("complete rational form", m.lookup(self.db, "concept", "noncyclotomic-haagerup")["description"])

    def test_one_layer_targets_only_frozen_concepts(self):
        report = json.loads((m.ROOT / "data/one-layer-review.json").read_text())
        batch = json.loads((m.ROOT / "data/one-layer-batch.json").read_text())
        seeds = set(report["seed_concepts"])
        new = {c["slug"] for c in batch["concepts"]}
        self.assertFalse(seeds & new)
        self.assertEqual({r["concept"] for r in report["reviews"]}, seeds)
        self.assertTrue(all(e["dependent"] in seeds for e in batch["dependencies"]))
        self.assertTrue(all(c["boundary"] for c in batch["concepts"]))
        self.assertTrue(all(e["dependent"] not in new for e in batch["dependencies"]))
        self.assertEqual(len(new), len(report["new_to_database"]))
        self.assertEqual(batch["source_relations"], [])  # Learning links are not strict paper dependencies.

    def test_local_expression_is_not_an_active_concept(self):
        payload = json.loads((m.ROOT / "data/seed.json").read_text())
        slugs = {c["slug"] for c in payload["concepts"]}
        self.assertFalse(slugs & {"normalized-third-twisted-moment", "normalized-moment-invariance"})
        fields_note = next(l["note"] for l in payload["source_concepts"] if l["concept"] == "haagerup-fields")
        self.assertIn("Definition 4.2", fields_note)


if __name__ == "__main__":
    unittest.main()
