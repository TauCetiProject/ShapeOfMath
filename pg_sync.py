"""Copy a collection between SQLite and PostgreSQL, and verify the copy.

    python pg_sync.py import archive/math.sqlite postgresql://...   # into an empty database
    python pg_sync.py export postgresql://... snapshot.sqlite       # to a new SQLite file

Export writes a consistent SQLite snapshot (one repeatable-read transaction) for
tools that still read the collection as a file, such as
`curation/prepare_task.py --db snapshot.sqlite`.

On import, the SQLite file is first copied with SQLite's backup API, so a collection that
curation agents are still writing yields one consistent state. Rows keep their
IDs. User triggers are disabled during the copy: imported review flags and
revisions are recorded judgments, not consequences of inserting edges now.
Identity sequences then continue after the largest imported ID.

Verification compares every table row by row (as unordered multisets), the
`verify()` report, and the statement and proof cones of a sample of concepts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import time

import mathdb as m

# Parents before children, so foreign keys hold row by row.
TABLES = (
    'formalization_library', 'concept', 'concept_alias', 'source', 'source_identifier',
    'citation', 'citation_identifier', 'source_artifact', 'concept_dependency', 'source_concept',
    'concept_related', 'source_relation', 'embedding_model', 'concept_embedding', 'curation_event',
    'formalization_file', 'concept_formalization', 'concept_formalization_file',
)
IDENTITY_TABLES = (
    'citation', 'source_artifact', 'concept_dependency', 'source_concept', 'concept_related',
    'source_relation', 'curation_event', 'formalization_file', 'concept_formalization',
)


def consistent_copy(path: Path, directory: Path) -> Path:
    target = directory / 'collection.sqlite'
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as live, \
            closing(sqlite3.connect(target)) as private:
        live.backup(private)
    return target


def copy(source: sqlite3.Connection, target) -> dict[str, int]:
    raw = target._conn  # psycopg connection behind the adapter
    counts = {}
    with raw.transaction():
        raw.execute(f'SELECT pg_advisory_xact_lock({__import__("pgcompat").WRITER_LOCK})')
        for table in TABLES:
            if raw.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() and table != 'formalization_library':
                raise ValueError(f'Target table {table} is not empty')
        for table in TABLES:
            raw.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
        # The schema seeds the two standard libraries; the source has its own rows.
        raw.execute('DELETE FROM formalization_library')
        for table in TABLES:
            columns = [r[1] for r in source.execute(f'PRAGMA table_info({table})')]
            names = ','.join(columns)
            n = 0
            with raw.cursor() as cursor:
                with cursor.copy(f'COPY {table} ({names}) FROM STDIN') as stream:
                    for row in source.execute(f'SELECT {names} FROM {table} ORDER BY rowid'):
                        stream.write_row(tuple(row))
                        n += 1
            counts[table] = n
        for table in IDENTITY_TABLES:
            raw.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), coalesce((SELECT max(id) FROM {table}),0)+1, false)")
        for table in TABLES:
            raw.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
    return counts


def rows(db, table):
    def normal(value):
        return value.hex() if isinstance(value, (bytes, memoryview)) else value
    return Counter(json.dumps([normal(v) for v in r], ensure_ascii=False, sort_keys=True)
                   for r in db.execute(f'SELECT * FROM {table}'))


def compare(source, target, sample=200, seed=0) -> list[str]:
    problems = []
    for table in TABLES:
        a, b = rows(source, table), rows(target, table)
        if a != b:
            problems.append(f'{table}: {sum((a - b).values())} rows only in SQLite, {sum((b - a).values())} only in PostgreSQL')
    if m.verify(source) != m.verify(target):
        problems.append('verify() reports differ')
    slugs = sorted(r[0] for r in source.execute("SELECT slug FROM concept WHERE status='active'"))
    for slug in random.Random(seed).sample(slugs, min(sample, len(slugs))):
        for mode in ('statement', 'proof'):
            left, right = m.prerequisite_cone(source, slug, mode), m.prerequisite_cone(target, slug, mode)
            if json.dumps(left, sort_keys=True, default=str) != json.dumps(right, sort_keys=True, default=str):
                problems.append(f'{mode} cone of {slug} differs')
    return problems


def export(url, out: Path) -> dict[str, int]:
    """Write the PostgreSQL collection to a new SQLite file with the SQLite schema."""
    if out.exists():
        raise ValueError(f'{out} already exists')
    statements, statement = [], ''
    for line in (m.ROOT / 'schema.sql').read_text().splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            statements.append(statement)
            statement = ''
    def code(statement):  # without leading comment lines
        return '\n'.join(line for line in statement.splitlines() if not line.lstrip().startswith('--')).lstrip()
    triggers = [x for x in statements if code(x).upper().startswith('CREATE TRIGGER')]
    counts = {}
    partial = out.with_name(out.name + '.partial')
    partial.unlink(missing_ok=True)
    with closing(m.connect(url)) as source, closing(sqlite3.connect(partial)) as target:
        source._conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            # Create tables first and triggers last, so copied review flags and
            # revisions are not reset by the triggers that guard later edits.
            for x in statements:
                if x not in triggers:
                    target.execute(x)
            target.execute('DELETE FROM formalization_library')
            for table in TABLES:
                columns = [r[1] for r in target.execute(f'PRAGMA table_info({table})')]
                names = ','.join(columns)
                key = ','.join(r[1] for r in sorted(target.execute(f'PRAGMA table_info({table})'), key=lambda r: r[5]) if r[5]) or names
                rows = source.execute(f'SELECT {names} FROM {table} ORDER BY {key}').fetchall()
                target.executemany(f'INSERT INTO {table} ({names}) VALUES ({",".join("?" * len(columns))})',
                                   [tuple(bytes(v) if isinstance(v, memoryview) else v for v in r) for r in rows])
                counts[table] = len(rows)
            for x in triggers:
                target.execute(x)
            target.commit()
        finally:
            source._conn.execute('ROLLBACK')
    partial.rename(out)
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('import', 'export'))
    parser.add_argument('source', help='import: SQLite file; export: PostgreSQL URL')
    parser.add_argument('target', help='import: PostgreSQL URL; export: new SQLite file')
    parser.add_argument('--sample', type=int, default=200, help='concepts whose cones are compared')
    args = parser.parse_args(argv)
    started = time.time()
    if args.command == 'export':
        out = Path(args.target)
        counts = export(args.source, out)
        print(json.dumps({'exported': counts, 'seconds': round(time.time() - started, 1)}))
        with closing(m.connect(out)) as copy, closing(m.connect(args.source)) as live:
            problems = compare(copy, live, args.sample)
        print(json.dumps({'problems': problems}, ensure_ascii=False))
        return 1 if problems else 0
    with tempfile.TemporaryDirectory() as temp:
        path = consistent_copy(Path(args.source), Path(temp))
        with closing(m.connect(path)) as source, closing(m.connect(args.target)) as target:
            m.initialize(target)
            counts = copy(source, target)
            print(json.dumps({'copied': counts, 'seconds': round(time.time() - started, 1)}))
            started = time.time()
            problems = compare(source, target, args.sample)
            print(json.dumps({'problems': problems, 'compare_seconds': round(time.time() - started, 1)}, ensure_ascii=False))
            return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
