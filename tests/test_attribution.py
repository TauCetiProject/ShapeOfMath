from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest

import mathdb as m
import mathdb_server as api
from test_mathdb import concept,source,edge


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)
        m.ingest(self.db,dict(sources=[source()],concepts=[concept('a'),concept('b')]))

    def tearDown(self):self.db.close()

    def test_introduction_requires_evidence_and_legacy_proofs_are_explanations(self):
        with self.assertRaisesRegex(ValueError,'introduction_evidence'):
            with self.db:m.add_link(self.db,dict(source='paper',concept='a',role='introduces',locator='Definition 1'))
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='a',role='defines',locator='Definition 1'))
            m.add_link(self.db,dict(source='paper',concept='a',role='proves',locator='Theorem 2'))
        self.assertEqual({r[0] for r in self.db.execute('SELECT role FROM source_concept')},{'explains'})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:self.db.execute("UPDATE source_concept SET role='introduces'")
        with self.db:m.add_link(self.db,dict(source='paper',concept='a',role='introduces',locator='Original construction',introduction_evidence='Checked the original construction and its predecessor credits.'))
        self.assertEqual(self.db.execute("SELECT count(*) FROM source_concept WHERE role='introduces'").fetchone()[0],1)

    def test_source_frontier_preserves_occurrences_and_inherited_knowledge(self):
        m.ingest(self.db,dict(concepts=[concept('c'),concept('conclusion')],dependencies=[edge('a','b'),edge('b','c'),edge('a','conclusion')]))
        with self.db:
            for slug in ('a','b','c'):m.add_link(self.db,dict(source='paper',concept=slug,role='relies_on',locator='Input '+slug))
            m.add_link(self.db,dict(source='paper',concept='conclusion',role='introduces',locator='Theorem 1',introduction_evidence='Synthetic new theorem.'))
        result=m.source_requirements(self.db,'paper')
        self.assertEqual([r['slug'] for r in result['direct']],['c'])
        self.assertEqual({r['slug'] for r in result['inherited']},{'a','b'})
        self.assertTrue(all(r['via']==['c'] for r in result['inherited']))
        self.assertEqual(self.db.execute("SELECT count(*) FROM source_concept WHERE role='relies_on'").fetchone()[0],3)
        self.assertNotIn('conclusion',{r['slug'] for r in m.closure(self.db,'paper')})

    def test_an_explanation_or_origin_does_not_inherit_a_later_proofs_inputs(self):
        m.ingest(self.db,dict(dependencies=[edge('a','b')]))
        with self.db:
            m.add_link(self.db,dict(source='paper',concept='b',role='introduces',locator='Theorem 1',introduction_evidence='Synthetic original theorem.'))
            m.add_link(self.db,dict(source='paper',concept='a',role='explains',locator='Later appendix'))
        self.assertEqual(m.closure(self.db,'paper'),[])
        self.assertEqual(m.source_requirements(self.db,'paper'),{'direct':[],'inherited':[]})

    def test_reorganization_requires_a_fresh_origin_judgment(self):
        with self.db:m.add_link(self.db,dict(source='paper',concept='b',role='introduces',locator='Definition 1',introduction_evidence='Original b.'))
        ident=self.db.execute('SELECT id FROM source_concept').fetchone()[0]
        plan=dict(operation='split',reason='Distinguish meanings',**{'from':['b']},to=[concept('b1'),concept('b2')],edge_routes={},related_routes={},link_routes={str(ident):{'replacements':['b1','b2']}})
        with self.assertRaisesRegex(ValueError,'Route an introduction explicitly'):m.reorganize(self.db,plan)
        self.assertEqual(m.lookup(self.db,'concept','b')['status'],'active')
        plan['link_routes'][str(ident)]['replacements']=[dict(concept='b1',role='explains'),dict(concept='b2',role='introduces',introduction_evidence='The checked passage introduces b2 only.')]
        m.reorganize(self.db,plan)
        roles={r['slug']:r['role'] for r in self.db.execute('SELECT c.slug,l.role FROM active_source_concept l JOIN concept c ON c.id=l.concept_id')}
        self.assertEqual(roles,{'b1':'explains','b2':'introduces'})
        self.assertTrue(m.verify(self.db)['dag'])

    def test_api_rejects_unsupported_priority_promotions(self):
        with self.assertRaisesRegex(ValueError,'introduction_evidence'):
            with self.db:api.write_api(self.db,'POST',['source-concepts'],dict(source='paper',concept='a',role='introduces',locator='Theorem 1',reason='A later proof'))
        with self.db:
            result=api.write_api(self.db,'POST',['source-concepts'],dict(source='paper',concept='a',role='explains',locator='Theorem 1',reason='A later proof'))
        with self.assertRaisesRegex(ValueError,'introduction_evidence'):
            with self.db:api.write_api(self.db,'PATCH',['source-concepts',str(result['id'])],dict(role='introduces',reason='A new label'))

    def test_v6_migration_keeps_math_and_history_but_resets_ambiguous_origin_reviews(self):
        with closing(m.connect(':memory:')) as db:
            db.executescript((Path(__file__).parent/'fixtures/schema_v6.sql').read_text())
            with db:
                db.execute("INSERT INTO source(id,slug,title,authors,field,status,coverage,summary,dependency_review) VALUES ('s','paper','Paper','[]','Test','reviewed','','','')")
                db.execute("INSERT INTO source_identifier VALUES ('doi','10.1234/paper','s')")
                db.execute("INSERT INTO concept(id,slug,title,kind,description,field,prerequisites_complete) VALUES ('a','a','A','definition','Definition.','Test',1)")
                db.execute("INSERT INTO source_concept VALUES (42,'s','a','introduces','Definition 1','A useful exposition.')")
                db.execute('UPDATE source SET requirements_complete=1,introductions_complete=1,citations_complete=1')
                db.execute("INSERT INTO embedding_model VALUES ('test','test','hash',1,'{}')")
                db.execute("INSERT INTO concept_embedding VALUES ('a','test',?,?)",(m.content_hash(m.lookup(db,'concept','a')),b'\x00\x00\x80\x3f'))
                m.event(db,'original','Original event',{}, {})
            m.initialize(db)
            row=db.execute('SELECT * FROM source_concept').fetchone()
            self.assertEqual((row['id'],row['role'],row['note']),(42,'explains','A useful exposition.'))
            self.assertEqual(m.lookup(db,'concept','a')['prerequisites_complete'],1)
            s=m.lookup(db,'source','paper')
            self.assertEqual((s['requirements_complete'],s['introductions_complete'],s['citations_complete']),(1,0,1))
            self.assertEqual(m.verify(db)['vectors'],1)
            self.assertEqual(db.execute('SELECT count(*) FROM curation_event').fetchone()[0],5)
            m.initialize(db);self.assertEqual(db.execute('SELECT count(*) FROM curation_event').fetchone()[0],5)

    def test_g2_regression_in_reproducible_seed(self):
        with closing(m.connect(':memory:')) as db:
            m.initialize(db);payload=json.loads((m.ROOT/'data/seed.json').read_text());m.ingest(db,payload)
            rows=db.execute("SELECT l.*,s.slug AS source,c.slug AS concept FROM active_source_concept l JOIN source s ON s.id=l.source_id JOIN concept c ON c.id=l.concept_id").fetchall()
            origins={(r['source'],r['concept']) for r in rows if r['role']=='introduces'}
            self.assertFalse(any(s=='morrison-g2-2011' for s,c in origins))
            self.assertIn(('kuperberg-1996','g2-spider'),origins)
            self.assertIn(('kuperberg-1994','g2-web'),origins)
            self.assertIn(('lehrer-zhang-2006','g2-braid-surjectivity'),origins)
            self.assertIn(('morrison-snyder-2012','haagerup-fields'),origins)
            books={'stacks-project','egno-tensor-categories-2015','durrett-probability-2019','lebl-basic-analysis-2026','morrison-jones-wenzl-2015'}
            self.assertFalse(any(s in books for s,c in origins))
            self.assertTrue(all(r['introduction_evidence'].strip() for r in rows if r['role']=='introduces'))
            frontier=m.source_requirements(db,'morrison-g2-2011')
            direct={r['slug'] for r in frontier['direct']}
            self.assertIn('g2-web-basis',direct)
            self.assertFalse({'g2-spider','g2-web','nonelliptic-g2-web'}&direct)
            inherited={r['slug']:r for r in frontier['inherited']}
            self.assertTrue({'g2-spider','g2-web','nonelliptic-g2-web'}<=set(inherited))
            self.assertIn('g2-web-basis',inherited['g2-web']['via'])
            self.assertNotIn('euler-measure',{r['slug'] for r in m.closure(db,'lehrer-zhang-2006')})
            note=next(r['note'] for r in rows if r['source']=='morrison-snyder-2012' and r['concept']=='haagerup-fields')
            self.assertIn('Definition 4.2',note)
