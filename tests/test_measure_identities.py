import importlib.util
from pathlib import Path
import sys
import unittest

import mathdb as m
from test_mathdb import concept

DIRECTORY=Path(__file__).resolve().parents[1]/'experiments/curation-2015-round2'
sys.path.insert(0,str(DIRECTORY))
spec=importlib.util.spec_from_file_location('round2_measure',DIRECTORY/'measure.py')
measure=importlib.util.module_from_spec(spec);spec.loader.exec_module(measure)


class IdentityMeasurementTests(unittest.TestCase):
    def test_only_audited_merges_normalize_old_ids_and_chains_deduplicate(self):
        db=m.connect(':memory:');self.addCleanup(db.close);m.initialize(db)
        m.ingest(db,{'concepts':[concept(s) for s in ('a','b','d')]})
        baseline=db.execute('SELECT max(id) FROM curation_event').fetchone()[0]
        def merge(old,new):
            m.reorganize(db,{'operation':'merge','from':old,'to':[concept(new)],
                'reason':'Synthetic equivalent-identity audit.','edge_routes':{},'link_routes':{},
                'related_routes':{},'formalization_routes':{}})
        old={s:m.lookup(db,'concept',s)['id'] for s in ('a','b','d')}
        merge(['a','b'],'ab');merge(['ab','d'],'all')
        targets=measure.audited_merge_targets(db,baseline)
        final=m.lookup(db,'concept','all')['id']
        self.assertEqual(measure.merge_normalized(set(old.values()),targets),{final})
        self.assertEqual(measure.merge_normalized({'unrelated'},targets),{'unrelated'})
        last=db.execute('SELECT max(id) FROM curation_event').fetchone()[0]
        self.assertEqual(measure.audited_merge_targets(db,last),{})

    def test_bad_historical_mapping_does_not_loop(self):
        with self.assertRaisesRegex(ValueError,'Cycle'):
            measure.merge_normalized({'a'},{'a':'b','b':'a'})
