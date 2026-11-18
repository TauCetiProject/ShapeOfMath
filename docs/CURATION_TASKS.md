# Curation tasks

A curation task reads one paper (a **source task**) or expands the prerequisites
of some concepts (a **cone task**). Each task runs in isolation: the worker reads
a snapshot of the catalogue, never sees other tasks, and writes one result file.
Results meet only when they are merged into the live catalogue, one at a time.

The steps are:

1. The coordinator **prepares** a task directory.
2. A worker subagent does the mathematics and writes `output/result.json`.
3. A merge subagent reconciles the result with the live catalogue
   ([prompts/merge.md](../prompts/merge.md)).
4. The coordinator **imports** it, then refreshes embeddings and exports.

Steps 2 and 3 are mathematical work and run in subagents. Steps 1 and 4 are
mechanical. Tasks can run in parallel; merges and imports run one at a time, so
each merge sees everything imported before it.

## Prepare

Write a JSON file naming the task. For a source task:

```json
{
  "task_id": "source-1501.04823",
  "source_identifiers": [["arxiv", "1501.04823"]],
  "coverage": "Entire paper, including appendices and bibliography",
  "capture_bibliography": true
}
```

Add `"artifact": {"path": "/path/to/paper.pdf", "version": "v1"}` if you already
have the paper; otherwise the worker obtains it. For a cone task:

```json
{
  "task_id": "cones-category-clique",
  "roots": ["category", "clique"],
  "baseline": "Sets and natural numbers, elementary logic and finite arithmetic"
}
```

`roots` accepts slugs or objects with `id` and `slug`. Omit `baseline` to use the
elementary baseline shown. Then:

```sh
python curation_plans.py prepare --kind source --assignment source-input.json --out TASK_DIR
python curation_plans.py prepare --kind cone --assignment cone-input.json --out TASK_DIR
```

This creates `TASK_DIR/assignment.json` (the input plus resolved root UUIDs, the
prompt to follow, the repository commit and catalogue event),
`TASK_DIR/catalogue.sqlite` (an SQLite snapshot of the live catalogue, exported
from PostgreSQL; `--db` names another PostgreSQL URL or SQLite file), a copy of any supplied paper, and an empty `output/`. It refuses
to overwrite an existing directory.

## Hand off

Give the worker only this, with the path filled in:

> Work in TASK_DIR. Read assignment.json and the prompt it names, in the
> repository it names. Use the catalogue snapshot; write your result to
> output/result.json. Do not write the shared database. No earlier conversation
> is required. Report inaccessible evidence and unresolved judgments explicitly.
> Never use Anna's Archive, Library Genesis, Z-Library, Sci-Hub or any other
> shadow library.

Do not include expected results, novelty targets or reuse rates in the handoff.

## Merge and import

Once the worker has finished, give a merge subagent
[prompts/merge.md](../prompts/merge.md) and the task directory. When it reports
a clean dry run:

```sh
python curation_plans.py import TASK_DIR
python mathdb.py embed
```

`import` applies the whole result in one transaction, runs typed transitive
reduction, applies the completeness reviews, records a `curated_task_plan` event
and writes `output/import.json`. Any error rolls everything back. Importing the
same unchanged result again does nothing; a changed result for an already
imported task is rejected, so later corrections need a new task.
`--dry-run` applies the result inside a transaction that is always rolled back
(on SQLite, to a private copy) and changes nothing. Both commands use the default
database, the PostgreSQL collection; `--db` selects another.

Regenerate the readable exports (`python mathdb.py export`) and run
`python mathdb.py verify` periodically.

## The result file

`output/result.json` has these sections, all optional:

```json
{
  "changes": {"concepts": [], "sources": [], "dependencies": [], "source_concepts": [], "citations": []},
  "same_as": {"candidate-slug": {"target": "existing-slug", "reason": "Same meaning: ..."}},
  "operations": {"revisions": [], "reorganizations": []},
  "concept_reviews": [{"slug": "root", "statement_prerequisites_complete": true,
                       "proof_prerequisites_complete": false, "reason": "..."}],
  "source_reviews": [{"source": "source-slug",
                      "flags": {"requirements_complete": true},
                      "flag_reasons": {"requirements_complete": "..."}}],
  "notes": "Free text for humans; ignored by the importer."
}
```

**changes** is the ingest payload documented in [API.md](../API.md). A source is
matched to an existing record by its external identifiers. A concept whose slug
already exists must have identical title, kind and description, or be listed in
`same_as`.

**same_as** maps a concept the result would create to an existing concept with
the same meaning. Every reference to the candidate slug is redirected to the
target, and the target keeps its own wording.

**concept_reviews** set `statement_prerequisites_complete` and, for theorems,
`proof_prerequisites_complete`, each with a reason. **source_reviews** set
`requirements_complete`, `introductions_complete` and `citations_complete`
independently, each with a reason. Omitted flags are left unchanged; nothing
becomes true merely because an import succeeded.

**operations** change existing records. They run before `changes`, except where
noted, and every one needs a `reason`:

- `reorganizations`: complete split, merge or retirement plans for
  `mathdb.reorganize`, with every incident relationship routed, including
  formalizations. Retirement without a replacement needs an exact
  `mathdb.retirement_inventory` snapshot and alias dispositions.
- `revisions`: same-identity changes `{slug, changes, reason, disposition,
  incident_inventory}`. The inventory must equal the concept's current incoming
  and outgoing edges, source occurrences, aliases, related links and
  formalizations (`mathdb.formalizations(db, concept=SLUG)`).
- `edge_removals`: `{prerequisite, dependent, purpose, reason}` removes a
  statement or proof role from an existing edge (run after `changes`).
- `occurrence_routings`: `{source, from_concept, to_concept, role: "relies_on",
  locator, reason}` moves one existing `relies_on` occurrence to another concept.
- `source_role_corrections`, `source_metadata_updates` (`summary`, `coverage`,
  `dependency_review`; `before` holds the exact old values),
  `locator_corrections` (`kind` is `dependency` or `source_occurrence`; `before`
  is the exact current row), `source_identifier_corrections` (`before` row,
  `replacement` `[scheme, value]` or `null`), `dependency_evidence_updates`
  (`before` row, `changes` to `rationale` and/or `locator`). These run after
  `changes`. Stale `before` rows are rejected.

Changing an edge resets the dependent's completeness flags; include a
post-change review for any concept whose flags should remain true.

## Completeness and measurement

Source reading, originality and bibliography flags are separate from each
concept's statement and proof flags. A complete statement cone says nothing about
encountered theorems' proofs, and proof-only inputs are deliberately left
unexpanded. Keep unknown, inaccessible and unresolved items false with their
reasons; never guess them away. Passing structural checks is not mathematical
review.

Record token usage with [task accounting](TASK_USAGE.md). Budgets are limits,
not completeness criteria: on reaching one, save the queue state and false
flags so a later task can resume.
