# The Shape of Math API

Run `python mathdb_server.py`, then open <http://127.0.0.1:8000>.
The browser and API operate on `data/math.sqlite`. `--db PATH` selects another
database; `--port PORT` changes the port. The server initializes or migrates the
database before serving. Core functionality uses only the Python standard library.

This is a local development server bound to loopback. A later shared service can
reuse the curation operations and endpoint contract, with user authentication,
permissions and editor attribution added at its HTTP boundary. The current audit
records what changed and why; it does not identify an authenticated person.

For released plans from prepared source/cone tasks, use `curation_plans.py check`
then `curation_plans.py import`; see [task preparation and imports](docs/CURATION_TASKS.md).
The importer provides private preflight, stale-input checks, one-transaction edits
and task/plan fingerprint auditing for arbitrary sources and roots. Token telemetry
is separate from mathematical edits; [task accounting](docs/TASK_USAGE.md) records
provider requests or measured session intervals in an independent ledger.

All API paths start with `/api/v1`. Requests and responses use JSON. Successful
edits return `{"version":"…","result":…}`. Errors return `{"error":"…"}`.
Records use UUIDs internally, stable slugs in URLs, and integer IDs for links and
citations. Slugs and UUIDs are both accepted where an existing concept/source is
referenced. Concept and source records are reorganized rather than hard-deleted.

## Read endpoints

| Method and path | Result |
| --- | --- |
| `GET /state` | `{version,stats,data,formalizations}`; `data` is the relational snapshot, including historical concept records; `formalizations` contains current status and LOC estimates. |
| `GET /concepts?q=TEXT` | Active concept records matching names, descriptions or fields. |
| `GET /concepts/SLUG` | Concept with immediate `prerequisites`, `dependents`, `related`, source occurrences and `formalizations`. |
| `GET /concepts/SLUG/cone?mode=statement` | Mode-filtered ancestor DAG (statement is the default): `root_id,nodes,edges,leaves,unreviewed,max_depth,all_reviewed`. Nodes have longest-path `depth`, root 0. |
| `GET /concepts/SLUG/reduction` | Read-only reduction preview: removed edges and retained alternative paths. |
| `GET /sources?q=TEXT` | Source records matching title, authors or field. |
| `GET /sources/SLUG` | Source with identifiers, concept occurrences, citations, incoming citations and curated source relations. |
| `GET /citations/ID` | Citation, extracted identifiers and optional assessment. |
| `GET /history?limit=20&before=ID` | Curation summaries, newest first; maximum page size 100. |
| `GET /history/ID` | Full before/after audit event. |

Source details decode `authors` as a list. The relational snapshot retains the
SQLite storage format, including JSON-encoded authors and integer boolean flags.
The browser filters superseded concepts and their historical occurrences from its
active reading views. An empty prerequisite list does not certify completeness.

## Editing and concurrent changes

Every edit requires a nonempty `reason` and `Content-Type: application/json`.
Every read and successful edit returns an `ETag` header. Send the latest value,
including its quotes, in `If-Match`. The version covers the whole database, so an
unrelated intervening edit also requires refreshing. Version checks and the edit
start under one SQLite write transaction. Each successful operation records an
audit event. Existing cycle checks, paragraph limits, completeness invalidation,
identifier normalization and atomic split/merge routing remain enforced.

```python
import json
from urllib.request import Request, urlopen

root = "http://127.0.0.1:8000/api/v1"
with urlopen(root + "/concepts/fusion-category") as response:
    concept = json.load(response)
    version = response.headers["ETag"]

request = Request(
    root + "/concepts/fusion-category",
    method="PATCH",
    headers={"Content-Type": "application/json", "If-Match": version},
    data=json.dumps({
        "description": concept["description"],
        "reason": "Reviewed the definition and its field conventions"
    }).encode(),
)
with urlopen(request) as response:
    saved = json.load(response)
```

On `412`, reload the record and review the draft against the latest data before
retrying. Missing `If-Match` gives `428`. Other responses include `400` for invalid
input, `403` for an untrusted Host or cross-origin edit, `404` for missing records,
`409` for constraint violations including cycles, `413` for invalid/oversized
bodies, and `415` for non-JSON edits. Request bodies are limited to 2 MiB. The server
does not allow cross-origin browser writes and serves no permissive CORS headers.

## Edit endpoints

The fields below omit the `reason` required on every request. Optional fields
can be omitted; nullable fields can explicitly be set to `null`.

| Method and path | Body |
| --- | --- |
| `POST /concepts` | `slug,title,kind,description,field`; optional `aliases,boundary`. |
| `PATCH /concepts/SLUG` | Any of `title,kind,description,field,boundary`. |
| `POST /sources` | Source ingestion record: `slug,title,authors,field,status,coverage,summary,dependency_review,identifiers`; optional `year,artifacts`. |
| `PATCH /sources/SLUG` | Any of `title,authors,year,field,status,coverage,summary,dependency_review`. |
| `POST /sources/SLUG/identifiers` | `scheme,value`; collision with another source is rejected. |
| `POST /dependencies` | `prerequisite,dependent,basis,rationale,purpose`; optional evidence `source,locator`. |
| `PATCH /dependencies/ID` | Any of the dependency creation fields. |
| `DELETE /dependencies/ID` | Only the required reason. |
| `POST /related` | `concept_a,concept_b,rationale`; optional evidence `source,locator`. |
| `DELETE /related/ID` | Only the required reason. |
| `POST /source-concepts` | `source,concept,role,locator`; optional `note`, and required `introduction_evidence` for role `introduces`. |
| `PATCH /source-concepts/ID` | Any of `role,locator,note,introduction_evidence`. |
| `DELETE /source-concepts/ID` | Only the required reason; historical occurrences cannot be removed. |
| `POST /citations` | `source,text`; optional `label,identifiers,cited_source,pedagogically_necessary,needed_material`. |
| `PATCH /citations/ID` | Any citation fields except citing `source`. |
| `DELETE /citations/ID` | Only the required reason. |
| `POST /citations/resolve` | `source`; match explicit identifiers against the current catalogue. |
| `POST /reviews` | `kind` (`concept`/`source`), `slug`, and a `changes` object of boolean completion flags. |
| `POST /reductions` | Optional `root` concept slug; omit for the entire DAG. Preserves reachability and existing reviews; original edges/evidence and retained paths are audited. |
| `POST /reorganize` | An explicit split/merge/retire plan, including routes and reason; see `mathdb.reorganize`. |
| `POST /ingest` | `batch`: an existing JSON ingestion batch. The request reason becomes its audit note. |

Kinds are `definition`, `theorem`, `construction`, `conjecture`. Dependency bases
are `logical`, `pedagogical`, `both`. Source statuses are `catalogued`, `draft`,
`reviewed`. Canonical source concept roles are **`relies_on`, `introduces`, `explains`,
`discusses`**. `introduces` asserts an original mathematical contribution and requires
nonempty `introduction_evidence` plus a location. `explains` covers useful expositions,
recalled definitions and new proofs of known results. Legacy `defines`/`proves` input
maps to `explains`; it never creates an origin claim. Originality remains a curated
judgment requiring source review. [Curation workflows](docs/CURATION.md) give the
source-specific criteria and the G₂ counterexample.

Source details include `requirements.direct` (the minimal recorded prerequisite
frontier) and `requirements.inherited` (background with `via` root slugs). Raw located
occurrences remain in `concepts`; source explanations and introductions do not
implicitly seed requirements. `closure` / `prerequisite_closure` follow explicitly
required concepts only.

Identifiers use `[scheme,value]` pairs: DOI, arXiv, ISBN, URL and zbMATH (`zbl`).
A citation's `pedagogically_necessary` is `true`, `false` or `null`; its
`needed_material` is optional free text. It can remain unresolved. Citation text
changes re-extract identifiers and clear the previous target before rematching.
A citation's identifiers do not automatically become canonical source identifiers.

`POST /reviews` accepts independent `statement_prerequisites_complete` and
`proof_prerequisites_complete` judgments for concepts (the old combined
`prerequisites_complete` remains for compatibility); sources accept
`requirements_complete`, `introductions_complete`, `citations_complete`. Values
must be JSON booleans. Completion judgments are independent, local to the direct
list, and never inferred by traversing the graph. Source role and citation edits
reset only their corresponding flags. See [CONCEPTS.md](CONCEPTS.md) for all rules.

Example citation body:

```json
{
  "source": "morrison-g2-2011",
  "label": "Example reference",
  "text": "Author, A useful paper. arXiv:1002.0168.",
  "pedagogically_necessary": null,
  "needed_material": "Theorem 2.3, existence part only",
  "reason": "Capture a bibliography entry for later assessment"
}
```

The browser uses these same endpoints for its editing forms. It offers concept
and source editing, adding records and identifiers, prerequisite and related
links, source concept links, citation capture/assessment, and completeness reviews.
Advanced batch ingestion and split/merge routing are available through the API.

Retirement without an equivalent replacement uses `operation: "retire"`,
nonempty `from`, and `to: []`. Capture `mathdb.retirement_inventory(db, slugs)`
as `incident_inventory` immediately before preparing the plan. It includes the
complete concept rows, incoming and outgoing edges, source occurrences, aliases,
related links, and formalization reviews. Every incident ID still needs an
explicit route with `replacements: []` and a reason. Every alias needs an
`alias_dispositions` entry containing `concept`, `alias`,
`action: "historical_only"`, and `reason`. A stale inventory is rejected.
The retired UUIDs, paragraphs, source occurrences, aliases and reviews remain
historical records; active edges and vectors are removed. A different valid
theorem is not an equivalent replacement for a refuted claim.


The cone endpoint traverses every ancestor without a depth or node-count cutoff.
It includes the selected root, deduplicates shared prerequisites, and excludes
related links and citations. `all_reviewed` is true only when every returned node
has the relevant typed completeness judgment true. It describes the recorded graph under its
curated definitions and baseline. An unreviewed leaf keeps the value false.

Reduction previews return each original `edge`, a `path` of concept slugs, and
`path_edge_ids` referencing retained edges. A reduction write requires the normal
reason and `If-Match` headers. It restores existing review values after deleting
shortcuts, since the known prerequisite relation is unchanged; it does not grant
new review certifications. A scoped reduction edits only edges in that entire
ancestor cone. Citation and related graphs remain independent.


## Statement and proof dependencies (schema8)

Dependency `purpose` is `statement`, `proof`, `both`, or `unclassified`.
`basis` still means logical/pedagogical justification; it is not a purpose.
POST and PATCH `/dependencies` accept `purpose`. New theorem inputs without a
purpose remain unclassified; definition/construction inputs default to statement.
Proof purposes target theorem-shaped concepts. Typed completeness cannot be
certified while a concept has unclassified incoming edges.

`GET /concepts/SLUG/cone?mode=statement` recursively follows statement/both inputs.
`?mode=proof` recursively follows concepts needed for the statement and for the proof. `?mode=all` includes
legacy unclassified edges for inspection. Responses include the selected `mode`,
per-node `coverage_complete`, `proof_frontier` (recorded inputs not traversed in
statement mode), and `unclassified_dependencies`. Unknown classifications prevent
`all_reviewed` from being true. Statement and proof completeness flags are separate;
a complete statement cone does not certify recursive proof closure.

The current curation task records all direct prerequisites for the proof of encountered
theorems but recursively follows only statement edges. CLI equivalents:

```sh
python mathdb.py cone chebyshev-inequality --mode statement
python mathdb.py cone chebyshev-inequality --mode proof
python mathdb.py review concept chebyshev-inequality --statement-prerequisites complete --reason 'Reviewed all direct prerequisites for the statement'
```

Reduction preserves statement reachability and proof reachability separately.
A proof-only path never justifies deleting a statement edge. Original evidence,
purposes and retained witness paths are recorded in the reduction event.

## Formalization and estimated LOC (schema 10)

Run `python mathdb.py init` once to upgrade an existing v3–v9 database. Migration
adds the library/file/review tables and Mathlib/Tau Ceti registry entries, preserving
existing concept IDs, vectors, links, review flags and history. It creates no
formalization claims. Initialization is idempotent.

All writes below use the normal `reason`, `If-Match`, JSON body and audit rules.
The `POST` operations save a full record or review; they also update an existing
record with the same identity. Review IDs and shared file IDs remain stable.

| Method and path under `/api/v1/` | Body or query |
| --- | --- |
| `GET formalization-libraries` | Library registry |
| `POST formalization-libraries` | `slug`, `name`, optional `repository_url` (HTTP(S), no credentials; null clears it) |
| `GET formalization-files?library=mathlib` | Stored shared files, including measurements; optional library filter |
| `POST formalization-files` | `library`, `path`, `loc`, and for a measured count `revision`; optional `measured_at` ISO timestamp with timezone and `sha256` |
| `POST concepts/SLUG/formalizations/LIBRARY` | `status`, `evidence`, `files` (full replacement set) |
| `GET formalizations` | Optional `concept`, `library`, `status` filters |
| `GET concepts/SLUG` | Includes that concept's computed `formalizations` |
| `GET state` | Raw tables in `data`, plus computed `formalizations` alongside `stats` |

A review's status is `formalized`, `partial`, `inherited`, `not_formalized` or `unknown`. Evidence
is required and should name the inspected revision and actual comparison/search.
A file item is `{"path":"Mathlib/Example.lean","note":"Defines X and develops its API","declarations":"X, X.property"}`.
`declarations` is optional text; `note` is required. Paths must be canonical,
repository-relative `.lean` paths, with no traversal, backslashes or duplicate
paths. Positive/partial reviews require at least one file; inherited/negative/unknown reviews
require an empty array. Saving a review creates unmeasured shared file records as
needed; it never overwrites an existing file count. Use the file operation to record
or clear a count. `loc: null` clears revision, timestamp and hash too (omit them or
pass null). A measured count requires a nonnegative integer and a revision; the
measurement timestamp defaults to now. Count physical lines including blank lines
and comments, with a final unterminated line counted once.

The response to `GET formalizations` has one row per active concept/library,
including unreviewed `unknown` rows. Important fields are:

- `status`: effective status; `recorded_status` preserves the earlier judgment.
- `review_id`, `evidence`, `reviewed_at`, `review_needed`: provenance and staleness.
  A concept's name/kind/description revision makes its review stale, effectively
  unknown, until re-reviewed. Retired concepts are excluded from current reports.
- `files`: path, declarations, contribution note, raw `loc`, revision, measurement
  timestamp, hash, `mapped_concepts`, `allocated_loc` and optional file URL. URLs use
  `repository_url/blob/REVISION/PATH` for GitHub-compatible repository URLs. Unknown
  revisions or repository URLs yield null links. Stale reviews retain their old
  files as evidence with null allocations.
- `estimated_loc`: sum of whole-file equal shares, null if any mapped file is
  unmeasured or the effective status is unknown/negative. Inherited-only reviews
  have zero native LOC.
- `known_loc`: sum for measured files only, explicitly a subtotal if counts are
  missing; zero for inherited-only reviews and null for unknown/negative reviews.
- `file_count`, `measured_files`: counts for current positive/partial mappings.

All current positive **and partial** reviews of active concepts share a file.
`allocated_loc = loc / mapped_concepts` is calculated before report filters; a
query for a single concept does not assign it the whole file. Counts and shares
are separate per library. Adding/removing a mapping changes every affected share.
Inherited-only/unknown/negative/stale/retired reviews receive no file shares. An actual measured empty file
has zero LOC, whereas an unmeasured file has null LOC. This deliberately rough
estimate apportions the entire file among known mappings, even when other concepts
in that file have not yet been catalogued. File snapshots can have different
revisions; the report exposes those revisions rather than claiming one snapshot.

CLI equivalents (illustrative `CONCEPT`, paths and revisions):

```sh
python mathdb.py formalization library '{"slug":"mathlib","name":"Mathlib","repository_url":"https://github.com/leanprover-community/mathlib4"}' --reason 'Configure code links'
python mathdb.py formalization set CONCEPT mathlib '{"status":"formalized","evidence":"Compared the definition and API at COMMIT.","files":[{"path":"Mathlib/Example.lean","note":"Defines the concept and its basic API.","declarations":"Example"}]}' --reason 'Review implementation'
python mathdb.py formalization file '{"library":"mathlib","path":"Mathlib/Example.lean","loc":120,"revision":"COMMIT"}' --reason 'Count inspected file'
python mathdb.py formalization measure mathlib /path/to/mathlib4 --revision COMMIT --reason 'Count the reviewed commit'
python mathdb.py formalization report --concept CONCEPT --library mathlib
python mathdb.py formalization report --library tau-ceti --status formalized
```

`measure` is CLI/core only: it reads Git objects for all files in current active
positive/partial mappings in that library, pins the selected `--revision COMMIT` (HEAD by default), counts
committed bytes, and records SHA-256 hashes. Local edits are ignored. Supply the
repository root. Missing/nonregular files abort the entire operation, retaining
all prior measurements. The caller selects the checkout corresponding to the library.

Python core operations are `save_library(db, item, reason)`,
`save_formalization(db, concept, library, item, reason)`,
`save_formalization_file(db, item, reason)`,
`measure_formalization_files(db, library, root, reason, revision='HEAD')` and
`formalizations(db, concept=None, library=None, status=None)`. They require no new
packages. Mutations compose atomically with ingestion/reorganization transactions.

An ingestion batch may include `formalization_libraries`, `formalization_files`
and `formalizations`. Library/file items use the bodies above; formalization items
add `concept` and `library` to the review body. Records are processed in that order
after ordinary concepts/sources/links. A failed batch rolls back all reviews,
measurements, newly created files, and audit events.

Reorganization plans additionally require `formalization_routes` for exactly every
old review ID. Each route contains `replacements` of the form
`{"concept":"new-slug","library":"mathlib","status":"partial","evidence":"Fresh comparison at COMMIT; endpoint still missing.","files":[{"path":"Mathlib/Example.lean","note":"Implements this part."}]}`.
Empty replacements require a reason. Replacement concepts must be new identities;
the library must match the old review. Two old reviews in the same library must be
consolidated into one review per replacement/library, with explicit reasons for
dropping duplicate routes. Historical reviews remain on retired records; active
shares count only the replacements.

For direct SQL queries, `formalization_file_allocation` contains each currently
mapped file's whole count, denominator and share. `concept_formalization_loc`
contains totals for current positive/partial reviews. Join `concept_formalization`
and `concept` for human names; do not infer negative status from a missing row.

```sql
SELECT c.slug, cf.library_slug, cf.status, estimate.estimated_loc,
       estimate.known_loc, estimate.measured_files, estimate.file_count
FROM concept_formalization_loc estimate
JOIN concept_formalization cf ON cf.id=estimate.formalization_id
JOIN concept c ON c.id=cf.concept_id
ORDER BY cf.library_slug, c.slug;
```

`python export_example.py` regenerates raw `data/snapshot.json`, computed
`data/formalizations.json`, a per-concept/library `data/formalizations.tsv`, and the
readable catalogue. The browser uses the same computed report as the API/CLI.

Schema 10 adds `inherited` while retaining review IDs, file mappings, timestamps,
measurements and history from schema 9. A native contribution may be a core API
extension to a dependency-provided definition; its evidence must identify both
project and dependency revisions and ownership. An inherited-only review has empty
`files`, `file_count=measured_files=0`, and `estimated_loc=known_loc=0.0`. It asserts
checked availability, not absence. Unknown/negative reviews still have null LOC.
The native-file SQL allocation views intentionally contain only current
`formalized`/`partial` reviews; use the full report to include inherited zeroes.

The bounded core API selection, sample-density limits and representative
declaration/exclusion evidence are specified in CONCEPTS.md and
prompts/formalization.md. The reproducible first sample is
`data/formalization-pilot.json`; coordinator review decisions and exclusions are in
`data/formalization-pilot-review.txt` and its JSON companion. Do not replay an
old sample over later curation without reviewing its evidence and file sets.

Formalization reports include `concept_kind` and `statement_only` (true for
conjecture entries). Positive coverage of a conjecture records its formal statement,
not a proof or truth claim. The concept page and readable exports make this explicit;
aggregate reports must count these separately or disclose this distinction.
