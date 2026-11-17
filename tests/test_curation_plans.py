from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mathdb as m
import curation_plans as plans
from curation.prepare_task import prepare
from test_mathdb import concept,source,edge


class GeneralPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'math.sqlite'
        with closing(m.connect(self.db)) as db:
            m.initialize(db);m.ingest(db,{'concepts':[concept('root'),concept('parent')]})
        self.task=self.root/'task'
        prepare('cone',{'task_id':'new-cone-task','roots':['root']},self.task,self.db)
        self.path=self.task/'output/plan-001.json'

    def plan(self,payload=None,review=None):
        self.path.write_text(json.dumps(payload or {'dependencies':[{**edge('parent','root'),'purpose':'statement'}]}))
        self.path.with_name(self.path.stem+'-review.json').write_text(json.dumps(review or {
            'reviewed_ready':True,'reviews':[{'slug':'root','statement_prerequisites_complete':True,'reason':'Synthetic full immediate-list review.'}]}))

    def snapshot(self):
        with closing(m.connect(self.db)) as db:return m.snapshot(db)

    def test_cone_without_source_and_any_task_id_check_does_not_mutate(self):
        self.plan();before=self.snapshot();receipt=plans.check(self.task,self.path,self.db)
        self.assertEqual(before,self.snapshot());self.assertTrue(receipt['preflight_ok'])
        result=plans.import_plan(self.task,self.path,self.db);self.assertTrue(result['changed'])
        with closing(m.connect(self.db)) as db:
            self.assertTrue(m.lookup(db,'concept','root')['statement_prerequisites_complete'])
            self.assertEqual(db.execute("SELECT count(*) FROM curation_event WHERE operation='curated_task_plan'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM curation_event WHERE operation='paper_2015_stage'").fetchone()[0],0)
        before=self.snapshot();self.assertFalse(plans.import_plan(self.task,self.path,self.db)['changed']);self.assertEqual(before,self.snapshot())

    def test_source_outside_2015_and_reused_identifier_not_dropped(self):
        # Source identity is established by checked external identifiers, not year/sample.
        with closing(m.connect(self.db)) as db:m.ingest(db,{'sources':[source('canonical')]})
        other=self.root/'source-task';prepare('source',{'task_id':'source-2027','source_identifiers':[['doi','10.1234/paper']]},other,self.db)
        candidate=source('renamed');candidate['identifiers']=source('canonical')['identifiers']+[['doi','10.1234/extra']]
        path=other/'output/plan-001.json';path.write_text(json.dumps({'sources':[candidate]}))
        path.with_name('plan-001-review.json').write_text(json.dumps({'reviewed_ready':True,'reviews':[]}))
        plans.check(other,path,self.db);plans.import_plan(other,path,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM source').fetchone()[0],1)
            self.assertIsNotNone(db.execute("SELECT 1 FROM source_identifier WHERE value='10.1234/extra'").fetchone())

    def test_unreleased_changed_plan_and_tampered_input_rejected(self):
        self.plan(review={'reviewed_ready':False,'reviews':[]})
        with self.assertRaisesRegex(ValueError,'released'):plans.check(self.task,self.path,self.db)
        self.plan();plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        self.path.write_text(self.path.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'changed after import'):plans.import_plan(self.task,self.path,self.db)
        (self.task/'task.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'Pinned task input'):plans.check(self.task,self.path,self.db)

    def test_exact_event_guards_race_between_check_and_import(self):
        self.plan();plans.check(self.task,self.path,self.db)
        with closing(m.connect(self.db)) as db:m.ingest(db,{'concepts':[concept('concurrent')]})
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Database changed'):plans.import_plan(self.task,self.path,self.db)
        self.assertEqual(before,self.snapshot())
        plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)

    def test_stale_direct_prerequisite_review_rejected(self):
        self.plan()
        with closing(m.connect(self.db)) as db:m.ingest(db,{'dependencies':[{**edge('parent','root'),'purpose':'statement'}]})
        with self.assertRaisesRegex(ValueError,'prerequisite list changed'):plans.check(self.task,self.path,self.db)

    def test_failure_after_legacy_helpers_try_to_commit_rolls_back_everything(self):
        self.plan();plans.check(self.task,self.path,self.db);before=self.snapshot()
        real=plans.apply_operations
        def fail(*args,**kwargs):
            real(*args,**kwargs)
            raise ValueError('Synthetic late failure')
        with patch.object(plans,'apply_operations',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'late failure'):plans.import_plan(self.task,self.path,self.db)
        self.assertEqual(before,self.snapshot())
        plans.import_plan(self.task,self.path,self.db)

    def test_late_cycle_and_invalid_completeness_are_atomic(self):
        self.plan({'concepts':[concept('new')],'dependencies':[{**edge('root','parent'),'purpose':'statement'},{**edge('parent','root'),'purpose':'statement'}]})
        before=self.snapshot()
        with self.assertRaises(Exception):plans.check(self.task,self.path,self.db)
        self.assertEqual(before,self.snapshot())
        self.plan(review={'reviewed_ready':True,'reviews':[{'slug':'root','statement_prerequisites_complete':1,'reason':'invalid'}]})
        with self.assertRaisesRegex(ValueError,'boolean'):plans.check(self.task,self.path,self.db)
        self.assertEqual(before,self.snapshot())

    def test_task_id_collision_and_outside_path_rejected(self):
        self.plan();plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        other=self.root/'other';prepare('cone',{'task_id':'new-cone-task','roots':['root']},other,self.db)
        path=other/'output/plan-001.json';path.write_bytes(self.path.read_bytes())
        path.with_name('plan-001-review.json').write_bytes(self.path.with_name('plan-001-review.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'different pinned package'):plans.check(other,path,self.db)
        with self.assertRaises(ValueError):plans.check(self.task,path,self.db)

    def test_current_state_rereview_for_followup_and_stale_review_event(self):
        self.plan()
        with closing(m.connect(self.db)) as db:
            m.ingest(db,{'dependencies':[{**edge('parent','root'),'purpose':'statement'}]})
            event=plans.version(db)
        review={'reviewed_ready':True,'reviewed_against_event':event,'current_state_review_reason':'Synthetic curator rechecked the changed list.',
            'reviews':[{'slug':'root','statement_prerequisites_complete':True,'reason':'Current complete direct list reviewed.'}]}
        self.plan(review=review);plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        self.path=self.task/'output/plan-002.json';self.plan(review=review)
        self.path.with_name('plan-002-review.json').write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError,'reviewed_against_event is stale'):plans.check(self.task,self.path,self.db)

    def test_proof_and_statement_reduction_kept_separate_and_boundary_not_inferred(self):
        theorem=concept('theorem');theorem['kind']='theorem'
        self.plan({'concepts':[concept('middle'),theorem], 'dependencies':[
            {**edge('parent','middle'),'purpose':'statement'},
            {**edge('middle','theorem'),'purpose':'proof'},
            {**edge('parent','theorem'),'purpose':'statement'}]},
            {'reviewed_ready':True,'reviews':[]})
        plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        with closing(m.connect(self.db)) as db:
            pairs={(r['prerequisite'],r['dependent'],r['purpose']) for r in db.execute('SELECT p.slug prerequisite,d.slug dependent,e.purpose FROM concept_dependency e JOIN concept p ON p.id=e.prerequisite_id JOIN concept d ON d.id=e.dependent_id')}
            self.assertIn(('parent','theorem','statement'),pairs)
            self.assertIn(('middle','theorem','proof'),pairs)
            self.assertFalse(m.lookup(db,'concept','root')['boundary'])

    def test_reorganization_uses_full_core_routes_and_reviews_then_imports_atomically(self):
        operation={'operation':'merge','from':['root','parent'],'to':[concept('combined')],
            'reason':'Synthetic equivalent identity audit.','edge_routes':{},'link_routes':{},'related_routes':{},'formalization_routes':{}}
        self.plan({'note':'Synthetic identity merge'}, {'reviewed_ready':True,'reviews':[], 'proposed_reorganizations':[operation]})
        plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        with closing(m.connect(self.db)) as db:
            self.assertEqual(m.lookup(db,'concept','root')['status'],'superseded')
            self.assertEqual(m.lookup(db,'concept','combined')['status'],'active')

    def test_unchanged_edge_does_not_hide_changed_parent_meaning(self):
        with closing(m.connect(self.db)) as db:m.ingest(db,{'dependencies':[{**edge('parent','root'),'purpose':'statement'}]})
        refreshed=self.root/'with-edge';prepare('cone',{'task_id':'with-edge','roots':['root']},refreshed,self.db)
        self.task=refreshed;self.path=self.task/'output/plan-001.json';self.plan()
        with closing(m.connect(self.db)) as db:m.revise(db,'parent',{'description':'Changed synthetic meaning.'},'Synthetic concurrent meaning revision.')
        with self.assertRaisesRegex(ValueError,'prerequisite changed meaning'):plans.check(self.task,self.path,self.db)

    def test_same_identity_revision_requires_formalization_inventory(self):
        with closing(m.connect(self.db)) as db:
            c=m.lookup(db,'concept','root')
            inventory={'incoming':[],'outgoing':[],'source_occurrences':[],'aliases':[],'related':[],
                       'formalizations':m.formalizations(db,concept='root')}
        operation={'slug':'root','changes':{'title':'Clarified synthetic name'},'reason':'Synthetic editorial correction.',
                   'disposition':'No links or formalization mappings exist; preserve UUID.', 'incident_inventory':inventory}
        self.plan({'note':'Synthetic same-identity revision'}, {'reviewed_ready':True,'reviews':[],'proposed_revisions':[operation]})
        plans.check(self.task,self.path,self.db);plans.import_plan(self.task,self.path,self.db)
        with closing(m.connect(self.db)) as db:
            after=m.lookup(db,'concept','root');self.assertEqual(after['id'],c['id']);self.assertEqual(after['title'],'Clarified synthetic name')


if __name__=='__main__':unittest.main()
