from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import mathdb as m
import mathdb_server as api
from test_mathdb import concept,edge


class PurposeTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)

    def tearDown(self):self.db.close()

    def seed(self):
        concepts=[concept(x) for x in ('statement','proof','proof-parent','theorem')]
        concepts[-1]['kind']='theorem'
        m.ingest(self.db,{'concepts':concepts,'dependencies':[
            {**edge('statement','theorem'),'purpose':'statement'},
            {**edge('proof','theorem'),'purpose':'proof'},
            edge('proof-parent','proof')]})

    def test_statement_expansion_records_proof_frontier_without_following_it(self):
        self.seed()
        for slug in ('statement','theorem'):
            m.set_completeness(self.db,'concept',slug,{'statement_prerequisites_complete':True},'Reviewed statement vocabulary')
        statement=m.prerequisite_cone(self.db,'theorem','statement')
        proof=m.prerequisite_cone(self.db,'theorem','proof')
        self.assertEqual({r['slug'] for r in statement['nodes']},{'theorem','statement'})
        self.assertTrue(statement['all_reviewed'])
        self.assertEqual(len(statement['proof_frontier']),1)
        self.assertEqual({r['slug'] for r in proof['nodes']},{'theorem','statement','proof','proof-parent'})
        self.assertFalse(proof['all_reviewed'])
        self.assertEqual(len(api.read_api(self.db,['concepts','theorem','cone'],{})['nodes']),2)
        self.assertEqual(len(api.read_api(self.db,['concepts','theorem','cone'],{'mode':['proof']})['nodes']),4)

    def test_reduction_cannot_remove_statement_dependency_via_proof_path(self):
        concepts=[concept('a'),{**concept('lemma'),'kind':'theorem'},{**concept('root'),'kind':'theorem'}]
        m.ingest(self.db,{'concepts':concepts,'dependencies':[
            {**edge('a','root'),'purpose':'statement'},
            {**edge('a','lemma'),'purpose':'proof'},
            {**edge('lemma','root'),'purpose':'statement'}]})
        self.assertFalse(m.reduction_plan(self.db)['removed'])
        self.assertIn('a',{r['slug'] for r in m.prerequisite_cone(self.db,'root','statement')['nodes']})

    def test_proof_shortcut_can_use_typed_mixed_path(self):
        m.ingest(self.db,{'concepts':[concept('a'),concept('b'),{**concept('root'),'kind':'theorem'}],
          'dependencies':[edge('a','b'),{**edge('b','root'),'purpose':'proof'},{**edge('a','root'),'purpose':'proof'}]})
        plan=m.reduce_dependencies(self.db,'Both modes retain their reachability')
        self.assertEqual(len(plan['removed']),1)
        self.assertEqual(plan['removed'][0]['preserved_mode'],'proof')
        self.assertEqual(plan['removed'][0]['path'],['a','b','root'])
        self.assertEqual(len(m.prerequisite_cone(self.db,'root','statement')['nodes']),1)

    def test_proof_shortcut_cannot_use_another_theorems_proof_input(self):
        m.ingest(self.db,{'concepts':[concept('a'),{**concept('lemma'),'kind':'theorem'},{**concept('root'),'kind':'theorem'}],
          'dependencies':[{**edge('a','lemma'),'purpose':'proof'},{**edge('lemma','root'),'purpose':'proof'},
                          {**edge('a','root'),'purpose':'proof'}]})
        self.assertFalse(m.reduction_plan(self.db)['removed'])

    def test_proof_edge_edits_preserve_statement_review(self):
        self.seed()
        m.set_completeness(self.db,'concept','theorem',{'statement_prerequisites_complete':True,'proof_prerequisites_complete':True},'Both immediate lists reviewed')
        with self.db:
            m.add_concept(self.db,concept('extra'))
            m.add_edge(self.db,{**edge('extra','theorem'),'purpose':'proof'})
        theorem=m.lookup(self.db,'concept','theorem')
        self.assertEqual(theorem['statement_prerequisites_complete'],1)
        self.assertEqual(theorem['proof_prerequisites_complete'],0)
        with self.db:self.db.execute("UPDATE concept_dependency SET purpose='statement' WHERE dependent_id=? AND prerequisite_id=?",(theorem['id'],m.lookup(self.db,'concept','extra')['id']))
        self.assertEqual(m.lookup(self.db,'concept','theorem')['statement_prerequisites_complete'],0)

    def test_unknown_purpose_cannot_be_certified_as_statement_coverage(self):
        m.ingest(self.db,{'concepts':[concept('a'),{**concept('t'),'kind':'theorem'}],'dependencies':[edge('a','t')]})
        self.assertEqual(self.db.execute('SELECT purpose FROM concept_dependency').fetchone()[0],'unclassified')
        with self.assertRaisesRegex(ValueError,'Classify'):
            m.set_completeness(self.db,'concept','t',{'statement_prerequisites_complete':True},'Pretend the old edge was reviewed')
        cone=m.prerequisite_cone(self.db,'t','statement')
        self.assertFalse(cone['all_reviewed']);self.assertEqual(len(cone['unclassified_dependencies']),1)

    def test_recording_proof_use_of_an_existing_statement_prerequisite_preserves_statement_review(self):
        self.seed()
        for purpose in ('both','statement'):
            m.set_completeness(self.db,'concept','theorem',{'statement_prerequisites_complete':True,'proof_prerequisites_complete':True},'The two immediate lists were reviewed')
            theorem=m.lookup(self.db,'concept','theorem')
            with self.db:self.db.execute('UPDATE concept_dependency SET purpose=? WHERE dependent_id=? AND prerequisite_id=?',
                                        (purpose,theorem['id'],m.lookup(self.db,'concept','statement')['id']))
            actual=m.lookup(self.db,'concept','theorem')
            self.assertEqual(actual['statement_prerequisites_complete'],1)
            self.assertEqual(actual['proof_prerequisites_complete'],0)

    def test_proof_roles_are_not_silently_attached_to_definitions(self):
        m.ingest(self.db,{'concepts':[concept('a'),concept('b')]})
        with self.assertRaisesRegex(ValueError,'theorem-shaped'):
            with self.db:m.add_edge(self.db,{**edge('a','b'),'purpose':'proof'})
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:self.db.execute('INSERT INTO concept_dependency(prerequisite_id,dependent_id,basis,rationale,purpose) VALUES (?,?,?,?,?)',
                (m.lookup(self.db,'concept','a')['id'],m.lookup(self.db,'concept','b')['id'],'both','Incorrect input','proof'))

    def test_migration_preserves_ids_vectors_and_unclassified_theorem_evidence(self):
        with closing(m.connect(':memory:')) as db:
            m.execute_schema(db,(Path(__file__).parent/'fixtures/schema_v7.sql').read_text())
            for slug,kind in [('a','definition'),('t','theorem')]:
                db.execute("INSERT INTO concept(id,slug,title,kind,description,field,prerequisites_complete) VALUES (?,?,?,?,?,?,1)",(slug,slug,slug,kind,'A test concept.','Test'))
            db.execute("INSERT INTO concept_dependency(id,prerequisite_id,dependent_id,basis,rationale) VALUES (42,'a','t','both','Original evidence')")
            db.execute("INSERT INTO embedding_model VALUES ('model','Test model','hash',1,'{}')")
            db.execute("INSERT INTO concept_embedding VALUES ('a','model','original-hash',?)",(b'\x00\x00\x00\x00',))
            db.commit()
            edges=[tuple(r) for r in db.execute('SELECT id,prerequisite_id,dependent_id,rationale FROM concept_dependency')]
            vectors=[tuple(r) for r in db.execute('SELECT * FROM concept_embedding')]
            m.initialize(db)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],10)
            self.assertEqual(edges,[tuple(r) for r in db.execute('SELECT id,prerequisite_id,dependent_id,rationale FROM concept_dependency')])
            self.assertEqual(vectors,[tuple(r) for r in db.execute('SELECT * FROM concept_embedding')])
            self.assertTrue(db.execute("SELECT 1 FROM concept_dependency WHERE purpose='unclassified'").fetchone())
            self.assertEqual(m.lookup(db,'concept','t')['statement_prerequisites_complete'],0)
            self.assertEqual(m.lookup(db,'concept','a')['statement_prerequisites_complete'],1)
