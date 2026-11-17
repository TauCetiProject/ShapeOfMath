"""Guard the mechanical full-catalogue importer; no mathematical judgments here."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mathdb as m
from test_mathdb import concept


class CoverageUpdateImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'test.sqlite'
        self.real_connect = m.connect
        with self.real_connect(self.db_path) as db:
            m.initialize(db)
            m.ingest(db, dict(concepts=[concept('sample')]))
            self.c = {k: m.lookup(db, 'concept', 'sample')[k] for k in ('id','slug','title','description','kind','field','status','revision')}
        spec = importlib.util.spec_from_file_location('update_import_test', m.ROOT/'data/formalization-update-2026-11-12/import_reviewed.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.RUN = self.root
        self.module.ROSTER = {'sample': self.c}
        self.module.PLAN = {'tau_mathlib_dependency': 'dependency-commit'}
        for name in ('jobs','proposals','reviews','rechecks','imported'):
            (self.root/name).mkdir()
        self.job = dict(id='batch-000', author='author', reviewer='reviewer', concepts=[self.c], libraries=['mathlib'])
        (self.root/'jobs/batch-000.json').write_text(json.dumps(self.job))
        self.row = dict(concept='sample', concept_id=self.c['id'], concept_revision=1,
                        library='mathlib', status='unknown', evidence='Unresolved after the documented source search.',
                        search_notes='A hypothetical fixture, not a mathematical claim.', files=[])
        self.publish(self.row)

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, row, decision='accept', replacement=None):
        proposal = dict(batch_id='batch-000', author='author', reviews=[row])
        raw = (json.dumps(proposal)+'\n').encode()
        (self.root/'proposals/batch-000.json').write_bytes(raw)
        entry = dict(concept='sample',library='mathlib',decision=decision,reason='Independent fixture review.')
        if replacement is not None:
            entry['replacement']=replacement
        review = dict(batch_id='batch-000', reviewer='reviewer', proposal_sha256=hashlib.sha256(raw).hexdigest(), decisions=[entry])
        (self.root/'reviews/batch-000.json').write_text(json.dumps(review))

    def test_only_exact_digest_and_independent_reviewer_are_accepted(self):
        self.assertEqual(len(self.module.prepare(self.job)[0]), 1)
        path=self.root/'proposals/batch-000.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'proposal bytes'):
            self.module.prepare(self.job)
        self.publish(self.row)
        path=self.root/'reviews/batch-000.json'
        review=json.loads(path.read_text());review['reviewer']='author'
        path.write_text(json.dumps(review))
        with self.assertRaisesRegex(ValueError,'independence'):
            self.module.prepare(self.job)

    def test_rejection_and_missing_pair_never_become_importable(self):
        self.publish(self.row,decision='reject')
        with self.assertRaisesRegex(ValueError,'rejected'):
            self.module.prepare(self.job)
        self.publish(self.row)
        job={**self.job,'libraries':['mathlib','tau-ceti']}
        with self.assertRaisesRegex(ValueError,'exact assigned roster'):
            self.module.prepare(job)

    def test_live_revision_conflict_requires_versioned_recheck_and_fresh_review(self):
        self.module.REVISION={'mathlib':'fixture-commit'}
        with self.real_connect(self.db_path) as db:
            m.revise(db,'sample',{'description':'An updated concept meaning.'},'Concurrent fixture edit')
            current={k:m.lookup(db,'concept','sample')[k] for k in self.c}
        with patch.object(self.module.m,'connect',side_effect=lambda: self.real_connect(self.db_path)):
            with self.assertRaisesRegex(ValueError,'Live concept changed'):
                self.module.import_one(self.job)
        with self.real_connect(self.db_path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM concept_formalization').fetchone()[0],0)
        raw=(self.root/'jobs/batch-000.json').read_bytes()
        recheck=dict(parent_job_sha256=hashlib.sha256(raw).hexdigest(),changes=[dict(baseline=self.c,current=current)])
        (self.root/'rechecks/batch-000-input.json').write_text(json.dumps(recheck))
        with self.assertRaisesRegex(ValueError,'revision mismatch'):
            self.module.prepare(self.job)
        self.publish({**self.row,'concept_revision':current['revision'],'evidence':'Independent review checked the revised meaning.'})
        with patch.object(self.module.m,'connect',side_effect=lambda: self.real_connect(self.db_path)):
            receipt=self.module.import_one(self.job)
        self.assertEqual(receipt['context_rechecks']['sample'],dict(baseline_revision=1,reviewed_revision=2))
        with self.real_connect(self.db_path) as db:
            report=m.formalizations(db,concept='sample',library='mathlib')[0]
            self.assertFalse(report['review_needed'])
            self.assertEqual(m.lookup(db,'concept','sample')['description'],'An updated concept meaning.')

    def test_native_measurements_read_committed_bytes_and_global_shares(self):
        repo=self.root/'repo';repo.mkdir()
        def git(*args):
            return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True).stdout.decode().strip()
        git('init')
        content=b'-- exact fixture\ndef x := 1'
        (repo/'Sample.lean').write_bytes(content)
        git('add','.')
        git('-c','user.name=Test','-c','user.email=test@example.org','commit','-m','fixture')
        rev=git('rev-parse','HEAD')
        (repo/'Sample.lean').write_text('uncommitted\n'*50)
        self.module.REPOSITORIES={'mathlib':repo}
        self.module.REVISION={'mathlib':rev}
        row={**self.row,'status':'formalized','files':[dict(path='Sample.lean',declarations='x (L2)',note='Synthetic fixture definition.')],
             'evidence':'Synthetic fixture, source review supplied separately.'}
        self.publish(row)
        with patch.object(self.module.m,'connect',side_effect=lambda: self.real_connect(self.db_path)):
            receipt=self.module.import_one(self.job)
        self.assertEqual(receipt['measurements_updated'],1)
        with self.real_connect(self.db_path) as db:
            report=m.formalizations(db,concept='sample',library='mathlib')[0]
            self.assertEqual(report['estimated_loc'],2)
            self.assertEqual(report['files'][0]['sha256'],hashlib.sha256(content).hexdigest())
            self.assertEqual(report['files'][0]['revision'],rev)
            self.assertEqual(m.lookup(db,'concept','sample')['revision'],1)
            self.assertEqual(m.verify(db)['integrity'],'ok')


if __name__=='__main__':
    unittest.main()
