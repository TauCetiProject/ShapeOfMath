"""Load key columns of an OpenAlex mathematics release into PostgreSQL.

python openalex_pg.py load --release DIR --url-file ~/.config/shapeofmath/neon.env

DIR is a local copy of a release written by openalex_math.py (the directory holding
data/parquet). The tables are built in schema `<schema>_load`, checked against the
release manifests, then swapped in for `<schema>` in one transaction, so readers see
either the previous release or the new one. Requires the `openalex` and `postgres`
extras. See docs/OPENALEX_MATH.md.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import sys
import time

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from openalex_math import work_ints

ARXIV = re.compile(r'(?:arxiv(?:\.org/(?:abs|pdf)/|:)|10\.48550/arxiv\.|oai:arxiv\.org:)'
                   r'(\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?', re.I)
READ_ROLES = ('curator', 'reader')
WORK_COLUMNS = ['id', 'doi', 'title', 'publication_year', 'publication_date', 'type', 'language',
                'primary_location', 'primary_topic', 'authorships', 'cited_by_count', 'referenced_works',
                'is_retracted', 'is_paratext', 'open_access', 'best_oa_location', 'locations', 'updated_date']


def ddl(schema):
    return f'''
CREATE SCHEMA {schema};
COMMENT ON SCHEMA {schema} IS 'OpenAlex mathematics works (CC0), loaded by openalex_pg.py; see docs/OPENALEX_MATH.md';
CREATE TABLE {schema}.release (
  upstream_date date NOT NULL, upstream_manifest_sha256 text NOT NULL, filter jsonb NOT NULL,
  works bigint NOT NULL, citations bigint NOT NULL, loaded_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE {schema}.work (
  id bigint NOT NULL,                 -- OpenAlex W number
  doi text,                           -- lowercase, without https://doi.org/
  arxiv_ids text[] NOT NULL,          -- found in the DOI and location identifiers/URLs
  title text,
  publication_year integer,
  publication_date date,
  type text,
  language text,
  source_id bigint,                   -- primary location source (S number)
  source_name text,
  source_issn_l text,
  source_type text,
  primary_topic_id bigint,            -- T number
  primary_topic text,
  subfield_id integer,
  subfield text,
  authors jsonb NOT NULL,             -- [{{"id": A number, "name", "orcid"}}] in author order
  cited_by_count integer,
  referenced_works bigint[] NOT NULL, -- outgoing references (any field)
  is_retracted boolean,
  is_paratext boolean,
  is_oa boolean,
  oa_status text,
  oa_url text,
  best_oa_pdf_url text,
  best_oa_landing_page_url text,
  best_oa_version text,
  best_oa_license text,
  updated_date date NOT NULL);        -- the release partition holding the record
CREATE TABLE {schema}.citation (
  cited_work_id bigint NOT NULL,      -- a work in {schema}.work
  citing_work_id bigint NOT NULL);    -- any non-xpac OpenAlex work
'''


def indexes(schema):
    return f'''
ALTER TABLE {schema}.work ADD PRIMARY KEY (id);
ALTER TABLE {schema}.citation ADD PRIMARY KEY (cited_work_id, citing_work_id);
CREATE INDEX ON {schema}.citation (citing_work_id);
CREATE INDEX ON {schema}.work (doi);
CREATE INDEX ON {schema}.work USING gin (arxiv_ids);
CREATE INDEX ON {schema}.work (source_id);
ANALYZE {schema}.work;
ANALYZE {schema}.citation;
'''


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, file=sys.stderr, flush=True)


def tail_int(value):
    """Trailing number of an OpenAlex URL id (https://openalex.org/S123 -> 123)."""
    if not value:
        return None
    match = re.search(r'(\d+)$', value)
    return int(match.group(1)) if match else None


def bare_doi(value):
    if not value:
        return None
    return value.lower().removeprefix('https://doi.org/').removeprefix('http://doi.org/')


def arxiv_ids(row):
    found = []
    places = [row.get('doi')]
    for location in row.get('locations') or []:
        places.extend(location.get(k) for k in ('id', 'doi', 'landing_page_url', 'pdf_url'))
    for value in places:
        for match in ARXIV.finditer(value or ''):
            ident = match.group(1)
            ident = ident.lower() if '/' in ident else ident
            if ident not in found:
                found.append(ident)
    return found


def work_row(r):
    source = (r.get('primary_location') or {}).get('source') or {}
    topic = r.get('primary_topic') or {}
    subfield = topic.get('subfield') or {}
    oa = r.get('open_access') or {}
    best = r.get('best_oa_location') or {}
    authors = [{'id': tail_int(a['author'].get('id')), 'name': a['author'].get('display_name'),
                'orcid': (a['author'].get('orcid') or '').removeprefix('https://orcid.org/') or None}
               for a in r.get('authorships') or [] if a.get('author')]
    return (tail_int(r['id']), bare_doi(r.get('doi')), arxiv_ids(r), r.get('title'), r.get('publication_year'),
            r.get('publication_date'), r.get('type'), r.get('language'), tail_int(source.get('id')),
            source.get('display_name'), source.get('issn_l'), source.get('type'), tail_int(topic.get('id')),
            topic.get('display_name'), tail_int(subfield.get('id')), subfield.get('display_name'),
            json.dumps(authors, ensure_ascii=False, separators=(',', ':')), r.get('cited_by_count'),
            [tail_int(w) for w in r.get('referenced_works') or []], r.get('is_retracted'), r.get('is_paratext'),
            oa.get('is_oa'), oa.get('oa_status'), oa.get('oa_url'), best.get('pdf_url'), best.get('landing_page_url'),
            best.get('version'), best.get('license'), r['updated_date'].date())


WORK_FIELDS = ('id, doi, arxiv_ids, title, publication_year, publication_date, type, language, source_id, '
               'source_name, source_issn_l, source_type, primary_topic_id, primary_topic, subfield_id, subfield, '
               'authors, cited_by_count, referenced_works, is_retracted, is_paratext, is_oa, oa_status, oa_url, '
               'best_oa_pdf_url, best_oa_landing_page_url, best_oa_version, best_oa_license, updated_date')


def manifest_files(release, entity):
    manifest = json.loads((release/'data/parquet'/entity/'manifest.json').read_text())
    files = []
    for entry in manifest['files']:
        rel = entry['url'][entry['url'].index(f'/{entity}/')+1:]
        files.append((release/'data/parquet'/rel, entry['meta']['record_count']))
    return manifest, files


def load(release, url, schema='openalex', limit_files=None):
    import psycopg
    release = Path(release)
    combined = json.loads((release/'data/parquet/manifest.json').read_text())
    works_manifest, work_files = manifest_files(release, 'works')
    cites_manifest, cite_files = manifest_files(release, 'citations')
    if limit_files:
        work_files, cite_files = work_files[:limit_files], cite_files[:limit_files]
    expected_works = sum(n for _, n in work_files)
    expected_cites = sum(n for _, n in cite_files)
    staging = schema+'_load'
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET maintenance_work_mem = '2GB'")
        conn.execute(f'DROP SCHEMA IF EXISTS {staging} CASCADE')
        conn.execute(ddl(staging))
        n = 0
        with conn.cursor() as cur, cur.copy(f'COPY {staging}.work ({WORK_FIELDS}) FROM STDIN') as copy:
            for i, (path, _) in enumerate(work_files):
                table = pq.read_table(path, columns=WORK_COLUMNS)
                for batch in table.to_batches(20000):
                    for r in batch.to_pylist():
                        copy.write_row(work_row(r)); n += 1
                if i % 20 == 0:
                    log(f'works: {i+1}/{len(work_files)} files, {n} rows')
        log(f'works loaded: {n}')
        m = 0
        with conn.cursor() as cur, cur.copy(f'COPY {staging}.citation (cited_work_id, citing_work_id) FROM STDIN (FORMAT csv)') as copy:
            for i, (path, _) in enumerate(cite_files):
                t = pq.read_table(path)
                ints = pa.table({'a': work_ints(t['cited_work_id']), 'b': work_ints(t['citing_work_id'])})
                buffer = io.BytesIO()
                pacsv.write_csv(ints, buffer, write_options=pacsv.WriteOptions(include_header=False))
                copy.write(buffer.getvalue()); m += ints.num_rows
                if i % 50 == 0:
                    log(f'citations: {i+1}/{len(cite_files)} files, {m} rows')
        log(f'citations loaded: {m}; building indexes')
        conn.execute(indexes(staging))
        got_works = conn.execute(f'SELECT count(*) FROM {staging}.work').fetchone()[0]
        got_cites = conn.execute(f'SELECT count(*) FROM {staging}.citation').fetchone()[0]
        if (got_works, got_cites) != (expected_works, expected_cites):
            raise RuntimeError(f'Row counts {got_works}, {got_cites} differ from manifests {expected_works}, {expected_cites}')
        dangling = conn.execute(f'SELECT count(*) FROM {staging}.citation c WHERE NOT EXISTS '
                                f'(SELECT 1 FROM {staging}.work w WHERE w.id = c.cited_work_id)').fetchone()[0]
        if dangling and not limit_files:
            raise RuntimeError(f'{dangling} citations point outside {staging}.work')
        conn.execute(f'INSERT INTO {staging}.release (upstream_date, upstream_manifest_sha256, filter, works, citations) '
                     'VALUES (%s, %s, %s, %s, %s)',
                     (combined['source']['upstream_date'], combined['source']['upstream_manifest_sha256'],
                      json.dumps(combined['source']['filter']), got_works, got_cites))
        with conn.transaction():
            conn.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
            conn.execute(f'ALTER SCHEMA {staging} RENAME TO {schema}')
            for role in READ_ROLES:
                if conn.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,)).fetchone():
                    conn.execute(f'GRANT USAGE ON SCHEMA {schema} TO {role}')
                    conn.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}')
        size = conn.execute("SELECT pg_size_pretty(sum(pg_total_relation_size(c.oid))) FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind = 'r'",
                            (schema,)).fetchone()[0]
        log(f'{schema}: {got_works} works, {got_cites} citations, {size}')
        return {'works': got_works, 'citations': got_cites, 'size': size}


def read_url(path):
    for line in Path(path).expanduser().read_text().splitlines():
        line = line.strip()
        if line.startswith('POSTGRES_URL='):
            return line.split('=', 1)[1].strip().strip('\'"')
        if line.startswith('postgres'):
            return line.strip('\'"')
    raise ValueError(f'No PostgreSQL URL in {path}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('load')
    p.add_argument('--release', required=True, help='local release directory (contains data/parquet)')
    p.add_argument('--url-file', required=True,
                   help='file holding the PostgreSQL URL of a role that may create schemas (a bare URL, or POSTGRES_URL=...)')
    p.add_argument('--schema', default='openalex')
    p.add_argument('--limit-files', type=int, help='load only the first N files of each entity (for trials)')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(load(args.release, read_url(args.url_file), args.schema, args.limit_files)))
    except Exception as error:  # never echo the connection URL
        message = re.sub(r'postgres(?:ql)?://\S+', '<url>', str(error))
        sys.exit(f'{type(error).__name__}: {message}')


if __name__ == '__main__':
    main()
