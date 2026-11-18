"""Run the unittest suite against PostgreSQL instead of SQLite.

    MATHDB_TEST_POSTGRES=postgresql://postgres@/postgres?host=/tmp/shapeofmath-pg \
        python tests/run_postgres.py [unittest arguments]

Tests open databases by filesystem path. This runner maps each distinct path to
its own PostgreSQL database, cloned from an initialized template, so the suite
runs unchanged. Tests of SQLite file migrations do not apply to PostgreSQL and
are skipped by name below. Every database the run creates is dropped at the end.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import psycopg  # noqa: E402

import mathdb  # noqa: E402

ADMIN = os.environ['MATHDB_TEST_POSTGRES']
TEMPLATE = 'mathdb_test_template'
created: list[str] = []
original_connect = mathdb.connect


def database_url(name: str) -> str:
    parts = urlsplit(ADMIN)
    return urlunsplit((parts.scheme, parts.netloc, '/' + name, parts.query, parts.fragment))


def admin(sql: str) -> None:
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(sql)


def prepare_template() -> None:
    admin(f'DROP DATABASE IF EXISTS {TEMPLATE}')
    admin(f'CREATE DATABASE {TEMPLATE}')
    db = original_connect(database_url(TEMPLATE))
    mathdb.initialize(db)
    db.close()


def connect(path=mathdb.DEFAULT_DB):
    if str(path).startswith(('postgres://', 'postgresql://')):
        return original_connect(path)
    memory = str(path) == ':memory:'
    key = f':memory:{len(created)}' if memory else str(Path(path).resolve())
    name = 'mathdb_test_' + hashlib.sha1(key.encode()).hexdigest()[:20]
    if name not in created:
        admin(f'DROP DATABASE IF EXISTS {name}')
        admin(f'CREATE DATABASE {name} TEMPLATE {TEMPLATE}')
        created.append(name)
        if not memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).touch()
    return original_connect(database_url(name))


SQLITE_ONLY = (
    # Upgrades of SQLite files from earlier schema versions.
    'migrat', 'legacy', 'v1_', 'v2_', 'archived',
)
# These modules drive tools that read or copy the live database as an SQLite
# file (task packages, freezes, the 2015 coordinators, one-off imports). Their
# task snapshots need a subgraph format before they can work at scale; see
# docs/SCALING.md.
SQLITE_FILE_TOOLING = (
    'test_curation_plans.', 'test_curation_task_package.', 'test_curation_freeze.',
    'test_sample_corrections.', 'test_coverage_update_import.',
)


def skip_sqlite_only(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            skip_sqlite_only(test)
            continue
        reason = ('SQLite file migration' if any(word in test.id().lower() for word in SQLITE_ONLY) else
                  'tool reads the live database as an SQLite file' if test.id().startswith(SQLITE_FILE_TOOLING) else None)
        if reason:
            setattr(test, test._testMethodName, unittest.skip(reason)(getattr(test, test._testMethodName)))


def main() -> int:
    prepare_template()
    mathdb.connect = connect
    try:
        loader = unittest.TestLoader()
        names = sys.argv[1:]
        suite = loader.loadTestsFromNames(names) if names else loader.discover(str(ROOT / 'tests'))
        skip_sqlite_only(suite)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        for name in created:
            admin(f'DROP DATABASE IF EXISTS {name} WITH (FORCE)')
        admin(f'DROP DATABASE IF EXISTS {TEMPLATE}')


if __name__ == '__main__':
    sys.exit(main())
