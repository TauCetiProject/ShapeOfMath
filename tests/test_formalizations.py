import hashlib
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

import mathdb as m
from test_mathdb import concept


def review(*paths, status='formalized'):
    return dict(status=status, evidence='Compared definitions and completed proofs at test-commit.',
                files=[dict(path=p, note='Defines the concept and develops its API.', declarations='Test.definition') for p in paths])


class FormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = m.connect(Path(self.temp.name) / 'db.sqlite')
        m.initialize(self.db)
        m.ingest(self.db, dict(concepts=[concept(x) for x in ('a', 'b', 'c')]))

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def set_review(self, c, *paths, library='mathlib', status='formalized'):
        return m.save_formalization(self.db, c, library, review(*paths, status=status), 'Inspect code')

    def count(self, path, loc, library='mathlib'):
        return m.save_formalization_file(self.db, dict(library=library, path=path, loc=loc,
                                                     revision='test-commit' if loc is not None else None), 'Count lines')

    def report(self, c='a', library='mathlib'):
        return m.formalizations(self.db, concept=c, library=library)[0]

    def test_equal_shares_multiple_files_and_query_filters(self):
        shared, extra = 'Mathlib/Shared.lean', 'Mathlib/Extra.lean'
        self.set_review('a', shared, extra)
        self.set_review('b', shared)
        self.count(shared, 101)
        self.count(extra, 30)
        self.assertEqual(self.report()['estimated_loc'], 80.5)
        self.assertEqual(self.report('b')['estimated_loc'], 50.5)
        self.assertEqual(self.report()['files'][1]['mapped_concepts'], 2)
        all_reports = m.formalizations(self.db, library='mathlib', status='formalized')
        self.assertEqual(sum(r['estimated_loc'] for r in all_reports), 131)
        self.assertEqual(m.formalizations(self.db, concept='a', status='formalized')[0]['estimated_loc'], 80.5)
        self.set_review('b', status='not_formalized')
        self.assertEqual(self.report()['estimated_loc'], 131)
        self.assertIsNone(self.report('b')['estimated_loc'])

    def test_partial_unknown_missing_and_zero_counts(self):
        self.assertEqual(self.report()['status'], 'unknown')
        self.assertIsNone(self.report()['estimated_loc'])
        self.set_review('a', 'Shared.lean', 'Missing.lean')
        self.set_review('b', 'Shared.lean', status='partial')
        self.count('Shared.lean', 120)
        r = self.report()
        self.assertIsNone(r['estimated_loc'])
        self.assertEqual((r['known_loc'], r['file_count'], r['measured_files']), (60, 2, 1))
        self.assertEqual(self.report('b')['estimated_loc'], 60)
        self.count('Missing.lean', 0)
        self.assertEqual(self.report()['estimated_loc'], 60)
        self.count('Shared.lean', None)
        self.assertIsNone(self.report()['estimated_loc'])
        self.assertEqual(self.report()['known_loc'], 0)
        self.assertEqual(self.report()['measured_files'], 1)

    def test_library_separation_registry_and_pinned_links(self):
        path = 'Same.lean'
        self.set_review('a', path)
        self.set_review('b', path, library='tau-ceti')
        self.count(path, 60)
        self.count(path, 90, library='tau-ceti')
        self.assertEqual(self.report()['estimated_loc'], 60)
        self.assertEqual(self.report('b', 'tau-ceti')['estimated_loc'], 90)
        m.save_library(self.db, dict(slug='mathlib', name='Mathlib', repository_url='https://example.org/repo'), 'Configure links')
        self.assertEqual(self.report()['files'][0]['url'], 'https://example.org/repo/blob/test-commit/Same.lean')
        m.save_library(self.db, dict(slug='new-library', name='New Library'), 'Extend registry')
        self.assertEqual(self.report(library='new-library')['status'], 'unknown')
        with self.assertRaises(ValueError):
            m.save_library(self.db, dict(slug='bad', name='Bad', repository_url='javascript:alert(1)'), 'Bad URL')

    def test_revision_invalidates_review_without_losing_evidence(self):
        self.set_review('a', 'Shared.lean')
        self.set_review('b', 'Shared.lean')
        self.count('Shared.lean', 100)
        m.revise(self.db, 'a', {'description': 'A corrected mathematical definition.'}, 'Correct meaning')
        r = self.report()
        self.assertEqual((r['status'], r['recorded_status'], r['review_needed']), ('unknown', 'formalized', True))
        self.assertIsNone(r['estimated_loc'])
        self.assertIsNone(r['files'][0]['allocated_loc'])
        self.assertEqual(len(r['files']), 1)
        self.assertEqual(self.report('b')['estimated_loc'], 100)
        self.set_review('a', 'Shared.lean')
        self.assertEqual(self.report()['estimated_loc'], 50)
        self.assertFalse(self.report()['review_needed'])

    def test_review_validation_and_failed_replacement_preserves_data(self):
        existing = self.set_review('a', 'Existing.lean')
        cases = [review(), review('Unused.lean', status='unknown'), review('Unused.lean', status='not_formalized'),
                 review('../Escape.lean'), review('/Absolute.lean'), review('Bad\\Path.lean'),
                 review('Dot/./Path.lean'), review('Dup.lean', 'Dup.lean'), review('MissingNote.lean')]
        cases[-1]['files'][0]['note'] = ''
        for item in cases:
            with self.subTest(item=item):
                before = m.snapshot(self.db)
                with self.assertRaises(ValueError):
                    m.save_formalization(self.db, 'a', 'mathlib', item, 'Inspect')
                self.assertEqual(m.snapshot(self.db), before)
        updated = self.set_review('a', 'Replacement.lean')
        self.assertEqual(updated['id'], existing['id'])
        self.assertEqual([f['path'] for f in self.report()['files']], ['Replacement.lean'])
        self.assertEqual(m.verify(self.db)['formalization_reviews'], 1)

    def test_measurement_validation_and_file_library_invariant(self):
        self.set_review('a', 'File.lean')
        for changes in [dict(loc=-1), dict(loc=True), dict(loc=2.5), dict(loc=1, revision=''),
                        dict(loc=1, measured_at='not a timestamp'), dict(loc=None, revision='commit'),
                        dict(loc=1, sha256='bad')]:
            item = dict(library='mathlib', path='File.lean', loc=1, revision='commit') | changes
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                m.save_formalization_file(self.db, item, 'Measure')
        self.set_review('b', 'File.lean', library='tau-ceti')
        ids = self.db.execute('SELECT id,library_slug FROM formalization_file ORDER BY id').fetchall()
        fid = self.report()['review_id']
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'different library'):
            with self.db:
                self.db.execute('INSERT INTO concept_formalization_file VALUES (?,?,?,?)', (fid, ids[1]['id'], '', 'Wrong library'))

    def test_ingestion_rollback_includes_nested_formalization_mutations(self):
        batch = dict(formalization_libraries=[dict(slug='other', name='Other')],
                     formalization_files=[dict(library='other', path='New.lean', loc=100, revision='commit')],
                     formalizations=[dict(concept='a', library='other', **review('New.lean')),
                                     dict(concept='missing', library='other', **review('Missing.lean'))])
        before = m.snapshot(self.db)
        history = self.db.execute('SELECT count(*) FROM curation_event').fetchone()[0]
        with self.assertRaises(ValueError):
            m.ingest(self.db, batch)
        self.assertEqual(m.snapshot(self.db), before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM curation_event').fetchone()[0], history)

    def test_split_requires_routes_and_retires_old_shares(self):
        old = self.set_review('a', 'Shared.lean')
        self.set_review('b', 'Shared.lean')
        self.count('Shared.lean', 90)
        plan = dict(operation='split', reason='Separate meanings', **{'from': ['a']}, to=[concept('a1'), concept('a2')],
                    edge_routes={}, link_routes={})
        with self.assertRaisesRegex(ValueError, 'formalization_routes'):
            m.reorganize(self.db, plan)
        self.assertEqual(m.lookup(self.db, 'concept', 'a')['status'], 'active')
        plan['formalization_routes'] = {str(old['id']): dict(replacements=[dict(concept='a1', library='mathlib', **review('Shared.lean'))])}
        m.reorganize(self.db, plan)
        self.assertEqual(m.lookup(self.db, 'concept', 'a')['status'], 'superseded')
        self.assertEqual(self.report('a1')['estimated_loc'], 45)
        self.assertEqual(self.report('a2')['status'], 'unknown')
        self.assertEqual(len(m.formalization_record(self.db, old['id'])['files']), 1)
        self.assertEqual(m.verify(self.db)['formalization_reviews'], 3)

    def test_merge_consolidation_and_late_route_failure_are_atomic(self):
        a = self.set_review('a', 'A.lean')
        b = self.set_review('b', 'B.lean')
        self.count('A.lean', 30)
        self.count('B.lean', 70)
        route = dict(concept='ab', library='mathlib', **review('A.lean', 'B.lean'))
        plan = dict(operation='merge', reason='Unify meanings', **{'from': ['a', 'b']}, to=[concept('ab')],
                    edge_routes={}, link_routes={}, formalization_routes={
                        str(a['id']): dict(replacements=[route]), str(b['id']): dict(replacements=[route])})
        before = m.snapshot(self.db)
        with self.assertRaisesRegex(ValueError, 'Consolidate'):
            m.reorganize(self.db, plan)
        self.assertEqual(m.snapshot(self.db), before)
        plan['formalization_routes'][str(b['id'])] = dict(replacements=[], reason='Consolidated evidence and both files in the first route')
        m.reorganize(self.db, plan)
        self.assertEqual(self.report('ab')['estimated_loc'], 100)
        self.assertEqual(len(self.report('ab')['files']), 2)

    def test_measure_committed_bytes_hashes_and_abort_on_missing_file(self):
        root = Path(self.temp.name) / 'repo'
        root.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout.decode().strip()
        git('init')
        content = b'-- a comment\n\ndef x := 1'  # three physical lines, no trailing newline
        (root / 'File.lean').write_bytes(content)
        (root / 'Empty.lean').write_bytes(b'')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'fixture')
        self.set_review('a', 'File.lean', 'Empty.lean')
        (root / 'File.lean').write_text('uncommitted\n' * 50)
        out = m.measure_formalization_files(self.db, 'mathlib', root, 'Count committed files')
        self.assertEqual(out['revision'], git('rev-parse', 'HEAD'))
        self.assertEqual(self.report()['estimated_loc'], 3)
        f = next(f for f in self.report()['files'] if f['path']=='File.lean')
        self.assertEqual(f['sha256'], hashlib.sha256(content).hexdigest())
        self.set_review('b', 'Missing.lean')
        before = m.snapshot(self.db)
        with self.assertRaisesRegex(ValueError, 'Could not read'):
            m.measure_formalization_files(self.db, 'mathlib', root, 'Missing file')
        self.assertEqual(m.snapshot(self.db), before)
        git('rm', 'Empty.lean')
        (root / 'Empty.lean').symlink_to('File.lean')
        git('add', 'Empty.lean')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'symlink')
        self.set_review('b', status='unknown')
        with self.assertRaisesRegex(ValueError, 'regular tracked file'):
            m.measure_formalization_files(self.db, 'mathlib', root, 'Reject symlink')

    def test_inherited_availability_has_zero_native_cost_and_no_file_share(self):
        self.set_review('a', 'Shared.lean')
        self.set_review('b', 'Shared.lean')
        self.count('Shared.lean', 100)
        self.set_review('b', status='inherited')
        inherited = self.report('b')
        self.assertEqual((inherited['status'], inherited['estimated_loc'], inherited['known_loc']), ('inherited', 0, 0))
        self.assertEqual(inherited['files'], [])
        self.assertEqual(self.report()['estimated_loc'], 100)
        self.assertEqual(len(m.formalizations(self.db, library='mathlib', status='inherited')), 1)
        with self.assertRaisesRegex(ValueError, 'empty file list'):
            self.set_review('b', 'Wrong.lean', status='inherited')
        m.revise(self.db, 'b', {'description': 'Changed concept statement.'}, 'Review changed identity')
        self.assertEqual(self.report('b')['status'], 'unknown')
        self.assertIsNone(self.report('b')['estimated_loc'])

    def test_conjecture_coverage_is_explicitly_statement_only(self):
        m.revise(self.db, 'a', {'kind': 'conjecture'}, 'Synthetic conjecture fixture')
        self.set_review('a', 'Statement.lean')
        self.count('Statement.lean', 10)
        report = self.report()
        self.assertEqual(report['concept_kind'], 'conjecture')
        self.assertTrue(report['statement_only'])
        self.assertEqual(report['estimated_loc'], 10)
        self.assertFalse(self.report('b')['statement_only'])
        self.set_review('a', status='inherited')
        self.assertTrue(self.report()['statement_only'])
        self.assertEqual(self.report()['estimated_loc'], 0)

    def test_measure_selected_commit_ignores_newer_head_and_worktree(self):
        root = Path(self.temp.name) / 'selected-repo'
        root.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout.decode().strip()
        git('init')
        file = root / 'File.lean'
        file.write_bytes(b'-- first commit\ndef x := 1')
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'first')
        first = git('rev-parse', 'HEAD')
        file.write_text('-- a much longer new version\n' * 40)
        git('add', '.')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'second')
        file.write_text('Uncommitted worktree content.')
        self.set_review('a', 'File.lean')
        out = m.measure_formalization_files(self.db, 'mathlib', root, 'Count reviewed commit', revision=first)
        self.assertEqual(out['revision'], first)
        self.assertEqual(self.report()['estimated_loc'], 2)
        before = m.snapshot(self.db)
        with self.assertRaises(ValueError):
            m.measure_formalization_files(self.db, 'mathlib', root, 'Invalid revision', revision='missing-commit')
        self.assertEqual(m.snapshot(self.db), before)

    def test_v9_migration_preserves_positive_reviews_file_links_and_measurements(self):
        db = m.connect(Path(self.temp.name) / 'v9.db')
        try:
            db.executescript((Path(__file__).parent / 'fixtures/schema_v9.sql').read_text())
            m.ingest(db, dict(concepts=[concept('legacy')]))
            saved = m.save_formalization(db, 'legacy', 'mathlib', review('Legacy.lean'), 'Original native review')
            m.save_formalization_file(db, dict(library='mathlib', path='Legacy.lean', loc=75, revision='old-commit'), 'Original count')
            before = m.snapshot(db)
            old_review = m.formalization_record(db, saved['id'])
            history_ids = [r[0] for r in db.execute('SELECT id FROM curation_event')]
            m.initialize(db)
            self.assertEqual(m.snapshot(db), before)
            self.assertEqual(m.formalization_record(db, saved['id']), old_review)
            self.assertEqual(m.formalizations(db, concept='legacy', library='mathlib')[0]['estimated_loc'], 75)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
            self.assertEqual([r[0] for r in db.execute('SELECT id FROM curation_event')][:-1], history_ids)
            m.save_formalization(db, 'legacy', 'tau-ceti', review(status='inherited'), 'Checked dependency availability')
            m.initialize(db)
            self.assertEqual(m.formalizations(db, concept='legacy', library='tau-ceti')[0]['estimated_loc'], 0)
            self.assertEqual(m.verify(db)['formalization_reviews'], 2)
        finally:
            db.close()

    def test_v8_migration_preserves_ids_vectors_reviews_and_is_idempotent(self):
        db = m.connect(Path(self.temp.name) / 'v8.db')
        try:
            db.executescript((Path(__file__).parent / 'fixtures/schema_v8.sql').read_text())
            m.ingest(db, dict(concepts=[concept('legacy')]))
            c = dict(m.lookup(db, 'concept', 'legacy'))
            with db:
                db.execute("INSERT INTO embedding_model VALUES ('test','test','hash',1,'{}')")
                db.execute("INSERT INTO concept_embedding VALUES (?,'test',?,?)", (c['id'], m.content_hash(c), b'\0\0\x80?'))
            m.set_completeness(db, 'concept', 'legacy', {'statement_prerequisites_complete': True}, 'Reviewed primitive')
            old = dict(m.lookup(db, 'concept', 'legacy'))
            m.initialize(db)
            self.assertEqual(dict(m.lookup(db, 'concept', 'legacy')), old)
            self.assertEqual(m.verify(db)['vectors'], 1)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 10)
            count = db.execute('SELECT count(*) FROM curation_event').fetchone()[0]
            m.initialize(db)
            self.assertEqual(db.execute('SELECT count(*) FROM curation_event').fetchone()[0], count)
            self.assertTrue(all(r['status']=='unknown' for r in m.formalizations(db)))
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
