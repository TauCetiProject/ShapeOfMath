"""Republish the mathematics works of the OpenAlex snapshot, with incoming citations.

python openalex_math.py release --upstream s3://openalex/data/parquet --out DIR \
    --publish-url s3://BUCKET/data/parquet

DIR holds the previous release (or nothing, for the first run) and is updated in
place. See docs/OPENALEX_MATH.md for the selection rule, layout and sync procedure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.fs as pafs
import pyarrow.parquet as pq

MATH_FIELD = 'https://openalex.org/fields/26'
WORK_PREFIX = 'https://openalex.org/W'
MAX_PART = 400_000
FILTER = {'primary_topic.field.id': MATH_FIELD, 'is_xpac': False}
PARTITION = re.compile(r'/updated_date=(\d{4}-\d{2}-\d{2})/')
EMPTY = np.zeros(0, dtype=np.int64)


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, file=sys.stderr, flush=True)


def filesystem(uri):
    if uri.startswith('s3://'):
        return pafs.S3FileSystem(anonymous=True, region='us-east-1'), uri[5:].rstrip('/')
    return pafs.LocalFileSystem(), str(Path(uri).resolve())


def read_bytes(fs, path):
    with fs.open_input_stream(path, compression=None) as f:
        return f.read()


def exists(fs, path):
    return fs.get_file_info(path).type == pafs.FileType.File


def work_ints(ids):
    """Map URL-form work ids to int64 (W123 -> 123); every id must be a work id."""
    chunks = ids.chunks if isinstance(ids, pa.ChunkedArray) else [ids]
    out = []
    for chunk in chunks:
        chunk = pc.cast(chunk, pa.string())
        if len(chunk) and not pc.all(pc.starts_with(chunk, WORK_PREFIX)).as_py():
            raise ValueError('Unexpected non-work id in works data')
        out.append(pc.cast(pc.utf8_slice_codeunits(chunk, len(WORK_PREFIX)), pa.int64()).to_numpy(zero_copy_only=False))
    return np.concatenate(out) if out else EMPTY


def work_urls(ints):
    return pc.binary_join_element_wise(WORK_PREFIX, pc.cast(pa.array(ints), pa.string()), '')


def member(sorted_values, xs):
    """Boolean mask of xs in sorted_values (both int64 numpy arrays)."""
    if not len(sorted_values) or not len(xs):
        return np.zeros(len(xs), dtype=bool)
    pos = np.minimum(np.searchsorted(sorted_values, xs), len(sorted_values)-1)
    return sorted_values[pos] == xs


def math_mask(table):
    field = pc.struct_field(pc.struct_field(table['primary_topic'], 'field'), 'id')
    xpac = pc.fill_null(table['is_xpac'], False)
    return pc.and_(pc.fill_null(pc.equal(field, MATH_FIELD), False), pc.invert(xpac))


def row_groups(fs, path, columns):
    with fs.open_input_file(path) as f:
        pf = pq.ParquetFile(f)
        for i in range(pf.metadata.num_row_groups):
            yield pf.read_row_group(i, columns=columns)


class Upstream:
    def __init__(self, uri):
        self.uri = uri
        self.fs, self.root = filesystem(uri)
        self.manifest_bytes = read_bytes(self.fs, self.root+'/works/manifest.json')
        self.manifest = json.loads(self.manifest_bytes)
        self.files = []
        for entry in self.manifest['files']:
            url = entry['url']
            match = PARTITION.search(url)
            if not match:
                raise ValueError(f'Upstream file outside an updated_date partition: {url}')
            rel = url[url.index('/works/')+len('/works/'):]
            self.files.append({'path': self.root+'/works/'+rel, 'partition': match.group(1),
                               'records': entry['meta']['record_count'], 'bytes': entry['meta']['content_length']})

    def ledger(self, name):
        path = self.root+'/works/'+name
        if not exists(self.fs, path):
            return None
        data = read_bytes(self.fs, path)
        if name.endswith('.gz'):
            data = gzip.decompress(data)
        return pacsv.read_csv(io.BytesIO(data), convert_options=pacsv.ConvertOptions(
            column_types={'deleted_date': pa.string(), 'merge_date': pa.string()}))

    def check_unchanged(self):
        if read_bytes(self.fs, self.root+'/works/manifest.json') != self.manifest_bytes:
            raise RuntimeError('Upstream works manifest changed during the run; rerun against the new release')


class Release:
    def __init__(self, upstream, out, publish_url=None, workers=4, refresh=False):
        self.up = upstream
        self.out = Path(out)
        self.data = self.out/'data/parquet'
        self.publish_url = (publish_url or str(self.data.resolve())).rstrip('/')
        self.workers = workers
        self.refresh = refresh
        state = self.out/'state.json'
        self.prev = json.loads(state.read_text()) if state.exists() else {'works': {}, 'citations': {}}
        self.tmp = self.out/'tmp'
        self.before = {}
        self.before = {p: self.prev_ids(p) for p in self.prev['works']}
        self.before_ledger = self.prev_ledger_ids()

    # ---- previous release -------------------------------------------------
    def prev_ids(self, partition):
        if partition in self.before:
            return self.before[partition]
        files = self.prev['works'].get(partition, {}).get('files', [])
        ids = [work_ints(pq.read_table(self.data/'works'/f'updated_date={partition}'/f['name'], columns=['id'])['id'])
               for f in files]
        return np.sort(np.concatenate(ids)) if ids else EMPTY

    # ---- pass 1: math identities in every upstream partition ---------------
    def scan_identities(self, file):
        found = []
        for t in row_groups(self.up.fs, file['path'], ['id', 'is_xpac', 'primary_topic']):
            found.append(work_ints(t['id'].filter(math_mask(t))))
        return np.concatenate(found) if found else EMPTY

    # ---- pass 2: citations, plus full rows for re-extracted partitions -----
    def scan_records(self, index, file, extract):
        columns = None if extract else ['id', 'is_xpac', 'referenced_works']
        cited, citing, kept = [], [], []
        for t in row_groups(self.up.fs, file['path'], columns):
            live = pc.invert(pc.fill_null(t['is_xpac'], False))
            refs = t['referenced_works'].filter(live).combine_chunks()
            ids = work_ints(t['id'].filter(live))
            flat = pc.list_flatten(refs)
            if len(flat):
                parents = pc.list_parent_indices(refs).to_numpy(zero_copy_only=False)
                targets = self.resolve(work_ints(flat))
                hit = member(self.math_ids, targets)
                cited.append(targets[hit]); citing.append(ids[parents[hit]])
            if extract:
                rows = t.filter(math_mask(t))
                if rows.num_rows:
                    kept.append(rows)
        if kept:
            target = self.tmp/file['partition']
            target.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.concat_tables(kept, promote_options='permissive'),
                           target/f'{index:05d}.parquet', compression='zstd')
        return (np.concatenate(cited) if cited else EMPTY, np.concatenate(citing) if citing else EMPTY)

    def resolve(self, ids):
        if not len(self.merge_from):
            return ids
        hit = member(self.merge_from, ids)
        if hit.any():
            ids = ids.copy()
            ids[hit] = self.merge_to[np.searchsorted(self.merge_from, ids[hit])]
        return ids

    # ---- writing ----------------------------------------------------------
    def write_parts(self, entity, partition, table):
        """Write table as part files (at most MAX_PART rows each); return file metadata."""
        target = self.data/entity/f'updated_date={partition}'
        if target.exists():
            shutil.rmtree(target)
        files = []
        if not table.num_rows:
            return files
        target.mkdir(parents=True)
        for n, start in enumerate(range(0, table.num_rows, MAX_PART)):
            name = f'part_{n:04d}.parquet'
            part = table.slice(start, MAX_PART)
            pq.write_table(part, target/name, compression='zstd', compression_level=9)
            files.append({'name': name, 'record_count': part.num_rows, 'content_length': (target/name).stat().st_size})
        return files

    def run(self):
        up = self.up
        for manifest in [self.data/'manifest.json', self.data/'works/manifest.json', self.data/'citations/manifest.json']:
            manifest.unlink(missing_ok=True)  # present = release complete, as upstream
        if self.tmp.exists():
            shutil.rmtree(self.tmp)
        partitions = sorted({f['partition'] for f in up.files})
        log(f'upstream {up.manifest["date"]}: {len(up.files)} files, {len(partitions)} partitions')

        merged = up.ledger('merged_ids.csv.gz')
        if merged is not None:
            frm, to = work_ints(merged['id']), work_ints(merged['merge_into_id'])
            order = np.argsort(frm)
            self.merge_from, self.merge_to = frm[order], to[order]
        else:
            self.merge_from = self.merge_to = EMPTY

        with ThreadPoolExecutor(self.workers) as pool:
            found = list(pool.map(self.scan_identities, up.files))
        math_by_partition = {p: [] for p in partitions}
        for file, ids in zip(up.files, found):
            math_by_partition[file['partition']].append(ids)
        math_by_partition = {p: np.sort(np.concatenate(v)) if v else EMPTY for p, v in math_by_partition.items()}

        # Classify every partition by content: unchanged, shrunk (prune) or needing extraction.
        plan = {}
        for p in partitions:
            now, before = math_by_partition[p], self.prev_ids(p)
            if not len(now) and not len(before):
                continue  # no mathematics works, before or now
            if self.refresh or not np.isin(now, before).all():
                plan[p] = 'extract'
            elif len(now) == len(before):
                plan[p] = 'keep'
            else:
                plan[p] = 'prune'
        counts = {k: sum(1 for v in plan.values() if v == k) for k in ['keep', 'prune', 'extract']}
        log('partitions:', counts)

        all_ids = np.concatenate([math_by_partition[p] for p in partitions]) if partitions else EMPTY
        all_codes = np.concatenate([np.full(len(math_by_partition[p]), i) for i, p in enumerate(partitions)]) if partitions else EMPTY
        order = np.argsort(all_ids)
        self.math_ids, self.math_codes = all_ids[order], all_codes[order]
        if len(self.math_ids) > 1 and (np.diff(self.math_ids) == 0).any():
            raise ValueError('A work id appears in more than one upstream partition')
        log(f'{len(self.math_ids)} mathematics works')

        with ThreadPoolExecutor(self.workers) as pool:
            jobs = [pool.submit(self.scan_records, i, f, plan.get(f['partition']) == 'extract') for i, f in enumerate(up.files)]
            edges = [j.result() for j in jobs]
        cited = np.concatenate([e[0] for e in edges]) if edges else EMPTY
        citing = np.concatenate([e[1] for e in edges]) if edges else EMPTY
        log(f'{len(cited)} citation links into mathematics works (before deduplication)')

        works_state = {}
        for p in plan:
            if plan[p] == 'keep':
                works_state[p] = self.prev['works'][p]
            elif plan[p] == 'prune':
                old = [pq.read_table(self.data/'works'/f'updated_date={p}'/f['name']) for f in self.prev['works'][p]['files']]
                table = pa.concat_tables(old, promote_options='permissive')
                keep = member(math_by_partition[p], work_ints(table['id']))
                works_state[p] = {'files': self.write_parts('works', p, table.filter(pa.array(keep)))}
            else:
                pieces = sorted((self.tmp/p).glob('*.parquet')) if (self.tmp/p).exists() else []
                table = pa.concat_tables([pq.read_table(x) for x in pieces], promote_options='permissive') if pieces else pa.table({})
                if table.num_rows != len(math_by_partition[p]):
                    raise RuntimeError(f'Partition {p}: extracted {table.num_rows} rows, identity scan found {len(math_by_partition[p])}')
                works_state[p] = {'files': self.write_parts('works', p, table)}
            if not works_state[p]['files']:
                del works_state[p]
        self.remove_stale('works', works_state)

        citations_state = {}
        codes = self.math_codes[np.searchsorted(self.math_ids, cited)] if len(cited) else EMPTY
        order = np.lexsort((citing, cited, codes))
        codes, cited, citing = codes[order], cited[order], citing[order]
        if len(cited):
            unique = np.ones(len(cited), dtype=bool)
            unique[1:] = (cited[1:] != cited[:-1]) | (citing[1:] != citing[:-1])
            codes, cited, citing = codes[unique], cited[unique], citing[unique]
        bounds = np.searchsorted(codes, np.arange(len(partitions)+1))
        for i, p in enumerate(partitions):
            a, b = cited[bounds[i]:bounds[i+1]], citing[bounds[i]:bounds[i+1]]
            if not len(a):
                continue
            digest = hashlib.sha256(a.tobytes()+b'|'+b.tobytes()).hexdigest()
            old = self.prev['citations'].get(p)
            if old and old.get('sha256') == digest and (self.data/'citations'/f'updated_date={p}').exists():
                citations_state[p] = old
                continue
            table = pa.table({'cited_work_id': work_urls(a), 'citing_work_id': work_urls(b)})
            citations_state[p] = {'files': self.write_parts('citations', p, table), 'sha256': digest}
        self.remove_stale('citations', citations_state)
        log(f'{len(cited)} distinct citation links')

        published_before = set(self.prev['works'])
        ever = np.unique(np.concatenate([self.prev_ids_all(published_before), self.before_ledger]))
        current = np.sort(np.concatenate([math_by_partition[p] for p in works_state])) if works_state else EMPTY
        merged_rows = self.write_merged(merged, ever)
        self.write_deleted(up.ledger('deleted_ids.csv.gz'), current, merged_rows)

        shutil.rmtree(self.tmp, ignore_errors=True)
        up.check_unchanged()
        state = {'version': 1, 'upstream_date': up.manifest['date'], 'upstream_manifest_sha256':
                 hashlib.sha256(up.manifest_bytes).hexdigest(), 'filter': FILTER, 'plan': counts,
                 'works': works_state, 'citations': citations_state}
        (self.out/'state.json').write_text(json.dumps(state, indent=1, sort_keys=True)+'\n')
        self.write_manifests(state)
        log('release complete')
        return state

    def prev_ids_all(self, partitions):
        ids = [self.prev_ids(p) for p in partitions]
        return np.concatenate(ids) if ids else EMPTY

    def prev_ledger_ids(self):
        ids = []
        for name in ['deleted_ids.csv.gz', 'merged_ids.csv.gz']:
            path = self.data/'works'/name
            if path.exists():
                table = pacsv.read_csv(path)
                ids.append(work_ints(table[table.column_names[0]]))
        return np.concatenate(ids) if ids else EMPTY

    def remove_stale(self, entity, keep):
        root = self.data/entity
        if root.exists():
            for d in root.glob('updated_date=*'):
                if d.name.split('=', 1)[1] not in keep:
                    shutil.rmtree(d)

    def write_merged(self, upstream_merged, ever):
        """Merge ledger restricted to ids this dataset has ever published (cumulative upstream)."""
        path = self.data/'works/merged_ids.csv.gz'
        if upstream_merged is None:
            if path.exists():
                return pacsv.read_csv(path)
            return None
        rows = upstream_merged.filter(pa.array(member(ever, work_ints(upstream_merged['id']))))
        write_csv_gz(path, rows)
        return rows

    def write_deleted(self, upstream_deleted, current, merged_rows):
        """Cumulative ledger of ids that left this dataset: deleted upstream or no longer selected."""
        path = self.data/'works/deleted_ids.csv.gz'
        ledger = {}
        if path.exists():
            for row in pacsv.read_csv(path, convert_options=pacsv.ConvertOptions(
                    column_types={'deleted_date': pa.string()})).to_pylist():
                ledger[row['work_id']] = row['deleted_date']
        before = self.prev_ids_all(set(self.prev['works']))
        gone = before[~member(current, before)]
        dates = {}
        if upstream_deleted is not None:
            up_ids = work_ints(upstream_deleted['work_id'])
            hit = member(np.sort(gone), up_ids)
            for wid, date in zip(up_ids[hit].tolist(), upstream_deleted['deleted_date'].filter(pa.array(hit)).to_pylist()):
                dates[wid] = date
        merged = set(work_ints(merged_rows['id']).tolist()) if merged_rows is not None else set()
        for wid in gone.tolist():
            if wid not in merged:
                ledger.setdefault(WORK_PREFIX+str(wid), dates.get(wid, self.up.manifest['date']))
        restored = set(work_urls(current).to_pylist()) if len(current) else set()
        rows = sorted((k, v) for k, v in ledger.items() if k not in restored)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv_gz(path, pa.table({'work_id': pa.array([r[0] for r in rows], pa.string()),
                                     'deleted_date': pa.array([r[1] for r in rows], pa.string())}))

    def write_manifests(self, state):
        entities = []
        for entity in ['works', 'citations']:
            files = []
            for p in sorted(state[entity]):
                for f in state[entity][p]['files']:
                    files.append({'url': f'{self.publish_url}/{entity}/updated_date={p}/{f["name"]}',
                                  'meta': {'content_length': f['content_length'], 'record_count': f['record_count']}})
            manifest = {'date': state['upstream_date'], 'format': 'parquet', 'entity': entity,
                        'record_count': sum(f['meta']['record_count'] for f in files),
                        'content_length': sum(f['meta']['content_length'] for f in files), 'files': files}
            (self.data/entity).mkdir(parents=True, exist_ok=True)
            (self.data/entity/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
            entities.append(manifest)
        combined = {'date': state['upstream_date'], 'format': 'parquet',
                    'source': {'upstream': 's3://openalex/data/parquet', 'upstream_date': state['upstream_date'],
                               'upstream_manifest_sha256': state['upstream_manifest_sha256'], 'filter': FILTER},
                    'meta': {'record_count': sum(e['record_count'] for e in entities),
                             'content_length': sum(e['content_length'] for e in entities)},
                    'entities': entities}
        (self.data/'manifest.json').write_text(json.dumps(combined, indent=2)+'\n')


def write_csv_gz(path, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    pacsv.write_csv(table, buffer, write_options=pacsv.WriteOptions(quoting_style='needed'))
    path.write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    rel = sub.add_parser('release', help='update DIR to the current upstream release')
    rel.add_argument('--upstream', default='s3://openalex/data/parquet')
    rel.add_argument('--out', required=True)
    rel.add_argument('--publish-url', help='base URL written into manifests (default: local path)')
    rel.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    rel.add_argument('--refresh', action='store_true', help='re-extract every partition from upstream')
    args = parser.parse_args(argv)
    state = Release(Upstream(args.upstream), args.out, args.publish_url, args.workers, args.refresh).run()
    print(json.dumps({'upstream_date': state['upstream_date'], 'plan': state['plan'],
                      'works': sum(f['record_count'] for p in state['works'].values() for f in p['files']),
                      'citations': sum(f['record_count'] for p in state['citations'].values() for f in p['files'])}))


if __name__ == '__main__':
    main()
