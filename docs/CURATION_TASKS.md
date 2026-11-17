# Prepare inputs for a curation task

A curator needs the paper or concepts to inspect, the database to read, the
repository instructions, and a directory in which to save proposed edits. The
`curation/prepare_task.py` command puts fixed copies of these inputs in a new
directory. It does not run an agent or apply database edits.

The task instructions themselves are [ingest-source.md](../prompts/ingest-source.md)
for paper inventories, [expand-prerequisites.md](../prompts/expand-prerequisites.md)
for cones, and [formalization.md](../prompts/formalization.md) for library coverage.
There is one prompt for each task.

## Specify the paper or concepts

For a source task, create a JSON file such as `source-input.json`:

```json
{
  "task_id": "source-1501.04823",
  "source_identifiers": [["arxiv", "1501.04823"]],
  "coverage": "Entire paper, including appendices and bibliography",
  "capture_bibliography": true
}
```

If you already have the paper, add `"artifact": {"path": "/path/to/paper.pdf",
"version": "v1"}` with the actual path and version. Otherwise the worker obtains
and records the file before analysis.

For a cone task, create a JSON file such as `cone-input.json`:

```json
{
  "task_id": "cones-category-clique",
  "roots": ["category", "clique"],
  "baseline": "Sets and natural numbers, elementary logic and finite arithmetic"
}
```

Replace these example identifiers with the ones requested. `roots` accepts either
current concept slugs or objects containing `id` and `slug`; the preparer looks up
and records the actual database UUIDs. The baseline is the point at which recursive
investigation stops. Omit it to use the elementary baseline shown above.

## Create the directory

```sh
python curation/prepare_task.py --kind source --assignment source-input.json \
  --out /path/to/new/source-task
python curation/prepare_task.py --kind cone --assignment cone-input.json \
  --out /path/to/new/cone-task
```

`--assignment` names the JSON input file just described. `--out` names a new task
directory. `--db /path/to/catalogue.sqlite` chooses a different input database;
otherwise the command uses `data/math.sqlite` in this repository.

The preparer saves a consistent read-only copy of the catalogue, pins root UUIDs,
copies the instruction files, hashes supplied paper files, and writes
`assignment.json` with the resolved paths and identifiers. `policy-manifest.json`
records the hashes of the database, paper and instruction files. Existing task directories are never overwritten. It does
no mathematical review, import, embedding or formalization processing. Assignments
can specify a different catalogue using `--db`. Source artifact paths in the input
assignment must be actual local files; they are copied and hashed in the package.
If no artifact is supplied, the worker must obtain/version/hash it before reading.

The command resolves all input paths relative to the current directory. The
finished package uses relative paths for its catalogue, policies and copied source
artifact so it can be moved. It also records the original repository location and
code hashes as provenance. Supply the repository/software or an equivalent pinned
environment to execute API checks. A source identifier or a task file is not by
itself a runnable mathematical database service.

Give the curator only this handoff, replacing TASK_DIRECTORY:

> Work in TASK_DIRECTORY. Read assignment.json, task.md and the policy files listed
> in policy-manifest.json. Use the pinned catalogue; stage outputs in output/.
> Do not write the shared database. No earlier conversation is required. Report
> inaccessible evidence and unresolved judgments explicitly. Keep released plans
> immutable and provide a resumable checkpoint if work remains.

Run mathematical review in subagents per repository policy. Use fresh contexts.
Do not include results, forecasts, model preferences, novelty targets or desired
reuse rates in the job. Existing catalogue contents are necessary context; prompt
isolation is not filesystem isolation. Do not claim stronger independence than
the runner provides.

## What is fixed, and what remains judgment

Record the database and instruction-file hashes, identifiers, paper versions, baseline,
root list, coverage, proof traversal policy and worker/model settings. The current
baseline is sets and natural numbers, elementary logic and finite arithmetic.
The source job records all actual reading roots; the cone job follows all their
statement/both ancestors, records one inspected proof's immediate requirements at
each reached theorem, and never follows proof-only edges unless that parent is
independently on a statement path. Capture which proof was examined.

This makes the procedure repeatable, not its mathematical judgments deterministic.
Concept granularity, source-specific reading requirements, proof choices and origin
evidence still need expert judgment. Preserve candidate ledgers, excluded local
expressions, reuse/revision reasons and inspected proof accounts so another worker
can audit differences. Self-review is not independent review. No amount of software
validation proves an inventory is mathematically exhaustive.

## Review and import

Workers produce staged plans and evidence only. The coordinator runs a compatible
private-copy importer/checker and reconciles against the current shared state.
An old snapshot does not license overwriting concurrent changes. Refresh stale
incident inventories and review source occurrences and formalizations before any
revision/split/merge/retirement. Released plans are immutable; corrections are later
plans. Apply reviewed edits sequentially, validate typed DAG reachability and source
roles, then refresh vectors/exports and recompute final cones from the live graph.

Use the general importer for any prepared source or cone task:

```sh
python curation_plans.py check /path/to/task /path/to/task/output/plan-001.json \
  --db /path/to/math.sqlite
python curation_plans.py import /path/to/task /path/to/task/output/plan-001.json \
  --db /path/to/math.sqlite
```

`check` verifies the pinned task inputs, reads the current target database without
writing it, applies the plan to a private copy and saves `plan-001-check.json`.
`import` requires that receipt, the exact same released plan and the same target
database event number. It applies all operations and their audit record in one
transaction, rolling everything back on a late error. A repeated unchanged import
returns the prior result. A modified released plan, conflicting task ID, or changed
database requires review/checking again; use a new numbered plan for corrections.

The old2015 and cone-batch coordinators remain unchanged for their existing runs.
The general importer has no sample or year allowlist and accepts cone-only plans
without a source. It records `curated_task_plan` events rather than2015-paper events.
Checking is a structural preflight, not independent mathematical review.

### Plan files

Save the ordinary `API.md` ingest payload in `output/plan-NNN.json`, and a review
sidecar alongside it named `plan-NNN-review.json`. The review must contain
`"reviewed_ready": true` before checking or importing. For example:

```json
{
  "reviewed_ready": true,
  "reviews": [{
    "slug": "EXISTING_OR_NEW_CONCEPT_SLUG",
    "statement_prerequisites_complete": false,
    "reason": "Exact remaining statement-prerequisite work."
  }],
  "source_reviews": []
}
```

For source reviews, supply `source`, an explicit `flags` object containing any
reviewed `requirements_complete`, `introductions_complete`, `citations_complete`,
and a reason for each judgment (`reason` or per-flag `flag_reasons`). Concept proof
flags are independent. Omitted reviews are unchanged; no flags become true merely
because import succeeds. An empty reviews list is valid for bibliographic-only
updates. Legacy top-level `source_flags`/`judgments` are rejected to avoid silently
dropping completeness judgments.

An optional `plan-NNN-resolutions.json` maps candidate concept slugs to existing
ones as `{"concepts": {"candidate": {"target": "existing", "reason": "..."}}}`.
The importer compares same-slug statements and rejects conflicting text without
an explicit resolution/revision. Source identity is matched by normalized external
identifiers; conflicting source owners are rejected. Additional checked identifiers
and artifacts on reused sources are retained. Aliases in concept/source links,
dependencies, citations and formalization mappings are resolved consistently.

The supported `proposed_*` sidecar operations are revisions, reorganizations,
dependency-purpose removals, source occurrence routings, source role corrections,
source metadata updates, locator corrections, identifier corrections and dependency
evidence updates. Their reviewed before/after contracts remain documented in
`curation/source-tasks/PLAN_OPERATIONS.md` and `API.md`. Unknown operation names
are rejected. Same-identity revisions additionally require `formalizations` in
their full incident inventory (from `mathdb.formalizations(db, concept=SLUG)`).
Splits/merges/retirements still require the core's complete explicit routing,
including formalization reviews and retirement alias dispositions. Typed transitive
reduction preserves deleted evidence and witness paths. The importer does not
automatically relabel every database leaf as an elementary concept.

### Stale mathematical reviews

A completeness judgment made from an old task snapshot cannot certify newly
changed input lists. By default the importer compares reviewed concept statements,
their direct prerequisite rows and parent meanings, and reviewed source records/occurrences/citations/
artifacts/identifiers, with the pinned task database. Changed inputs require a
fresh task or an actual curator re-review of current state.

After such a re-review, the curator can record `reviewed_against_event: N` and
`current_state_review_reason` in the review sidecar. N is the exact current
`max(curation_event.id)` they inspected. The importer enforces it; it is not a
switch to bypass review. Follow-up plans that certify concepts created by an
earlier plan also need that current-state review or a refreshed task snapshot.
An unrelated database edit between preflight and import requires another check.

After successful import, the database audit event is authoritative.
`plan-NNN-result.json` is a convenience copy; if writing it fails, repeating the
unchanged import reconstructs the receipt without applying the edits twice.
Embeddings and readable exports are still an explicit coordinator step afterward.

## Completion and measurement

Keep source reading/originality/bibliography flags separate from each concept's
statement/proof flags. An entirely closed recorded cone does not certify that a
source's root inventory is complete. A statement cone can be complete while an
encountered theorem's proof requirements remain unknown. Proof-only parent lists
are deliberately left unexpanded. Unknown/false claims, inaccessible proofs and
unresolved priority have distinct dispositions; none should be guessed away.

Use [task token accounting](TASK_USAGE.md) before starting new work. The runner can
record provider-reported request usage directly or measure counter differences in
a dedicated session log interval. Keep one survey ledger, reference shared cone
tasks separately, and export a task's report to `output/usage.json`. Do not divide
a multi-paper session equally and present that as measured per-paper usage.
Budgets are limits, not completeness criteria. On reaching one, save queue state
and false flags; a later job resumes the scope with a current catalogue.
