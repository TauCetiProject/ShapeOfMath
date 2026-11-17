import json
import unittest

import mathdb as m
from test_mathdb import concept,source,edge


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.db=m.connect(':memory:');m.initialize(self.db)
        m.ingest(self.db,{'sources':[source()], 'concepts':[concept(x) for x in ('parent','claim','child')],
            'dependencies':[edge('parent','claim'),edge('claim','child')],
            'source_concepts':[{'source':'paper','concept':'claim','role':'introduces','locator':'Theorem 1',
                                'introduction_evidence':'Initial synthetic attribution.'}]})
        with self.db:self.db.execute('INSERT INTO concept_alias VALUES (?,?)',(m.lookup(self.db,'concept','claim')['id'],'Old claim name'))
        m.set_completeness(self.db,'source','paper',{'introductions_complete':True},'Initial fixture review.')
        m.set_completeness(self.db,'concept','child',{'statement_prerequisites_complete':True},'Initial fixture review.')

    def tearDown(self):self.db.close()

    def plan(self):
        inventory=m.retirement_inventory(self.db,['claim'])
        edges={r['id']:r for r in inventory['incoming']+inventory['outgoing']}
        drop=lambda:{'replacements':[],'reason':'Unsupported claim; reference retained as historical evidence only.'}
        return {'operation':'retire','from':['claim'],'to':[],
                'reason':'The synthetic claim is refuted and has no equivalent replacement.',
                'incident_inventory':inventory,
                'edge_routes':{str(i):drop() for i in edges},
                'link_routes':{str(r['id']):drop() for r in inventory['source_occurrences']},
                'related_routes':{},'formalization_routes':{},
                'alias_dispositions':[{'concept':'claim','alias':'Old claim name','action':'historical_only',
                                       'reason':'Do not redirect this unsupported claim to a different mathematical identity.'}]}

    def test_retirement_preserves_claim_and_occurrences_as_history_without_replacement(self):
        ident=m.lookup(self.db,'concept','claim')['id'];plan=self.plan()
        m.reorganize(self.db,plan)
        claim=m.lookup(self.db,'concept','claim')
        self.assertEqual((claim['id'],claim['status']),(ident,'superseded'))
        self.assertEqual(claim['description'],concept('claim')['description'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_concept').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM active_source_concept').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM concept_alias').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM concept_dependency').fetchone()[0],0)
        self.assertFalse(m.lookup(self.db,'concept','child')['statement_prerequisites_complete'])
        self.assertFalse(m.lookup(self.db,'source','paper')['introductions_complete'])
        event=self.db.execute("SELECT before_json,after_json FROM curation_event WHERE operation='retire'").fetchone()
        self.assertEqual(json.loads(event[0])['aliases'],plan['incident_inventory']['aliases'])
        self.assertEqual(json.loads(event[1]),plan)
        self.assertEqual(m.verify(self.db)['active_concepts'],2)

    def test_stale_inventory_aborts_before_retirement(self):
        plan=self.plan()
        with self.db:self.db.execute("UPDATE source_concept SET note='New source evidence'")
        with self.assertRaisesRegex(ValueError,'exact current complete'):
            m.reorganize(self.db,plan)
        self.assertEqual(m.lookup(self.db,'concept','claim')['status'],'active')
        self.assertEqual(self.db.execute('SELECT count(*) FROM concept_dependency').fetchone()[0],2)

    def test_every_alias_requires_explicit_disposition(self):
        plan=self.plan();plan['alias_dispositions']=[]
        with self.assertRaisesRegex(ValueError,'every alias'):
            m.reorganize(self.db,plan)
        self.assertEqual(m.lookup(self.db,'concept','claim')['status'],'active')

    def test_retirement_cannot_disguise_an_identity_merge(self):
        plan=self.plan();plan['to']=[concept('replacement')]
        with self.assertRaisesRegex(ValueError,'no equivalent replacement'):
            m.reorganize(self.db,plan)
        plan=self.plan();first=next(iter(plan['edge_routes']))
        plan['edge_routes'][first]['replacements']=[edge('parent','child')]
        with self.assertRaisesRegex(ValueError,'cannot invent equivalent replacements'):
            m.reorganize(self.db,plan)
        self.assertEqual(m.lookup(self.db,'concept','claim')['status'],'active')
