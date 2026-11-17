import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

import mathdb as m
from test_mathdb import concept

spec=importlib.util.spec_from_file_location('task_package',Path(__file__).resolve().parents[1]/'curation/prepare_task.py')
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)


class TaskPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'input.sqlite'
        with closing(m.connect(self.db)) as db:
            m.initialize(db);m.ingest(db,{'concepts':[concept('a'),concept('b')]})
        self.before=self.db.read_bytes()

    def test_multiple_roots_pinned_and_move_preserves_hashes(self):
        out=self.root/'task'
        manifest=package.prepare('cone',{'task_id':'test-cones','roots':['a','b']},out,self.db)
        data=json.loads((out/'assignment.json').read_text())
        self.assertEqual([r['slug'] for r in data['roots']],['a','b'])
        self.assertTrue(all(r['id'] for r in data['roots']))
        moved=self.root/'moved';out.rename(moved)
        for name,digest in manifest['files_sha256'].items():
            self.assertEqual(hashlib.sha256((moved/name).read_bytes()).hexdigest(),digest)
        self.assertTrue((moved/data['catalogue']).is_file())
        self.assertEqual(self.db.read_bytes(),self.before)
        with self.assertRaisesRegex(ValueError,'overwrite'):
            package.prepare('cone',{'task_id':'test','roots':['a']},moved,self.db)

    def test_source_artifact_hash_mismatch_rolls_back(self):
        artifact=self.root/'paper.pdf';artifact.write_bytes(b'fixture bytes')
        assignment={'task_id':'test-source','source_identifiers':[['arxiv','1501.00001']],
                    'artifact':{'path':str(artifact),'sha256':'wrong','version':'v1'}}
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            package.prepare('source',assignment,self.root/'task',self.db)
        self.assertFalse((self.root/'task').exists())
        assignment['artifact'].pop('sha256')
        package.prepare('source',assignment,self.root/'task',self.db)
        data=json.loads((self.root/'task/assignment.json').read_text())
        self.assertEqual((self.root/'task'/data['artifact']['path']).read_bytes(),artifact.read_bytes())

    def test_conflicting_root_identity_rejected(self):
        with closing(sqlite3.connect(self.db)) as db:
            ident=db.execute("SELECT id FROM concept WHERE slug='a'").fetchone()[0]
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            package.prepare('cone',{'task_id':'bad','roots':[{'id':ident,'slug':'b'}]},self.root/'bad',self.db)
        self.assertFalse((self.root/'bad').exists())


if __name__=='__main__':unittest.main()
