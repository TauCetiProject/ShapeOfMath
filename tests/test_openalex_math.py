import gzip
import json
from pathlib import Path
import tempfile
import unittest

try:
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq
    import openalex_math as om
except ImportError:  # optional dependency: pip install '.[openalex]'
    om = None

MATH, PHYS = 'https://openalex.org/fields/26', 'https://openalex.org/fields/31'
W = 'https://openalex.org/W'


def work(n, field, refs=(), xpac=False, title=None):
    return {'id': f'{W}{n}', 'title': title or f'work {n}', 'is_xpac': xpac,
            'primary_topic': None if field is None else {'id': 'https://openalex.org/T1', 'field': {'id': field}},
            'referenced_works': [f'{W}{r}' for r in refs]}


SCHEMA = pa.schema([('id', pa.string()), ('title', pa.string()), ('is_xpac', pa.bool_()),
                    ('primary_topic', pa.struct([('id', pa.string()), ('field', pa.struct([('id', pa.string())]))])),
                    ('referenced_works', pa.list_(pa.string()))]) if om else None


def publish(root, date, partitions, deleted=(), merged=()):
    """Write a fake upstream release: {updated_date: [[works of part 0], [part 1], ...]}."""
    works = Path(root)/'works'
    if works.exists():
        for f in works.rglob('*.parquet'):
            f.unlink()
    files = []
    for partition, parts in partitions.items():
        for i, rows in enumerate(parts):
            path = works/f'updated_date={partition}'/f'part_{i:04d}.parquet'
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path, row_group_size=2)
            files.append({'url': f's3://openalex/data/parquet/works/updated_date={partition}/part_{i:04d}.parquet',
                          'meta': {'content_length': path.stat().st_size, 'record_count': len(rows)}})
    works.mkdir(parents=True, exist_ok=True)
    (works/'manifest.json').write_text(json.dumps({'date': date, 'files': files}))
    with gzip.open(works/'deleted_ids.csv.gz', 'wt') as f:
        f.write('work_id,deleted_date\n'+''.join(f'{W}{n},{d}\n' for n, d in deleted))
    if merged:
        with gzip.open(works/'merged_ids.csv.gz', 'wt') as f:
            f.write('id,merge_into_id,merge_date\n'+''.join(f'{W}{a},{W}{b},{d}\n' for a, b, d in merged))


def ids(out, entity='works'):
    found = {}
    for f in sorted((Path(out)/'data/parquet'/entity).rglob('*.parquet')):
        partition = f.parent.name.split('=')[1]
        t = pq.read_table(f).to_pylist()
        found.setdefault(partition, []).extend(
            int(r['id'][len(W):]) if entity == 'works' else (int(r['cited_work_id'][len(W):]), int(r['citing_work_id'][len(W):]))
            for r in t)
    return {k: sorted(v) for k, v in found.items()}


def ledger(out, name):
    path = Path(out)/'data/parquet/works'/name
    return pacsv.read_csv(path, convert_options=pacsv.ConvertOptions(column_types={'deleted_date': pa.string(), 'merge_date': pa.string()})).to_pylist() if path.exists() else []


def release(up, out, **kw):
    return om.Release(om.Upstream(str(up)), out, 's3://bucket/data/parquet', workers=2, **kw).run()


@unittest.skipIf(om is None, 'pyarrow/numpy not installed')
class OpenAlexMathTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        self.up, self.out = Path(self.dir.name)/'up', Path(self.dir.name)/'out'

    def first(self):
        publish(self.up, '2026-10-14', {
            '2026-01-01': [[work(1, MATH), work(2, PHYS, [1]), work(3, MATH, [1, 1]), work(4, MATH, xpac=True)],
                           [work(5, None, [3]), work(6, MATH, [99])]],
            '2026-02-01': [[work(7, MATH, [6, 3]), work(8, MATH, xpac=False), work(9, PHYS, [8], xpac=True)]],
            '2026-03-01': [[work(10, PHYS, [2])]],
        }, deleted=[(50, '2026-01-02')])
        return release(self.up, self.out)

    def test_first_release_selects_nonxpac_primary_math_and_incoming_citations(self):
        state = self.first()
        self.assertEqual(ids(self.out), {'2026-01-01': [1, 3, 6], '2026-02-01': [7, 8]})
        # citations partitioned by the cited work's partition; xpac citers excluded, duplicates collapsed
        self.assertEqual(ids(self.out, 'citations'), {'2026-01-01': [(1, 2), (1, 3), (3, 5), (3, 7), (6, 7)]})
        self.assertEqual(state['plan'], {'keep': 0, 'prune': 0, 'extract': 2})
        manifest = json.loads((self.out/'data/parquet/works/manifest.json').read_text())
        self.assertEqual(manifest['record_count'], 5)
        self.assertTrue(all(f['url'].startswith('s3://bucket/data/parquet/works/updated_date=') for f in manifest['files']))
        combined = json.loads((self.out/'data/parquet/manifest.json').read_text())
        self.assertEqual([e['entity'] for e in combined['entities']], ['works', 'citations'])
        # all columns preserved
        self.assertEqual(set(pq.read_schema(next((self.out/'data/parquet/works').rglob('*.parquet'))).names),
                         {'id', 'title', 'is_xpac', 'primary_topic', 'referenced_works'})
        self.assertEqual(ledger(self.out, 'deleted_ids.csv.gz'), [])

    def test_incremental_release_moves_prunes_deletes_and_merges(self):
        self.first()
        kept = (self.out/'data/parquet/works/updated_date=2026-02-01/part_0000.parquet').stat().st_mtime_ns
        # Next release: 1 updated (moves), 3 deleted, 6 reclassified to physics (moves),
        # 7 unchanged, 8 merged into 11, 12 is a new math work citing 1 and 8.
        publish(self.up, '2027-01-13', {
            '2026-01-01': [[work(2, PHYS, [1])], [work(5, None, [3])]],
            '2026-02-01': [[work(7, MATH, [6, 3]), work(9, PHYS, [8], xpac=True)]],
            '2026-03-01': [[work(10, PHYS, [2])]],
            '2027-01-10': [[work(1, MATH, title='updated'), work(6, PHYS, [99]), work(11, MATH), work(12, MATH, [1, 8])]],
        }, deleted=[(50, '2026-01-02'), (3, '2026-12-01')], merged=[(8, 11, '2026-12-05')])
        state = release(self.up, self.out)
        self.assertEqual(state['plan'], {'keep': 0, 'prune': 2, 'extract': 1})
        self.assertEqual(ids(self.out), {'2026-02-01': [7], '2027-01-10': [1, 11, 12]})
        # 12 -> 8 resolves through the merge to 11; 7 -> 6 dropped because 6 left mathematics
        self.assertEqual(ids(self.out, 'citations'), {'2027-01-10': [(1, 2), (1, 12), (11, 12)]})
        self.assertEqual(ledger(self.out, 'deleted_ids.csv.gz'),
                         [{'work_id': f'{W}3', 'deleted_date': '2026-12-01'}, {'work_id': f'{W}6', 'deleted_date': '2027-01-13'}])
        self.assertEqual([r['id'] for r in ledger(self.out, 'merged_ids.csv.gz')], [f'{W}8'])
        updated = pq.read_table(self.out/'data/parquet/works/updated_date=2027-01-10/part_0000.parquet').to_pylist()
        self.assertEqual(updated[0]['title'], 'updated')
        self.assertNotEqual(kept, (self.out/'data/parquet/works/updated_date=2026-02-01/part_0000.parquet').stat().st_mtime_ns)

        # A re-run against the same release leaves every partition alone, and restoring 6 to
        # mathematics removes it from the deletion ledger.
        before = {f: f.stat().st_mtime_ns for f in (self.out/'data/parquet').rglob('*.parquet')}
        state = release(self.up, self.out)
        self.assertEqual(state['plan'], {'keep': 2, 'prune': 0, 'extract': 0})
        self.assertEqual(before, {f: f.stat().st_mtime_ns for f in (self.out/'data/parquet').rglob('*.parquet')})
        publish(self.up, '2027-04-14', {
            '2026-02-01': [[work(7, MATH, [6, 3])]],
            '2027-01-10': [[work(1, MATH, title='updated'), work(11, MATH), work(12, MATH, [1, 8])]],
            '2027-04-01': [[work(6, MATH, [99])]],
        }, deleted=[(3, '2026-12-01')], merged=[(8, 11, '2026-12-05')])
        release(self.up, self.out)
        self.assertEqual(ids(self.out), {'2026-02-01': [7], '2027-01-10': [1, 11, 12], '2027-04-01': [6]})
        self.assertEqual(ids(self.out, 'citations')['2027-04-01'], [(6, 7)])
        self.assertEqual([r['work_id'] for r in ledger(self.out, 'deleted_ids.csv.gz')], [f'{W}3'])

    def test_manifest_change_during_run_fails(self):
        publish(self.up, '2026-10-14', {'2026-01-01': [[work(1, MATH)]]})
        upstream = om.Upstream(str(self.up))
        publish(self.up, '2026-10-15', {'2026-01-01': [[work(1, MATH)]]})
        with self.assertRaises(RuntimeError):
            om.Release(upstream, self.out).run()
        self.assertFalse((self.out/'data/parquet/manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
