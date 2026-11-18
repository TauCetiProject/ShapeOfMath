from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mathdb as m
import curation_plans as plans
from test_mathdb import concept,source,edge


class TaskImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'math.sqlite'
        with closing(m.connect(self.db)) as db:
            m.initialize(db);m.ingest(db,{'concepts':[concept('root'),concept('parent')]})
        self.task=self.root/'task'
        plans.prepare_task('cone',{'task_id':'new-cone-task','roots':['root']},self.task,self.db)

    def write(self,result=None,task=None):
        result=result if result is not None else {
            'changes':{'dependencies':[{**edge('parent','root'),'purpose':'statement'}]},
            'concept_reviews':[{'slug':'root','statement_prerequisites_complete':True,'reason':'Synthetic full immediate-list review.'}]}
        ((task or self.task)/'output/result.json').write_text(json.dumps(result))

    def snapshot(self):
        with closing(m.connect(self.db)) as db:return m.snapshot(db)

    def test_import_is_idempotent_and_dry_run_does_not_mutate(self):
        self.write();before=self.snapshot()
        self.assertTrue(plans.import_result(self.task,self.db,dry_run=True)['changed'])
        self.assertEqual(before,self.snapshot());self.assertFalse((self.task/'output/import.json').exists())
        self.assertTrue(plans.import_result(self.task,self.db)['changed'])
        with closing(m.connect(self.db)) as db:
            self.assertTrue(m.lookup(db,'concept','root')['statement_prerequisites_complete'])
            self.assertEqual(db.execute("SELECT count(*) FROM curation_event WHERE operation='curated_task_plan'").fetchone()[0],1)
        before=self.snapshot();self.assertFalse(plans.import_result(self.task,self.db)['changed']);self.assertEqual(before,self.snapshot())
        self.assertTrue((self.task/'output/import.json').exists())

    def test_changed_result_after_import_rejected(self):
        self.write();plans.import_result(self.task,self.db)
        self.write({'changes':{'concepts':[concept('other')]}})
        with self.assertRaisesRegex(ValueError,'already imported'):plans.import_result(self.task,self.db)

    def test_reused_source_identifier_not_dropped(self):
        with closing(m.connect(self.db)) as db:m.ingest(db,{'sources':[source('canonical')]})
        other=self.root/'source-task'
        plans.prepare_task('source',{'task_id':'source-2027','source_identifiers':[['doi','10.1234/paper']]},other,self.db)
        candidate=source('renamed');candidate['identifiers']=source('canonical')['identifiers']+[['doi','10.1234/extra']]
        self.write({'changes':{'sources':[candidate]}},other);plans.import_result(other,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM source').fetchone()[0],1)
            self.assertIsNotNone(db.execute("SELECT 1 FROM source_identifier WHERE value='10.1234/extra'").fetchone())

    def test_same_slug_with_different_text_needs_same_as(self):
        changed=concept('parent');changed['description']='A different synthetic paragraph.'
        self.write({'changes':{'concepts':[changed],'dependencies':[{**edge('parent','root'),'purpose':'statement'}]}})
        with self.assertRaisesRegex(ValueError,'same_as'):plans.import_result(self.task,self.db,dry_run=True)
        self.write({'changes':{'concepts':[changed],'dependencies':[{**edge('parent','root'),'purpose':'statement'}]},
                    'same_as':{'parent':{'target':'parent','reason':'Same meaning, live wording kept.'}}})
        plans.import_result(self.task,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertNotEqual(m.lookup(db,'concept','parent')['description'],changed['description'])

    def test_same_as_maps_new_concept_to_existing(self):
        self.write({'changes':{'concepts':[concept('duplicate')],'dependencies':[{**edge('duplicate','root'),'purpose':'statement'}]},
                    'same_as':{'duplicate':{'target':'parent','reason':'Same mathematical meaning.'}}})
        plans.import_result(self.task,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM concept WHERE slug='duplicate'").fetchone())
            rows=db.execute("SELECT p.slug FROM concept_dependency e JOIN concept p ON p.id=e.prerequisite_id JOIN concept d ON d.id=e.dependent_id WHERE d.slug='root'").fetchall()
            self.assertEqual([r[0] for r in rows],['parent'])

    def test_unknown_sections_and_bad_same_as_rejected(self):
        self.write({'reviewed_ready':True})
        with self.assertRaisesRegex(ValueError,'Unknown result sections'):plans.import_result(self.task,self.db)
        self.write({'operations':{'proposed_revisions':[]}})
        with self.assertRaisesRegex(ValueError,'Unknown operations'):plans.import_result(self.task,self.db)
        self.write({'same_as':{'x':{'target':'parent'}}})
        with self.assertRaisesRegex(ValueError,'reason'):plans.import_result(self.task,self.db)

    def test_failure_after_inner_helpers_try_to_commit_rolls_back_everything(self):
        self.write();before=self.snapshot()
        real=plans.apply_operations
        def fail(*args,**kwargs):
            real(*args,**kwargs)
            raise ValueError('Synthetic late failure')
        with patch.object(plans,'apply_operations',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'late failure'):plans.import_result(self.task,self.db)
        self.assertEqual(before,self.snapshot())
        plans.import_result(self.task,self.db)

    def test_late_cycle_and_invalid_completeness_are_atomic(self):
        self.write({'changes':{'concepts':[concept('new')],'dependencies':[{**edge('root','parent'),'purpose':'statement'},{**edge('parent','root'),'purpose':'statement'}]}})
        before=self.snapshot()
        with self.assertRaises(Exception):plans.import_result(self.task,self.db)
        self.assertEqual(before,self.snapshot())
        self.write({'concept_reviews':[{'slug':'root','statement_prerequisites_complete':1,'reason':'invalid'}]})
        with self.assertRaisesRegex(ValueError,'boolean'):plans.import_result(self.task,self.db)
        self.assertEqual(before,self.snapshot())

    def test_proof_and_statement_reduction_kept_separate_and_boundary_not_inferred(self):
        theorem=concept('theorem');theorem['kind']='theorem'
        self.write({'changes':{'concepts':[concept('middle'),theorem],'dependencies':[
            {**edge('parent','middle'),'purpose':'statement'},
            {**edge('middle','theorem'),'purpose':'proof'},
            {**edge('parent','theorem'),'purpose':'statement'}]}})
        plans.import_result(self.task,self.db)
        with closing(m.connect(self.db)) as db:
            pairs={(r['prerequisite'],r['dependent'],r['purpose']) for r in db.execute('SELECT p.slug prerequisite,d.slug dependent,e.purpose FROM concept_dependency e JOIN concept p ON p.id=e.prerequisite_id JOIN concept d ON d.id=e.dependent_id')}
            self.assertIn(('parent','theorem','statement'),pairs)
            self.assertIn(('middle','theorem','proof'),pairs)
            self.assertFalse(m.lookup(db,'concept','root')['boundary'])

    def test_reorganization_uses_full_core_routes(self):
        operation={'operation':'merge','from':['root','parent'],'to':[concept('combined')],
            'reason':'Synthetic equivalent identity audit.','edge_routes':{},'link_routes':{},'related_routes':{},'formalization_routes':{}}
        self.write({'operations':{'reorganizations':[operation]}})
        plans.import_result(self.task,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertEqual(m.lookup(db,'concept','root')['status'],'superseded')
            self.assertEqual(m.lookup(db,'concept','combined')['status'],'active')

    def test_same_identity_revision_requires_formalization_inventory(self):
        with closing(m.connect(self.db)) as db:
            c=m.lookup(db,'concept','root')
            inventory={'incoming':[],'outgoing':[],'source_occurrences':[],'aliases':[],'related':[],
                       'formalizations':m.formalizations(db,concept='root')}
        operation={'slug':'root','changes':{'title':'Clarified synthetic name'},'reason':'Synthetic editorial correction.',
                   'disposition':'No links or formalization mappings exist; preserve UUID.','incident_inventory':inventory}
        self.write({'operations':{'revisions':[{**operation,'incident_inventory':{**inventory,'aliases':[{'x':1}]}}]}})
        with self.assertRaisesRegex(ValueError,'incident inventory'):plans.import_result(self.task,self.db)
        self.write({'operations':{'revisions':[operation]}})
        plans.import_result(self.task,self.db)
        with closing(m.connect(self.db)) as db:
            after=m.lookup(db,'concept','root');self.assertEqual(after['id'],c['id']);self.assertEqual(after['title'],'Clarified synthetic name')


class PrepareTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'input.sqlite'
        with closing(m.connect(self.db)) as db:
            m.initialize(db);m.ingest(db,{'concepts':[concept('a'),concept('b')]})
        self.before=self.db.read_bytes()

    def test_roots_pinned_snapshot_taken_and_no_overwrite(self):
        out=self.root/'task'
        plans.prepare_task('cone',{'task_id':'test-cones','roots':['a','b']},out,self.db)
        data=json.loads((out/'assignment.json').read_text())
        self.assertEqual([r['slug'] for r in data['roots']],['a','b'])
        self.assertTrue(all(r['id'] for r in data['roots']))
        self.assertEqual(data['prompt'],'prompts/expand-prerequisites.md')
        self.assertTrue((out/data['catalogue']).is_file());self.assertTrue((out/'output').is_dir())
        self.assertEqual(self.db.read_bytes(),self.before)
        with self.assertRaisesRegex(ValueError,'overwrite'):
            plans.prepare_task('cone',{'task_id':'test','roots':['a']},out,self.db)

    def test_source_artifact_hash_mismatch_rolls_back(self):
        artifact=self.root/'paper.pdf';artifact.write_bytes(b'fixture bytes')
        assignment={'task_id':'test-source','source_identifiers':[['arxiv','1501.00001']],
                    'artifact':{'path':str(artifact),'sha256':'wrong','version':'v1'}}
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            plans.prepare_task('source',assignment,self.root/'task',self.db)
        self.assertFalse((self.root/'task').exists())
        assignment['artifact'].pop('sha256')
        plans.prepare_task('source',assignment,self.root/'task',self.db)
        data=json.loads((self.root/'task/assignment.json').read_text())
        self.assertEqual((self.root/'task'/data['artifact']['path']).read_bytes(),artifact.read_bytes())

    def test_conflicting_root_identity_rejected(self):
        with closing(m.connect(self.db)) as db:
            ident=m.lookup(db,'concept','a')['id']
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            plans.prepare_task('cone',{'task_id':'bad','roots':[{'id':ident,'slug':'b'}]},self.root/'bad',self.db)
        self.assertFalse((self.root/'bad').exists())


if __name__=='__main__':unittest.main()
