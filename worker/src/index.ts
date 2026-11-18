// Public, read-only API and site for The Shape of Math (pipeline.taucetiproject.org).
//
// Each view is a slice of the collection in the /api/v1/state table format,
// holding exactly the rows the browser's renderer reads (web/app.js public mode).
// mathdb_server.py implements the same endpoints; tests/compare_worker.py checks
// that both return identical JSON for the same database.
//
// Every query for a view depends only on the slug, so a view is one HTTP
// transaction to Neon. Responses are cached at the edge under the collection
// version (the newest curation event), so any edit invalidates them.
import { neon, types, type NeonQueryFunction } from '@neondatabase/serverless';

types.setTypeParser(20, (value: string) => Number(value)); // int8: IDs and counts fit in a double

export interface Env {
  POSTGRES_URL: string;
  ASSETS: Fetcher;
  PUBLIC_QUERY_LIMIT?: RateLimit;
}

type Row = Record<string, unknown>;
type Sql = NeonQueryFunction<false, false>;

class HttpError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

const SLICE_TABLES = ['concept', 'concept_alias', 'concept_dependency', 'concept_related', 'source',
  'source_identifier', 'source_concept', 'citation', 'citation_identifier', 'formalization_file'] as const;
const KEYS: Record<string, string[]> = {
  concept_alias: ['concept_id', 'alias'], source_identifier: ['scheme', 'value'],
  citation_identifier: ['citation_id', 'scheme', 'value'],
};

function compare(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  const x = String(a), y = String(b);
  return x < y ? -1 : x > y ? 1 : 0; // code-point order, as PostgreSQL's C.UTF-8 and Python
}

function orderedSlice(tables: Partial<Record<string, Row[]>>): Record<string, Row[]> {
  const out: Record<string, Row[]> = {};
  for (const table of SLICE_TABLES) {
    const unique = new Map<string, Row>();
    for (const row of tables[table] ?? []) unique.set(JSON.stringify(Object.entries(row).sort()), row);
    const keys = KEYS[table] ?? ['id'];
    out[table] = [...unique.values()].sort((a, b) => {
      for (const k of keys) { const c = compare(a[k], b[k]); if (c) return c; }
      return 0;
    });
  }
  return out;
}

// Python's urllib.parse.quote: keep ASCII letters, digits and _.-~ plus `safe`.
function quote(value: string, safe = ''): string {
  let out = '';
  for (const byte of new TextEncoder().encode(value)) {
    const c = String.fromCharCode(byte);
    out += /[A-Za-z0-9_.\-~]/.test(c) || safe.includes(c) ? c : '%' + byte.toString(16).toUpperCase().padStart(2, '0');
  }
  return out;
}

const ROOT_CONCEPT = '(SELECT id FROM concept WHERE slug=$1 OR id=$1)';
const CONCEPT_CONE = `WITH RECURSIVE cone(id) AS (SELECT id FROM concept WHERE (slug=$1 OR id=$1) AND status='active' UNION
  SELECT d.prerequisite_id FROM concept_dependency d JOIN cone ON d.dependent_id=cone.id)`;
const CONCEPT_EDGES = `edges AS (SELECT d.* FROM concept_dependency d WHERE d.dependent_id IN (SELECT id FROM cone)
  UNION SELECT d.* FROM concept_dependency d WHERE d.prerequisite_id=${ROOT_CONCEPT})`;
const CONCEPT_RELATED = `SELECT * FROM concept_related WHERE concept_a_id=${ROOT_CONCEPT} OR concept_b_id=${ROOT_CONCEPT}`;

const FORMALIZATIONS = `SELECT c.id AS concept_id,c.slug AS concept,c.title,c.kind AS concept_kind,
  lib.slug AS library,lib.name AS library_name,lib.repository_url,
  cf.id AS review_id,cf.status AS recorded_status,cf.evidence,cf.reviewed_at,
  CASE WHEN cf.concept_revision=c.revision THEN cf.status ELSE 'unknown' END AS status,
  CASE WHEN cf.concept_revision<>c.revision THEN 1 ELSE 0 END AS review_needed,
  coalesce(estimate.file_count,0) AS file_count,coalesce(estimate.measured_files,0) AS measured_files,
  estimate.estimated_loc,estimate.known_loc
  FROM concept c CROSS JOIN formalization_library lib
  LEFT JOIN concept_formalization cf ON cf.concept_id=c.id AND cf.library_slug=lib.slug
  LEFT JOIN concept_formalization_loc estimate ON estimate.formalization_id=cf.id
  WHERE c.status='active' AND c.id=${ROOT_CONCEPT} ORDER BY c.title,lib.name`;
const FORMALIZATION_FILES = `SELECT link.formalization_id,f.*,link.declarations,link.note,
  a.mapped_concepts,a.allocated_loc FROM concept_formalization_file link
  JOIN formalization_file f ON f.id=link.file_id
  LEFT JOIN formalization_file_allocation a ON a.id=f.id
  WHERE link.formalization_id IN (SELECT id FROM concept_formalization WHERE concept_id=${ROOT_CONCEPT})
  ORDER BY f.path`;

function formalizations(reviews: Row[], fileRows: Row[]): Row[] {
  const files = new Map<unknown, Row[]>();
  for (const { formalization_id, ...file } of fileRows) {
    if (!files.has(formalization_id)) files.set(formalization_id, []);
    files.get(formalization_id)!.push(file);
  }
  return reviews.map(review => {
    const r: Row = { ...review, statement_only: review.concept_kind === 'conjecture' };
    if (r.status === 'inherited') { r.estimated_loc = 0; r.known_loc = 0; }
    r.review_needed = Boolean(r.review_needed);
    r.files = (files.get(r.review_id) ?? []).map(original => {
      const f: Row = { ...original };
      // Old reviews retain their evidence but no longer consume a file share.
      if (r.status !== 'formalized' && r.status !== 'partial') f.allocated_loc = null;
      const repository = r.repository_url as string | null;
      f.url = repository && f.revision ? repository.replace(/\/+$/, '') + '/blob/' + quote(String(f.revision)) + '/'
        + quote(String(f.path), '/') : null;
      return f;
    });
    return r;
  });
}

async function conceptSlice(sql: Sql, slug: string) {
  const [root, edges, related, links, concepts, aliases, sources, reviews, files] = await sql.transaction([
    sql.query('SELECT * FROM concept WHERE slug=$1 OR id=$1', [slug]),
    sql.query(`${CONCEPT_CONE}, ${CONCEPT_EDGES} SELECT * FROM edges`, [slug]),
    sql.query(CONCEPT_RELATED, [slug]),
    sql.query(`SELECT * FROM source_concept WHERE concept_id=${ROOT_CONCEPT}`, [slug]),
    sql.query(`${CONCEPT_CONE}, ${CONCEPT_EDGES}, rel AS (${CONCEPT_RELATED}),
      ids AS (SELECT id FROM cone UNION SELECT prerequisite_id FROM edges UNION SELECT dependent_id FROM edges
              UNION SELECT concept_a_id FROM rel UNION SELECT concept_b_id FROM rel)
      SELECT * FROM concept WHERE id IN (SELECT id FROM ids)`, [slug]),
    sql.query(`SELECT * FROM concept_alias WHERE concept_id=${ROOT_CONCEPT}`, [slug]),
    sql.query(`SELECT * FROM source WHERE id IN (SELECT source_id FROM source_concept WHERE concept_id=${ROOT_CONCEPT})`, [slug]),
    sql.query(FORMALIZATIONS, [slug]),
    sql.query(FORMALIZATION_FILES, [slug]),
  ], { readOnly: true, isolationLevel: 'RepeatableRead' }) as Row[][];
  if (!root.length || root[0].status !== 'active') throw new HttpError(404, 'Unknown concept');
  return {
    data: orderedSlice({ concept: concepts, concept_dependency: edges, concept_related: related, source_concept: links,
                         concept_alias: aliases, source: sources }),
    formalizations: formalizations(reviews, files),
  };
}

const ROOT_SOURCE = '(SELECT id FROM source WHERE slug=$1 OR id=$1)';
const SOURCE_CONE = `WITH RECURSIVE cone(id) AS (
  SELECT concept_id FROM source_concept WHERE source_id=${ROOT_SOURCE} AND role='relies_on' UNION
  SELECT d.prerequisite_id FROM concept_dependency d JOIN cone ON d.dependent_id=cone.id WHERE d.purpose IN ('statement','both'))`;
const SOURCE_CITATIONS = `SELECT * FROM citation WHERE source_id=${ROOT_SOURCE} OR cited_source_id=${ROOT_SOURCE}`;

async function sourceSlice(sql: Sql, slug: string) {
  const [root, links, edges, concepts, citations, sources, identifiers, citationIdentifiers] = await sql.transaction([
    sql.query('SELECT * FROM source WHERE slug=$1 OR id=$1', [slug]),
    sql.query(`SELECT * FROM source_concept WHERE source_id=${ROOT_SOURCE}`, [slug]),
    sql.query(`${SOURCE_CONE} SELECT * FROM concept_dependency WHERE dependent_id IN (SELECT id FROM cone)
      AND purpose IN ('statement','both')`, [slug]),
    sql.query(`${SOURCE_CONE} SELECT * FROM concept WHERE id IN (SELECT id FROM cone)
      OR id IN (SELECT concept_id FROM source_concept WHERE source_id=${ROOT_SOURCE})`, [slug]),
    sql.query(SOURCE_CITATIONS, [slug]),
    sql.query(`WITH c AS (${SOURCE_CITATIONS}) SELECT * FROM source WHERE id=${ROOT_SOURCE}
      OR id IN (SELECT source_id FROM c) OR id IN (SELECT cited_source_id FROM c)`, [slug]),
    sql.query(`SELECT * FROM source_identifier WHERE source_id=${ROOT_SOURCE}`, [slug]),
    sql.query(`SELECT * FROM citation_identifier WHERE citation_id IN (SELECT id FROM citation WHERE source_id=${ROOT_SOURCE})`, [slug]),
  ], { readOnly: true, isolationLevel: 'RepeatableRead' }) as Row[][];
  if (!root.length) throw new HttpError(404, 'Unknown source');
  return {
    data: orderedSlice({ concept: concepts, concept_dependency: edges, source_concept: links, source: sources,
                         source_identifier: identifiers, citation: citations, citation_identifier: citationIdentifiers }),
    formalizations: [],
  };
}

async function search(sql: Sql, kind: string, q: string, limit: number) {
  if (kind !== 'concept' && kind !== 'source') throw new HttpError(400, 'kind must be concept or source');
  if (!(limit >= 1 && limit <= 500)) throw new HttpError(400, 'limit must be between 1 and 500');
  const pattern = '%' + q.toLowerCase().replace(/\\/g, '\\\\').replace(/%/g, '\\%').replace(/_/g, '\\_') + '%';
  const where = kind === 'concept'
    ? `status='active' AND (lower(title) LIKE $1 ESCAPE '\\' OR lower(description) LIKE $1 ESCAPE '\\'
       OR lower(field) LIKE $1 ESCAPE '\\' OR id IN (SELECT concept_id FROM concept_alias WHERE lower(alias) LIKE $1 ESCAPE '\\'))`
    : `(lower(title) LIKE $1 ESCAPE '\\' OR lower(summary) LIKE $1 ESCAPE '\\' OR lower(field) LIKE $1 ESCAPE '\\'
       OR lower(authors) LIKE $1 ESCAPE '\\')`;
  const fields = kind === 'concept' ? 'id,slug,title,field' : 'id,slug,title,field,authors,year';
  const [total, items] = await sql.transaction([
    sql.query(`SELECT count(*) AS n FROM ${kind} WHERE ${where}`, [pattern]),
    sql.query(`SELECT ${fields} FROM ${kind} WHERE ${where} ORDER BY title, id LIMIT $2`, [pattern, limit]),
  ], { readOnly: true }) as Row[][];
  return { total: total[0].n, items };
}

async function stats(sql: Sql) {
  const [row] = await sql.query(`SELECT (SELECT coalesce(max(id),0) FROM curation_event) AS version,
    (SELECT count(*) FROM concept WHERE status='active') AS active_concepts, (SELECT count(*) FROM source) AS sources`) as Row[];
  return { version: String(row.version), active_concepts: row.active_concepts, sources: row.sources };
}

// The collection version changes with every edit; check it at most every 30 s.
let cachedVersion: { value: string; at: number } | null = null;
async function collectionVersion(sql: Sql): Promise<string> {
  if (cachedVersion && Date.now() - cachedVersion.at < 30_000) return cachedVersion.value;
  const [row] = await sql.query('SELECT coalesce(max(id),0) AS v FROM curation_event') as Row[];
  cachedVersion = { value: String(row.v), at: Date.now() };
  return cachedVersion.value;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8', 'X-Content-Type-Options': 'nosniff',
      'Cache-Control': status === 200 ? 'public, max-age=60' : 'no-store', 'Access-Control-Allow-Origin': '*',
    },
  });
}

async function api(request: Request, env: Env, url: URL, ctx: ExecutionContext): Promise<Response> {
  if (request.method !== 'GET') throw new HttpError(405, 'The public collection is read-only');
  const sql = neon(env.POSTGRES_URL);
  const parts = url.pathname.split('/').filter(Boolean).slice(2).map(decodeURIComponent);
  const version = await collectionVersion(sql);
  const cacheKey = new Request(`${url.origin}${url.pathname}?${url.searchParams}&v=${version}`);
  const cached = await caches.default.match(cacheKey);
  if (cached) return cached;
  let body: unknown;
  if (parts.length === 1 && parts[0] === 'stats') body = await stats(sql);
  else if (parts.length === 1 && parts[0] === 'search') {
    body = await search(sql, url.searchParams.get('kind') ?? 'concept', url.searchParams.get('q') ?? '',
                        Number(url.searchParams.get('limit') ?? '200'));
  } else if (parts.length === 3 && parts[0] === 'view' && parts[1] === 'concept') body = await conceptSlice(sql, parts[2]);
  else if (parts.length === 3 && parts[0] === 'view' && parts[1] === 'source') body = await sourceSlice(sql, parts[2]);
  else throw new HttpError(404, 'Unknown API endpoint');
  const response = json(body);
  ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
  return response;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/v1/')) {
      try {
        if (env.PUBLIC_QUERY_LIMIT) {
          const { success } = await env.PUBLIC_QUERY_LIMIT.limit({ key: request.headers.get('CF-Connecting-IP') ?? 'unknown' });
          if (!success) throw new HttpError(429, 'Too many requests; try again in a minute');
        }
        return await api(request, env, url, ctx);
      } catch (error) {
        if (error instanceof HttpError) return json({ error: error.message }, error.status);
        console.error(error);
        return json({ error: 'An internal error occurred' }, 500);
      }
    }
    if (url.pathname === '/' || url.pathname === '/index.html') {
      // The assets binding serves index.html at "/" (it redirects /index.html there).
      const page = await env.ASSETS.fetch(new Request(new URL('/', url), request));
      // Public mode: per-view slices, server-side search, no editing controls.
      return new HTMLRewriter().on('html', { element(e) { e.setAttribute('class', 'public-site'); } }).transform(page);
    }
    if (['/app.js', '/cone.js', '/math-text.js', '/app.css'].includes(url.pathname)) return env.ASSETS.fetch(request);
    return new Response('Not found', { status: 404 });
  },
};
