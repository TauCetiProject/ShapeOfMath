import importlib.util
import unittest
from pathlib import Path

import mathdb as m
from test_mathdb import concept,source,edge

spec=importlib.util.spec_from_file_location('source_task_coordinator',Path(__file__).resolve().parents[1]/'experiments/curation-2015-round2/coordinate.py')
coordinator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(coordinator)


class SourceTaskCoverageTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)
        paper=source('paper');paper['identifiers']=[['arxiv','1501.00001']]
        cs=[concept(x) for x in ('statement','proof','theorem','introduced')]
        cs[2]['kind']='theorem'
        m.ingest(self.db,{'sources':[paper],'concepts':cs,'dependencies':[
            {**edge('statement','theorem'),'purpose':'statement'},
            {**edge('proof','theorem'),'purpose':'proof'}],
            'source_concepts':[{'source':'paper','concept':'theorem','role':'relies_on','locator':'Section 1'},
                               {'source':'paper','concept':'introduced','role':'introduces','locator':'Theorem 2','introduction_evidence':'Synthetic origin evidence.'}]})
        self.sample={'papers':{'math.FA':[{'id':'1501.00001'},{'id':'1501.00002'}]}}

    def tearDown(self):self.db.close()

    def test_coverage_matches_core_and_excludes_proof_only_and_introductions(self):
        result=coordinator.source_cones(self.db,self.sample)['1501.00001']
        core={r['slug'] for r in m.closure(self.db,'paper')}
        self.assertEqual(set(result['concept_slugs']),core)
        self.assertEqual(core,{'statement','theorem'})
        self.assertEqual(result['proof_lists_pending'],['theorem'])
        self.assertFalse(result['statement_cone_complete'])

    def test_missing_source_has_no_claimed_inventory_or_cone(self):
        result=coordinator.source_cones(self.db,self.sample)['1501.00002']
        self.assertFalse(result['source_recorded'])
        self.assertNotIn('statement_cone_complete',result)

    def test_inventory_and_cone_reviews_are_independent(self):
        for slug in ('statement','theorem'):
            m.set_completeness(self.db,'concept',slug,{'statement_prerequisites_complete':True},'Reviewed statement list.')
        result=coordinator.source_cones(self.db,self.sample)['1501.00001']
        self.assertTrue(result['statement_cone_complete'])
        self.assertFalse(result['reading_inventory_complete'])
        self.assertEqual(result['proof_lists_pending'],['theorem'])

    def test_unknown_dependency_prevents_statement_completion(self):
        for slug in ('statement','theorem'):
            m.set_completeness(self.db,'concept',slug,{'statement_prerequisites_complete':True},'Reviewed statement list.')
        with self.db:self.db.execute("UPDATE concept_dependency SET purpose='unclassified' WHERE purpose='proof'")
        result=coordinator.source_cones(self.db,self.sample)['1501.00001']
        self.assertFalse(result['statement_cone_complete'])
        self.assertEqual(result['unclassified_edges'],1)
