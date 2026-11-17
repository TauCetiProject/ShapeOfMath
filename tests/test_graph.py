from contextlib import closing
import copy
import json
import unittest

import mathdb as m
import mathdb_server as api
from test_mathdb import concept,edge,source


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)

    def tearDown(self):
        self.db.close()

    def seed(self,names,edges):
        m.ingest(self.db,dict(sources=[source()],concepts=[concept(x) for x in names],dependencies=edges))

    def reachable(self):
        return {(r['slug'],n['slug']) for r in self.db.execute("SELECT slug FROM concept WHERE status='active'")
                for n in m.prerequisite_cone(self.db,r['slug'])['nodes']}

    def test_entire_cone_shared_nodes_and_longest_depth(self):
        self.seed(['a','b','c','root','unrelated'],[edge('a','b'),edge('a','c'),edge('b','root'),edge('c','root'),edge('a','root')])
        with self.db:m.add_related(self.db,dict(concept_a='root',concept_b='unrelated',rationale='Nearby but not a prerequisite.'))
        cone=m.prerequisite_cone(self.db,'root')
        self.assertEqual({r['slug'] for r in cone['nodes']},{'a','b','c','root'})
        self.assertEqual(len(cone['nodes']),4);self.assertEqual(len(cone['edges']),5)
        self.assertEqual({r['slug']:r['depth'] for r in cone['nodes']},{'root':0,'b':1,'c':1,'a':2})
        self.assertEqual(cone['leaves'],['a']);self.assertFalse(cone['all_reviewed'])
        m.set_completeness(self.db,'concept','root',{'prerequisites_complete':True},'Review only the root')
        self.assertFalse(m.prerequisite_cone(self.db,'root')['all_reviewed'])

    def test_reduction_preserves_reachability_reviews_and_audit_evidence(self):
        e={**edge('a','root'),'source':'paper','locator':'Theorem 4','rationale':'Original direct dependency claim.'}
        self.seed(['a','b','root'],[edge('a','b'),edge('b','root'),e])
        for name in ['a','b','root']:m.set_completeness(self.db,'concept',name,{'prerequisites_complete':True},'Review')
        before=self.reachable();plan=m.reduction_plan(self.db,'root')
        self.assertEqual(len(plan['removed']),1);self.assertEqual(plan['removed'][0]['path'],['a','b','root'])
        self.assertEqual(len(m.prerequisite_cone(self.db,'root')['edges']),3)  # Preview is read-only.
        result=m.reduce_dependencies(self.db,'Remove transitive shortcuts','root')
        self.assertEqual(self.reachable(),before);self.assertTrue(m.prerequisite_cone(self.db,'root')['all_reviewed'])
        self.assertEqual(m.reduction_plan(self.db,'root')['removed'],[])
        event=self.db.execute('SELECT * FROM curation_event ORDER BY id DESC LIMIT 1').fetchone()
        old=json.loads(event['before_json'])['edges'][0]
        self.assertEqual(old['rationale'],e['rationale']);self.assertEqual(old['locator'],'Theorem 4');self.assertIsNotNone(old['evidence_source_id'])
        self.assertEqual(json.loads(event['after_json'])['removed'],result['removed'])

    def test_dense_graph_witnesses_use_only_retained_edges(self):
        names=[str(i) for i in range(10)]
        self.seed(names,[edge(str(i),str(j)) for i in range(10) for j in range(i+1,10)])
        before=self.reachable();plan=m.reduce_dependencies(self.db,'Reduce dense DAG')
        self.assertEqual(plan['retained_edges'],9);self.assertEqual(len(plan['removed']),36)
        removed={r['edge']['id'] for r in plan['removed']}
        for r in plan['removed']:
            self.assertGreaterEqual(len(r['path']),3)
            self.assertFalse(removed&set(r['path_edge_ids']))
        self.assertEqual(self.reachable(),before)

    def test_scoped_reduction_leaves_other_dependents_untouched(self):
        self.seed(['a','b','root','other'],[edge('a','b'),edge('b','root'),edge('a','root'),edge('a','other'),edge('b','other')])
        m.reduce_dependencies(self.db,'Only the chosen cone','root')
        all_edges=self.db.execute('SELECT count(*) FROM concept_dependency').fetchone()[0]
        self.assertEqual(all_edges,4)
        self.assertEqual(len(m.reduction_plan(self.db,'other')['removed']),1)

    def test_singleton_cone_and_unknown_or_historical_root(self):
        self.seed(['a'],[]);self.assertFalse(m.prerequisite_cone(self.db,'a')['all_reviewed'])
        with self.assertRaises(ValueError):m.prerequisite_cone(self.db,'unknown')
        with self.db:self.db.execute("UPDATE concept SET status='superseded' WHERE slug='a'")
        with self.assertRaisesRegex(ValueError,'superseded'):m.prerequisite_cone(self.db,'a')

    def test_api_cone_reduction_preview_and_write(self):
        self.seed(['a','b','root'],[edge('a','b'),edge('b','root'),edge('a','root')])
        self.assertEqual(len(api.read_api(self.db,['concepts','root','cone'],{})['nodes']),3)
        self.assertEqual(len(api.read_api(self.db,['concepts','root','reduction'],{})['removed']),1)
        result=api.write_api(self.db,'POST',['reductions'],dict(root='root',reason='Curator review'))
        self.assertEqual(result['retained_edges'],2)
        self.assertTrue(m.verify(self.db)['dag'])

    def test_recursive_experiment_closes_both_cones_and_is_reproducible(self):
        import curate_recursive as experiment
        plan=json.loads(experiment.PLAN.read_text())
        payload=json.loads((m.ROOT/'data/seed.json').read_text())
        m.ingest(self.db,payload)
        result=experiment.apply(self.db,plan)
        self.assertEqual(result['cones']['drinfeld-center']['leaves'],['set'])
        self.assertEqual(set(result['cones']['chebyshev-inequality']['leaves']),{'set','natural-number'})
        for root,cone in result['cones'].items():
            self.assertTrue(cone['all_reviewed']);self.assertFalse(m.reduction_plan(self.db,root)['removed'])
            expected={r['id'] for r in cone['nodes']}
            self.assertTrue(all(e['prerequisite_id'] in expected and e['dependent_id'] in expected for e in cone['edges']))
        dc=result['cones']['drinfeld-center']
        functor=m.lookup(self.db,'concept','functor')['id']
        self.assertNotIn(functor,{e['prerequisite_id'] for e in dc['edges'] if e['dependent_id']==dc['root_id']})
        self.assertIn(functor,{n['id'] for n in dc['nodes']})
        previous=self.db.execute('SELECT count(*) FROM curation_event').fetchone()[0]
        self.assertTrue(experiment.apply(self.db,plan)['already_applied'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM curation_event').fetchone()[0],previous)
        self.assertEqual(m.verify(self.db)['ingested_sources'],7)
