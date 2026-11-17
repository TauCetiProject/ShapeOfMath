from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import mathdb as m
from test_mathdb import concept,source

DIRECTORY=Path(__file__).resolve().parents[1]/'experiments/curation-2015-round2'
sys.path.insert(0,str(DIRECTORY))
spec=importlib.util.spec_from_file_location('curation_freeze',DIRECTORY/'freeze.py')
freezer=importlib.util.module_from_spec(spec);spec.loader.exec_module(freezer)


class CurationFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.here=self.root/'experiment';self.here.mkdir()
        self.tasks=self.root/'curation';paper=self.tasks/'papers/1501.00001';paper.mkdir(parents=True)
        (paper/'report.txt').write_text('Unresolved direct proof inventory remains unknown.')
        (paper/'primary.ps').write_text('%!PS\nSynthetic artifact fixture.\n')
        (self.tasks/'WORKFLOW.md').write_text('Neutral source curation fixture.')
        (self.root/'CONCEPTS.md').write_text('Synthetic concept policy.')
        freezer.save(self.here/'sample.json',{'papers':{'math.FA':[{'id':'1501.00001'}]}})
        freezer.save(self.here/'baseline-manifest.json',{
            'sample_sha256':freezer.digest(self.here/'sample.json'),
            'baseline_files_sha256':{},'baseline_event':0})
        paths=['mathdb.py','schema.sql','experiments/curation-2015/apply_paper.py',
               'experiments/curation-2015-round2/coordinate.py',
               'experiments/curation-2015-round2/measure.py',
               'experiments/curation-2015-round2/freeze.py']
        for relative in paths:
            p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('Fixture code.')
        self.db_path=self.root/'live.sqlite';self.output=self.root/'snapshot'
        with closing(m.connect(self.db_path)) as db:
            m.initialize(db)
            s=source();s['identifiers']=[['arxiv','1501.00001']]
            m.ingest(db,{'sources':[s],'concepts':[concept('input')],
                'source_concepts':[{'source':'paper','concept':'input','role':'relies_on','locator':'Section 1'}]})
        self.patches=[patch.object(freezer,'HERE',self.here),
                      patch.object(freezer.c,'ROOT',self.root),patch.object(freezer.c,'TASKS',self.tasks)]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temporary.cleanup()

    def test_snapshot_keeps_unknown_flags_and_is_independent_of_later_edits(self):
        manifest=freezer.freeze(self.db_path,self.output)
        self.assertEqual(manifest['source_records'],1)
        self.assertEqual(manifest['reviewed_reading_cones'],0)
        progress=json.loads((self.output/'progress.json').read_text())['papers']['1501.00001']
        self.assertFalse(progress['reading_inventory_complete'])
        self.assertEqual(progress['statement_frontier'],['input'])
        for name,sha in manifest['files_sha256'].items():
            self.assertEqual(freezer.digest(self.output/name),sha)
        artifacts=json.loads((self.output/'curation-files-sha256.json').read_text())
        self.assertIn('curation/papers/1501.00001/primary.ps',artifacts)
        self.assertEqual((self.output/'curation-config/WORKFLOW.md').read_text(),
                         'Neutral source curation fixture.')
        self.assertEqual((self.output/'instructions/CONCEPTS.md').read_text(),
                         'Synthetic concept policy.')
        self.assertIn('curation-config/WORKFLOW.md',manifest['files_sha256'])
        self.assertIn('instructions/CONCEPTS.md',manifest['files_sha256'])
        with closing(m.connect(self.db_path)) as db:
            m.revise(db,'input',{'description':'Changed after the snapshot.'},'Synthetic later edit.')
        with closing(m.connect(self.output/'math.sqlite')) as db:
            self.assertEqual(m.lookup(db,'concept','input')['description'],concept('input')['description'])

    def test_cannot_overwrite_a_snapshot_or_create_a_missing_source_database(self):
        freezer.freeze(self.db_path,self.output)
        before=(self.output/'manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'refusing to overwrite'):
            freezer.freeze(self.db_path,self.output)
        self.assertEqual((self.output/'manifest.json').read_bytes(),before)
        missing=self.root/'missing.sqlite'
        with self.assertRaisesRegex(ValueError,'does not exist'):
            freezer.freeze(missing,self.root/'another-snapshot')
        self.assertFalse(missing.exists())

    def test_missing_assignment_aborts_without_leaving_a_partial_snapshot(self):
        sample=json.loads((self.here/'sample.json').read_text())
        sample['papers']['math.FA'].append({'id':'1501.00002'})
        freezer.save(self.here/'sample.json',sample)
        manifest=json.loads((self.here/'baseline-manifest.json').read_text())
        manifest['sample_sha256']=freezer.digest(self.here/'sample.json')
        freezer.save(self.here/'baseline-manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'have not been installed'):
            freezer.freeze(self.db_path,self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.post-curation-*')),[])
