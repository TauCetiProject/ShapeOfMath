import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

import mathdb as m
from test_mathdb import concept,source

spec=importlib.util.spec_from_file_location('sample_ingester',Path(__file__).resolve().parents[1]/'experiments/curation-2015/apply_paper.py')
ingester=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingester)


class SampleCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)
        m.ingest(self.db,{'concepts':[concept('a')],'sources':[source()],
            'source_concepts':[{'source':'paper','concept':'a','role':'introduces',
                                'locator':'Theorem 1','introduction_evidence':'Earlier priority judgment.'}]})
        m.set_completeness(self.db,'source','paper',{'requirements_complete':True,'introductions_complete':True},'Synthetic review.')
        self.before=dict(self.db.execute('SELECT * FROM source_concept').fetchone())
        self.correction={'source':'paper','concept':'a','from_role':'introduces','to_role':'explains',
                         'locator':'Theorem 1','before':self.before,'reason':'An earlier source was checked.',
                         'note':'This occurrence is an exposition.'}

    def tearDown(self):self.db.close()

    def test_demotion_keeps_identity_and_old_evidence_in_history(self):
        with self.db:ingester.correct_source_roles(self.db,[self.correction])
        after=dict(self.db.execute('SELECT * FROM source_concept').fetchone())
        self.assertEqual((after['id'],after['role'],after['introduction_evidence']),
                         (self.before['id'],'explains',''))
        audit=self.db.execute("SELECT before_json FROM curation_event WHERE operation='correct_source_occurrence_role'").fetchone()
        self.assertEqual(json.loads(audit[0]),self.before)
        source_row=m.lookup(self.db,'source','paper')
        self.assertEqual((source_row['requirements_complete'],source_row['introductions_complete']),(1,0))

    def test_stale_snapshot_rejects_the_correction(self):
        with self.db:self.db.execute("UPDATE source_concept SET note='New evidence'")
        with self.assertRaisesRegex(ValueError,'exact occurrence snapshot'):
            with self.db:ingester.correct_source_roles(self.db,[self.correction])
        self.assertEqual(self.db.execute('SELECT role FROM source_concept').fetchone()[0],'introduces')

    def test_role_promotions_are_not_accepted_by_demotion_helper(self):
        correction={**self.correction,'from_role':'explains','to_role':'introduces'}
        with self.assertRaisesRegex(ValueError,'introduction demotion'):
            with self.db:ingester.correct_source_roles(self.db,[correction])

    def test_private_progress_is_read_only_unless_explicitly_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'sample.json').write_text(json.dumps({'papers':{'math.FA':[]}}))
            with patch.object(ingester,'HERE',root):
                preview=ingester.progress(self.db)
                self.assertFalse((root/'progress.json').exists())
                ingester.progress(self.db,write_files=True)
                self.assertEqual(json.loads((root/'progress.json').read_text()),preview)

    def test_staged_reorganization_runs_before_post_merge_review_and_is_idempotent(self):
        m.ingest(self.db,{'concepts':[concept('duplicate-a'),concept('duplicate-b')]})
        plan={'operation':'merge','reason':'Reconcile two synthetic names for the same fixture identity.',
              'from':['duplicate-a','duplicate-b'],'to':[concept('merged')],
              'edge_routes':{},'link_routes':{},'related_routes':{},'formalization_routes':{}}
        review={'proposed_reorganizations':[plan],
                'reviews':[{'slug':'merged','statement_prerequisites_complete':True,
                            'reason':'Reviewed the merged fixture immediate list.'}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);payload=root/'plan-merge.json'
            payload.write_text(json.dumps({'note':'Reviewed merge fixture.'}))
            payload.with_name('plan-merge-review.json').write_text(json.dumps(review))
            with patch.object(ingester,'HERE',root):
                result=ingester.apply(self.db,'fixture','cone',write_files=False,batch_path=payload)
                self.assertTrue(result['changed'])
                self.assertTrue(m.lookup(self.db,'concept','merged')['statement_prerequisites_complete'])
                self.assertEqual(m.lookup(self.db,'concept','duplicate-a')['status'],'superseded')
                self.assertEqual(m.lookup(self.db,'concept','duplicate-b')['status'],'superseded')
                repeated=ingester.apply(self.db,'fixture','cone',write_files=False,batch_path=payload)
                self.assertFalse(repeated['changed'])

    def test_source_metadata_update_preserves_flags_and_history_and_rejects_stale_text(self):
        before=dict(m.lookup(self.db,'source','paper'))
        update={'source':'paper','before':{'summary':before['summary']},
                'changes':{'summary':'The printed claim is disputed; see the reviewed source notes.'},
                'reason':'Correct the descriptive summary after source review.'}
        with self.db:ingester.correct_source_metadata(self.db,[update])
        after=dict(m.lookup(self.db,'source','paper'))
        self.assertEqual(after['summary'],update['changes']['summary'])
        self.assertEqual(after['id'],before['id'])
        self.assertEqual(after['introductions_complete'],before['introductions_complete'])
        event=self.db.execute("SELECT before_json FROM curation_event WHERE operation='correct_source_metadata'").fetchone()
        self.assertEqual(json.loads(event[0]),before)
        with self.assertRaisesRegex(ValueError,'stale'):
            with self.db:ingester.correct_source_metadata(self.db,[update])

    def test_locator_correction_preserves_every_other_field_and_invalidates_reviews(self):
        m.ingest(self.db,{'concepts':[concept('parent')],'dependencies':[{
            'prerequisite':'parent','dependent':'a','basis':'both','purpose':'statement',
            'rationale':'Synthetic dependency.','source':'paper','locator':'Wrong pointer'}]})
        m.set_completeness(self.db,'concept','a',{'statement_prerequisites_complete':True},'Fixture review.')
        edge=dict(self.db.execute('SELECT * FROM concept_dependency').fetchone())
        corrections=[{'kind':'dependency','before':edge,'locator':'Lemma 2','reason':'Checked exact source numbering.'},
                     {'kind':'source_occurrence','before':self.before,'locator':'Theorem 3','reason':'Checked exact source numbering.'}]
        with self.db:ingester.correct_locators(self.db,corrections)
        changed_edge=dict(self.db.execute('SELECT * FROM concept_dependency').fetchone())
        changed_link=dict(self.db.execute('SELECT * FROM source_concept').fetchone())
        self.assertEqual(changed_edge,{**edge,'locator':'Lemma 2'})
        self.assertEqual(changed_link,{**self.before,'locator':'Theorem 3'})
        self.assertFalse(m.lookup(self.db,'concept','a')['statement_prerequisites_complete'])
        self.assertTrue(m.lookup(self.db,'source','paper')['introductions_complete'])
        audits=[json.loads(r[0]) for r in self.db.execute("SELECT before_json FROM curation_event WHERE operation='correct_evidence_locator' ORDER BY id")]
        self.assertEqual(audits,[edge,self.before])

    def test_stale_locator_in_a_batch_prevents_all_corrections(self):
        first={'kind':'source_occurrence','before':self.before,'locator':'Checked pointer','reason':'Fix source numbering.'}
        stale={**first,'before':{**self.before,'note':'Stale evidence.'}}
        with self.assertRaisesRegex(ValueError,'exact current row'):
            ingester.correct_locators(self.db,[first,stale])
        self.assertEqual(dict(self.db.execute('SELECT * FROM source_concept').fetchone()),self.before)

    def test_identifier_correction_normalizes_preserves_source_and_audits_old_value(self):
        before=dict(self.db.execute('SELECT * FROM source_identifier').fetchone())
        source_before=dict(m.lookup(self.db,'source','paper'))
        correction={'before':before,'replacement':['doi','https://doi.org/10.1234/Corrected'],
                    'reason':'Verified the exact identifier against the primary bibliography.'}
        ingester.correct_source_identifiers(self.db,[correction])
        self.assertEqual(dict(m.lookup(self.db,'source','paper')),source_before)
        after=dict(self.db.execute('SELECT * FROM source_identifier').fetchone())
        self.assertEqual((after['scheme'],after['value'],after['source_id']),
                         ('doi','10.1234/corrected',before['source_id']))
        audit=self.db.execute("SELECT before_json FROM curation_event WHERE operation='correct_source_identifier'").fetchone()
        self.assertEqual(json.loads(audit[0]),before)
        with self.assertRaisesRegex(ValueError,'exact current row'):
            ingester.correct_source_identifiers(self.db,[correction])

    def test_identifier_correction_cannot_steal_an_identifier_or_remove_the_last_one(self):
        before=dict(self.db.execute('SELECT * FROM source_identifier').fetchone())
        other=source('other');other['identifiers']=[['doi','10.1234/other']]
        m.ingest(self.db,{'sources':[other]})
        correction={'before':before,'replacement':['doi','10.1234/other'],'reason':'Synthetic collision test.'}
        with self.assertRaisesRegex(ValueError,'belongs to another source'):
            ingester.correct_source_identifiers(self.db,[correction])
        correction={**correction,'replacement':None}
        with self.assertRaisesRegex(ValueError,'last source identifier'):
            ingester.correct_source_identifiers(self.db,[correction])
        self.assertEqual(dict(self.db.execute('SELECT * FROM source_identifier WHERE source_id=?',(before['source_id'],)).fetchone()),before)

    def test_dependency_evidence_update_preserves_reachability_and_invalidates_review(self):
        m.ingest(self.db,{'concepts':[concept('parent')],'dependencies':[{
            'prerequisite':'parent','dependent':'a','basis':'both','purpose':'statement',
            'rationale':'Earlier provisional explanation.','source':'paper','locator':'Page 1'}]})
        m.set_completeness(self.db,'concept','a',{'statement_prerequisites_complete':True},'Fixture review.')
        before=dict(self.db.execute('SELECT * FROM concept_dependency').fetchone())
        old_nodes={r['id'] for r in m.prerequisite_cone(self.db,'a')['nodes']}
        update={'before':before,'changes':{'rationale':'Checked exact statement in the primary source.',
                 'locator':'Theorem 2, page 3'},'reason':'Replace the obsolete provisional explanation.'}
        ingester.correct_dependency_evidence(self.db,[update])
        after=dict(self.db.execute('SELECT * FROM concept_dependency').fetchone())
        self.assertEqual(after,{**before,**update['changes']})
        self.assertEqual({r['id'] for r in m.prerequisite_cone(self.db,'a')['nodes']},old_nodes)
        self.assertFalse(m.lookup(self.db,'concept','a')['statement_prerequisites_complete'])
        audit=self.db.execute("SELECT before_json FROM curation_event WHERE operation='correct_dependency_evidence'").fetchone()
        self.assertEqual(json.loads(audit[0]),before)

    def test_dependency_evidence_update_rejects_stale_or_structural_changes_before_writing(self):
        m.ingest(self.db,{'concepts':[concept('parent')],'dependencies':[{
            'prerequisite':'parent','dependent':'a','basis':'both','purpose':'statement',
            'rationale':'Earlier explanation.','locator':'Page 1'}]})
        before=dict(self.db.execute('SELECT * FROM concept_dependency').fetchone())
        update={'before':before,'changes':{'rationale':'Checked explanation.'},'reason':'Review evidence.'}
        stale={**update,'before':{**before,'locator':'Stale pointer'}}
        with self.assertRaisesRegex(ValueError,'exact current row'):
            ingester.correct_dependency_evidence(self.db,[update,stale])
        with self.assertRaisesRegex(ValueError,'rationale/locator'):
            ingester.correct_dependency_evidence(self.db,[{**update,'changes':{'purpose':'proof'}}])
        self.assertEqual(dict(self.db.execute('SELECT * FROM concept_dependency').fetchone()),before)
