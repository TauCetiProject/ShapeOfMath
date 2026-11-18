# Scaling plan

The collection will grow to at least 100k sources, possibly 1M. How fast the
concept count grows with the source count is the question this project exists to
answer, so nothing here assumes it stays small. This document records the target
architecture and the order of the migration.

## Measurements at the start (2026-11-17)

| | Now | At 1000x |
|---|---|---|
| Active concepts | 6,196 | up to ~6M |
| Dependency edges | 22,680 | up to ~23M |
| Sources | 675 | 100k to 1M |
| `math.sqlite` | 110 MB | ~100 GB |
| `/api/v1/state` snapshot | 35 MB (6 MB gzipped) | ~35 GB |
| Full prerequisite cone, median / p99 / max | 43 / 828 / 1,735 nodes | grows with depth, not with count |

`curation_event` (the audit history) is 73% of the database.

## What breaks

1. The browser downloads the whole collection on load. This fails well before
   10x. Every view must fetch only what it shows.
2. Git LFS keeps every version of `math.sqlite`. Each commit of the database adds
   its full size to the repository's LFS storage.
3. Curation agents on one machine share one SQLite file. Agents on several
   machines, and people working alongside them, need a shared server.
4. Search and the cone diagram assume small collections. A 20,000-node diagram is
   unreadable; large cones need summaries (collapsed foundations baseline, depth
   limits, the unexpanded frontier).

## Target architecture

- **Authoritative store: Neon Postgres**, project `tauceti-shape-of-math`
  (`wild-sea-59301389`, AWS us-east-2). Curation agents write directly through
  `mathdb.py`, which keeps the audited core operations as the single
  implementation. There is no write service to host.
- **Integrity rules live in the database**: the DAG, purpose and review-flag
  triggers become PL/pgSQL triggers, so every writer gets them. Writers serialize
  on a transaction-level advisory lock, matching SQLite's single-writer semantics
  that the cycle check and the `If-Match` version check rely on.
- **Cone and cycle queries walk prerequisites**, never dependents. A new edge
  `p -> d` creates a cycle exactly when `d` is in the prerequisite cone of `p`.
  Cones stay small; the set of dependents of a foundational concept such as
  "Set" grows with the whole collection.
- **Public read path: a Cloudflare Worker** at
  `shapeofmath.taucetiproject.org` on the Tau Ceti account, following
  `TauCetiTools/services/github-state`: `@neondatabase/serverless` over HTTP,
  a Neon read replica, and responses cached at the edge by database version. The
  frontend fetches per view: one record, its neighbourhood, one cone, one page of
  search results.
- **History**: recent `curation_event` rows stay in Postgres; older events move
  to R2 so the working set stays small.
- **Published data**: periodic per-table dumps (compressed JSON Lines) in a
  public R2 bucket replace `data/math.sqlite` in git.
- **Submissions**: a GitHub issue form for single sources, and pull requests
  adding files under `submissions/` for bulk lists. Curation agents take work
  from there; no extra infrastructure.

## Migration order

1. Postgres schema (`schema_pg.sql`) equivalent to `schema.sql` version 10, and
   a connection adapter that lets the existing code run on either backend.
2. Run the full test suite against Postgres. (Done.)
3. Import `data/math.sqlite` into a Neon branch with triggers disabled, verify
   row counts, `verify()` output and cone results against SQLite. (Done.)
4. Benchmark cone queries and cycle checks on a synthetic graph at 100x. (Done.)
5. Cut over: point curation at Neon, freeze the SQLite file, stop committing it.
   (Done 2026-11-18: the frozen file is in `archive/`; tools use the `curator`
   role and the Worker will use `reader`.)
6. Worker read API and the per-view frontend.
7. R2 dumps, history archival, submission intake.

## Running on PostgreSQL

`mathdb.connect` takes a `postgresql://` URL as well as a file path, and
`MATHDB_DATABASE` sets the default. `pgcompat.py` gives the psycopg connection the
sqlite3 interface the code uses, so the core operations, the server and the plan
importer run unchanged. Install the `postgres` extra for psycopg.

`python tests/run_postgres.py` runs the unittest suite against PostgreSQL, given
`MATHDB_TEST_POSTGRES` (an administrative URL; each test gets its own database).
Skipped there: SQLite file migrations, and tests of tools that read or copy the
live database as an SQLite file.

On PostgreSQL, `curation_plans.py check` applies the plan in a transaction on the
live database and rolls it back, instead of copying the database.

## Work found during the port

- Task packages (`curation/prepare_task.py`) freeze a copy of the whole database
  as their baseline. At 100 GB that cannot work: a task's baseline must be the
  subgraph it reviews (its cones, sources and their events), exported from
  PostgreSQL.
- `curation/prepare_task.py`, `freeze.py` and the 2015 coordinators live in
  untracked directories, yet tracked tests import them. A clean checkout cannot
  run those tests.
- Several core functions read whole tables into Python: `verify()` (called by
  the `/api/v1/state` endpoint on every load), `snapshot()`, alias lookups in
  reorganization, and the per-source identifier check. Each needs an indexed
  query or a scoped variant before 100x.

## Benchmarks (2026-11-18)

`pg_sync.py import` copied the live collection into a Neon branch in 7 seconds; every
table, `verify()` and 100 sampled cones match the SQLite source.

`bench_scale.py` replicated the collection 100 times (581,196 concepts, 2,144,880
edges, 20% of copied edges crossing fields) on a Neon branch (0.25 to 8 compute
units, us-east-2), queried from a machine 24 ms away:

| | Time |
|---|---|
| Cone, median of 100 (statement and full, 67 nodes) | 64 ms |
| Largest full cone (4,286 nodes, 9,949 edges) | 0.31 s |
| Insert an edge, including the cycle check | 85 ms |
| Reject an edge that closes a cycle in the largest cone | 97 ms |

Each cone is two queries, so round trips dominate small cones. Replication grows
cones only slightly, even when every copied edge crosses fields: a cone's size
is bounded by the shape of the prerequisite paths, not by the size of the
collection. A materialized closure is not needed at this scale.

## Open questions
- Embeddings: `concept_embedding` moves to `pgvector` when similarity search is
  served publicly.
