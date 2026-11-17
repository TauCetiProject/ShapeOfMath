import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import mathdb as m
from test_mathdb import concept, source, edge


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.db = m.connect(':memory:')
        m.initialize(self.db)
        m.ingest(self.db, dict(sources=[source()], concepts=[concept(x) for x in ('a','b','c')],
                               dependencies=[edge('a','b'), edge('b','c')]))

    def tearDown(self):
        self.db.close()

    def review(self, kind, slug, **changes):
        m.set_completeness(self.db, kind, slug, changes, 'Reviewed immediate inputs')

    def test_local_flags_and_independent_source_judgments(self):
        self.review('concept', 'b', prerequisites_complete=True)
        self.assertEqual(m.lookup(self.db,'concept','a')['prerequisites_complete'], 0)
        self.assertEqual(m.lookup(self.db,'concept','b')['prerequisites_complete'], 1)
        self.review('source','paper', requirements_complete=True)
        self.assertEqual(m.lookup(self.db,'source','paper')['introductions_complete'], 0)
        self.review('source','paper', introductions_complete=True)
        self.assertEqual(m.lookup(self.db,'source','paper')['requirements_complete'], 1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM curation_event WHERE operation LIKE 'review_%'").fetchone()[0],3)
        with self.assertRaises(ValueError):
            m.set_completeness(self.db,'concept','b',{'requirements_complete':True},'Invalid flag')
        with self.assertRaises(ValueError):
            m.set_completeness(self.db,'concept','b',{'prerequisites_complete':True},' ')

    def test_edge_change_invalidates_only_its_dependent(self):
        for slug in ('a','b','c'):
            self.review('concept',slug,prerequisites_complete=True)
        self.review('source','paper',requirements_complete=True,introductions_complete=True)
        with self.db:
            self.db.execute('DELETE FROM concept_dependency WHERE dependent_id=?', (m.lookup(self.db,'concept','b')['id'],))
        self.assertEqual([m.lookup(self.db,'concept',s)['prerequisites_complete'] for s in ('a','b','c')],[1,0,1])
        self.assertEqual(m.lookup(self.db,'source','paper')['requirements_complete'],1)

    def test_source_roles_invalidate_independently(self):
        self.review('source','paper',requirements_complete=True,introductions_complete=True)
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='a',role='uses',locator='§1'))
        row=m.lookup(self.db,'source','paper')
        self.assertEqual((row['requirements_complete'],row['introductions_complete']),(0,1))
        self.assertEqual(self.db.execute('SELECT role FROM source_concept').fetchone()[0],'relies_on')
        self.review('source','paper',requirements_complete=True)
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='b',role='discusses',locator='§2'))
            self.db.execute("UPDATE source_concept SET note='Better locator explanation'")
        self.assertEqual(m.lookup(self.db,'source','paper')['requirements_complete'],1)
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='b',role='introduces',introduction_evidence='Synthetic fixture: the source establishes this new concept.',locator='§2'))
        row=m.lookup(self.db,'source','paper')
        self.assertEqual((row['requirements_complete'],row['introductions_complete']),(1,0))
        self.review('source','paper',introductions_complete=True)
        with self.db:
            self.db.execute("DELETE FROM source_concept WHERE role='introduces'")
        self.assertEqual(m.lookup(self.db,'source','paper')['introductions_complete'],0)

    def test_concept_edit_invalidates_local_reviews_and_source_roles(self):
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='a',role='relies_on',locator='§1'))
        for slug in ('a','b','c'):
            self.review('concept',slug,prerequisites_complete=True)
        self.review('source','paper',requirements_complete=True,introductions_complete=True)
        m.revise(self.db,'a',{'description':'A revised definition.'},'Clarify convention')
        self.assertEqual([m.lookup(self.db,'concept',s)['prerequisites_complete'] for s in ('a','b','c')],[0,0,1])
        row=m.lookup(self.db,'source','paper')
        self.assertEqual((row['requirements_complete'],row['introductions_complete']),(0,1))

    def test_related_is_symmetric_and_outside_dag(self):
        self.review('concept','a',prerequisites_complete=True)
        with self.db:
            m.add_related(self.db,dict(concept_a='c',concept_b='a',rationale='Parallel constructions.'))
        self.assertEqual(m.related(self.db,'a')[0]['slug'],'c')
        self.assertEqual(m.related(self.db,'c')[0]['slug'],'a')
        self.assertTrue(m.verify(self.db)['dag'])
        self.assertEqual(m.lookup(self.db,'concept','a')['prerequisites_complete'],1)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                m.add_related(self.db,dict(concept_a='a',concept_b='c',rationale='Duplicate reversal.'))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                m.add_related(self.db,dict(concept_a='a',concept_b='a',rationale='Self link.'))
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='a',role='relies_on',locator='§1'))
        self.assertEqual([r['slug'] for r in m.closure(self.db,'paper')],['a'])

    def test_split_requires_routing_related_links(self):
        with self.db:
            m.add_related(self.db,dict(concept_a='a',concept_b='c',rationale='Related.'))
        relation=self.db.execute('SELECT id FROM concept_related').fetchone()[0]
        dependency=self.db.execute('SELECT id FROM concept_dependency WHERE prerequisite_id=?',(m.lookup(self.db,'concept','a')['id'],)).fetchone()[0]
        plan=dict(operation='split',reason='Distinguish meanings', **{'from':['a']},
                  to=[concept('a1'),concept('a2')],link_routes={},
                  edge_routes={str(dependency):{'replacements':[edge('a1','b')]}})
        with self.assertRaisesRegex(ValueError,'related_routes'):
            m.reorganize(self.db,plan)
        self.assertEqual(m.lookup(self.db,'concept','a')['status'],'active')
        plan['related_routes']={str(relation):{'replacements':[dict(concept_a='c',concept_b='a2',rationale='Related to this meaning.')]}}
        m.reorganize(self.db,plan)
        self.assertEqual(m.related(self.db,'c')[0]['slug'],'a2')
        self.assertTrue(m.verify(self.db)['dag'])

    def test_initialize_is_idempotent_and_source_artifact_invalidates_reviews(self):
        self.review('concept','a',prerequisites_complete=True)
        self.review('source','paper',requirements_complete=True,introductions_complete=True)
        m.initialize(self.db)
        self.assertEqual(m.lookup(self.db,'concept','a')['prerequisites_complete'],1)
        self.assertEqual(m.lookup(self.db,'source','paper')['requirements_complete'],1)
        with self.db:
            self.db.execute("INSERT INTO source_artifact(source_id,url,accessed_at,note) VALUES (?,'https://example.com','2026-11-12','New snapshot')",(m.lookup(self.db,'source','paper')['id'],))
        row=m.lookup(self.db,'source','paper')
        self.assertEqual((row['requirements_complete'],row['introductions_complete']),(0,0))

    def test_v3_migration_preserves_identity_history_and_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=m.connect(Path(tmp)/'old.sqlite')
            try:
                db.executescript((Path(__file__).parent/'fixtures/schema_v3.sql').read_text())
                cid=m.stable_id('concept','old'); sid=m.stable_id('source','paper')
                with db:
                    db.execute("INSERT INTO concept(id,slug,title,kind,description,field) VALUES (?,'old','Old','definition','Definition.','Test')",(cid,))
                    db.execute("INSERT INTO source VALUES (?,'paper','Paper','[]',2026,'Test','draft','Test','Test','Test')",(sid,))
                    db.execute("INSERT INTO source_identifier VALUES ('doi','10.1234/paper',?)",(sid,))
                    db.execute("INSERT INTO source_concept VALUES (42,?,?,'uses','§1','Original note')",(sid,cid))
                    db.execute("INSERT INTO embedding_model VALUES ('test','test','hash',1,'{}')")
                    row=m.lookup(db,'concept','old')
                    db.execute("INSERT INTO concept_embedding VALUES (?,'test',?,?)",(cid,m.content_hash(row),b'\x00\x00\x80\x3f'))
                    m.event(db,'original','Original history',{}, {'id':cid})
                m.initialize(db)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],10)
                self.assertEqual(m.lookup(db,'concept','old')['id'],cid)
                self.assertEqual(m.lookup(db,'concept','old')['prerequisites_complete'],0)
                row=db.execute('SELECT * FROM source_concept').fetchone()
                self.assertEqual((row['id'],row['role'],row['note']),(42,'relies_on','Original note'))
                self.assertEqual(db.execute('SELECT vector FROM concept_embedding').fetchone()[0],b'\x00\x00\x80\x3f')
                self.assertEqual(db.execute('SELECT count(*) FROM curation_event').fetchone()[0],5)
                self.assertEqual(m.verify(db)['vectors'],1)
                m.initialize(db)
                self.assertEqual(db.execute('SELECT count(*) FROM curation_event').fetchone()[0],5)
            finally:
                db.close()
