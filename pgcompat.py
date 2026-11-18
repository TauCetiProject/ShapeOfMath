"""A PostgreSQL connection with the parts of the sqlite3 interface this project uses.

The audited operations in mathdb.py, the server and the curation tools were
written against Python's sqlite3 module. This adapter lets the same code run on
PostgreSQL (Neon in production) without rewriting every call site:

* `?` placeholders are rewritten to psycopg's `%s` outside string literals.
* Rows support both index and column-name access, and `dict(row)`.
* Transactions follow sqlite3's legacy behaviour: a write outside a transaction
  opens one implicitly, `with db:` commits or rolls back, and plain SELECTs
  outside a transaction autocommit.
* Writers serialize on one transaction-level advisory lock, matching SQLite's
  single-writer model. The cycle check and the API's If-Match version check rely
  on it. `BEGIN IMMEDIATE` takes the lock at once; any other transaction takes it
  before its first write.
* Database errors are re-raised as the sqlite3 exception classes callers catch.
"""
from __future__ import annotations

import re
import sqlite3

import psycopg
from psycopg import adapt, pq

# Any constant shared by every writer; the schema's triggers take the same lock.
WRITER_LOCK = 7307102
_LOCK_SQL = f"SELECT pg_advisory_xact_lock({WRITER_LOCK})"

_WRITE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE|MERGE)\b", re.I)
_WITH_WRITE = re.compile(r"^\s*WITH\b.*\b(?:INSERT|UPDATE|DELETE)\b", re.I | re.S)
_BEGIN = re.compile(r"^\s*BEGIN(?:\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?(?:\s+TRANSACTION)?\s*;?\s*$", re.I)
_SAVEPOINT = re.compile(r"^\s*SAVEPOINT\s+(\w+)\s*;?\s*$", re.I)
_RELEASE = re.compile(r"^\s*RELEASE(?:\s+SAVEPOINT)?\s+(\w+)\s*;?\s*$", re.I)
_TABLE_INFO = re.compile(r"^\s*PRAGMA\s+table_info\((\w+)\)\s*;?\s*$", re.I)
_END = re.compile(r"^\s*(COMMIT|END|ROLLBACK)(?:\s+TRANSACTION)?\s*;?\s*$", re.I)


def translate(sql: str) -> str:
    """Rewrite `?` placeholders to `%s`, escaping literal `%`, outside quotes."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1].replace('%', '%%'))
            i = j + 1
        elif c == '-' and sql.startswith('--', i):
            j = sql.find('\n', i)
            j = n if j < 0 else j
            out.append(sql[i:j].replace('%', '%%'))
            i = j
        elif c == '?':
            out.append('%s')
            i += 1
        elif c == '%':
            out.append('%%')
            i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


class Row(tuple):
    """A tuple that also supports access by column name, like sqlite3.Row."""

    _names: tuple = ()
    _index: dict = {}

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


def _row_factory(cursor):
    names = tuple(c.name for c in cursor.description or ())
    cls = type('Row', (Row,), {'_names': names, '_index': {k: i for i, k in enumerate(names)}})
    return lambda values: cls(values)


class _BoolAsInt(adapt.Dumper):
    """Store Python booleans in the schema's 0/1 INTEGER columns, as sqlite3 does."""
    oid = psycopg.postgres.types['int4'].oid

    def dump(self, obj):
        return b'1' if obj else b'0'


def _convert(error: psycopg.Error) -> sqlite3.Error:
    message = error.diag.message_primary or str(error)
    state = error.sqlstate or ''
    cls = sqlite3.IntegrityError if state.startswith('23') or state == 'P0001' else sqlite3.OperationalError
    converted = cls(message)
    converted.sqlstate = state
    return converted


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone() if self._cursor.description else None

    def fetchall(self):
        return self._cursor.fetchall() if self._cursor.description else []

    def fetchmany(self, size=1):
        return self._cursor.fetchmany(size) if self._cursor.description else []

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        raise NotImplementedError('Use INSERT ... RETURNING id; PostgreSQL has no lastrowid')

    def close(self):
        self._cursor.close()


class Connection:
    backend = 'postgres'

    def __init__(self, url: str):
        self.url = url
        self._conn = psycopg.connect(url, autocommit=True, row_factory=_row_factory)
        self._conn.adapters.register_dumper(bool, _BoolAsInt)
        self._locked = False
        # SQLite lets SAVEPOINT open a transaction that releasing it commits.
        # Names may repeat when savepoints nest; RELEASE pops to the most recent.
        self._savepoints: list[str] = []
        self._savepoint_opened = False

    # sqlite3 compatibility -------------------------------------------------
    row_factory = None  # accepted and ignored; rows always support both access styles

    @property
    def in_transaction(self):
        return self._conn.info.transaction_status != pq.TransactionStatus.IDLE

    def _lock(self):
        if not self._locked:
            self._conn.execute(_LOCK_SQL)
            self._locked = True

    def _run(self, sql, params=None, many=False):
        begin = _BEGIN.match(sql)
        if begin:
            if self.in_transaction:
                raise sqlite3.OperationalError('cannot start a transaction within a transaction')
            self._conn.execute('BEGIN')
            self._reset()
            if (begin.group(1) or '').upper() in ('IMMEDIATE', 'EXCLUSIVE'):
                self._lock()
            return Cursor(self._conn.cursor())
        table_info = _TABLE_INFO.match(sql)
        if table_info:
            # Same columns as SQLite: cid, name, type, notnull, dflt_value, pk.
            cursor = self._conn.cursor()
            cursor.execute("""SELECT a.attnum-1 AS cid, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
                    a.attnotnull::int AS notnull, pg_get_expr(d.adbin, d.adrelid) AS dflt_value,
                    coalesce(array_position(i.indkey::int2[], a.attnum), 0) AS pk
                FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                LEFT JOIN pg_index i ON i.indrelid=a.attrelid AND i.indisprimary
                WHERE a.attrelid=to_regclass(%s) AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum""",
                           (table_info.group(1),))
            return Cursor(cursor)
        savepoint = _SAVEPOINT.match(sql)
        if savepoint:
            if not self.in_transaction:
                self._conn.execute('BEGIN')
                self._locked = False
                self._savepoints = []
                self._savepoint_opened = True
            self._conn.execute(sql)
            self._savepoints.append(savepoint.group(1).lower())
            return Cursor(self._conn.cursor())
        release = _RELEASE.match(sql)
        if release:
            name = release.group(1).lower()
            self._conn.execute(sql)
            if name in self._savepoints:
                del self._savepoints[len(self._savepoints) - 1 - self._savepoints[::-1].index(name):]
            if not self._savepoints and self._savepoint_opened:
                self._conn.execute('COMMIT')
                self._reset()
            return Cursor(self._conn.cursor())
        end = _END.match(sql)
        if end:
            if self.in_transaction:
                self._conn.execute('ROLLBACK' if end.group(1).upper() == 'ROLLBACK' else 'COMMIT')
            self._reset()
            return Cursor(self._conn.cursor())
        if _WRITE.match(sql) or _WITH_WRITE.match(sql):
            if not self.in_transaction:
                self._conn.execute('BEGIN')
                self._locked = False
            self._lock()
        cursor = self._conn.cursor()
        query = translate(sql) if params is not None or many else sql
        if many:
            cursor.executemany(query, params)
        else:
            cursor.execute(query, params)
        return Cursor(cursor)

    def execute(self, sql, params=None):
        try:
            return self._run(sql, tuple(params) if params is not None and not isinstance(params, dict) else params)
        except psycopg.Error as error:
            raise _convert(error) from error

    def executemany(self, sql, seq):
        seq = [tuple(p) for p in seq]
        if not seq:
            return Cursor(self._conn.cursor())
        try:
            return self._run(sql, seq, many=True)
        except psycopg.Error as error:
            raise _convert(error) from error

    def executescript(self, script):
        """Run a multi-statement script in the current transaction (no placeholders)."""
        try:
            if not self.in_transaction:
                self._conn.execute('BEGIN')
                self._locked = False
            self._lock()
            self._conn.execute(script)
        except psycopg.Error as error:
            raise _convert(error) from error

    def commit(self):
        if self.in_transaction:
            try:
                self._conn.execute('COMMIT')
            except psycopg.Error as error:
                raise _convert(error) from error
        self._reset()

    def rollback(self):
        if self.in_transaction:
            self._conn.execute('ROLLBACK')
        self._reset()

    def _reset(self):
        self._locked = False
        self._savepoints = []
        self._savepoint_opened = False

    def close(self):
        self.rollback()
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.commit()
        else:
            self.rollback()
        return False


def is_url(path) -> bool:
    return str(path).startswith(('postgres://', 'postgresql://'))


def connect(url: str) -> Connection:
    return Connection(url)
