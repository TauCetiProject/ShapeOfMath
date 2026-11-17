# Complete the prerequisites of specified concepts

For each specified concept, identify and record the concepts needed to understand
it. Repeat this for those prerequisites, continuing down to sets, natural numbers,
elementary logic and finite arithmetic, unless a different stopping point was
explicitly supplied. The concept together with all these prerequisites is its
**downward cone**.

For every theorem encountered in this process, also inspect one proof and record
the concepts needed for that proof. **Do not recursively investigate concepts
needed only for the proof.** Investigate one of those concepts further only if
it is independently required to understand a specified concept or its statement
prerequisites.

Use existing database records when their mathematical meanings agree. Return
proposed changes and supporting evidence; do not edit the shared database.

## Inputs

Before starting, you need:

- The database identifiers or slugs of all concepts to investigate. A slug is the
  short unique name used in database URLs. Several concepts can be handled together.
- The path to this repository and the path to the mathematical database to read.
- The directory in which to save proposed changes and notes.
- Any explicitly requested stopping point or proof to examine. Otherwise use the
  elementary stopping point above and the proof-selection procedure below.

If you received a directory containing `assignment.json`, read these values there:
`roots` lists the concepts, `repository` and `catalogue` give the two paths,
`output_directory` says where to save work, and `baseline` gives the stopping point.
Relative paths are relative to that directory. If it contains an `instructions/`
directory, read the reference files copied there; otherwise read them in the
repository. `policy-manifest.json`, when present, records the input file hashes
so later reviewers can identify the same instructions and database.

Confirm each concept's identifier, slug and meaning before starting. If they
conflict, report the conflict; do not silently select another concept. If several
cones share a prerequisite, investigate that prerequisite once and use the result
for all of them.

## Mathematical rules

A concept is one reusable definition, construction, significant theorem or
conjecture, precisely named so an expert recognizes its scope, with at most one
short paragraph. Simple definitions should be short. Do not add scope fields,
umbrella theories, notation, temporary expressions, proof maneuvers or arbitrary
hypothesis bundles. Qualify ambiguous names, such as which Riemann–Roch theorem.
A theorem remains one concept across alternative proofs/equivalent formulations.

For each candidate prerequisite, search existing names, aliases, paragraphs,
neighbors and vectors if available. Compare exact meanings/hypotheses before reuse.
Do not redefine a shared concept to fit one argument. Revisions, splits, merges
and retirements require full incident-link review, including source occurrences,
related links, aliases and formalization mappings, with explicit audited routes.
Changing a paragraph can invalidate previous completeness judgments; revisit them.

Edges point **prerequisite → dependent**. For theorem inputs, classify `purpose`:

- `statement`: needed to understand the statement, its hypotheses or its application.
- `proof`: needed for the inspected proof, without being a statement prerequisite.
- `both`: needed for both.

`basis` (logical/pedagogical) is independent of `purpose`. Do not guess an
unclassified role. If transitive reachability supplies an input, preserve its
typed witness path rather than introducing redundant direct edges.

## Procedure

1. Read `CONCEPTS.md`, `docs/CURATION.md` sections 1–3, `API.md`, and
   `prompts/reorganize-concepts.md` in the repository. Inspect schema, roots,
   existing statement cones, flags, references and proof accounts. An unreviewed
   leaf is an unfinished frontier; absence of edges does not prove simplicity.
2. Initialize a deduplicated queue with **all assigned roots**. Reuse the same
   node and investigation across shared ancestors. Keep root membership so each
   root's completed and unresolved cone can be reported independently.
3. For every reached node, inspect its exact definition/statement in the recorded
   source or a reliable authored exposition. List the necessary reusable concepts,
   including uncited background, and reconcile them with existing records/edges.
   Existing valid complete reviews can be reused with their provenance; investigate
   gaps or contradictions rather than automatically rereading or trusting a flag.
4. Enqueue **every statement/both prerequisite** that still needs review, including
   reused concepts. Continue to the declared baseline. Empty immediate lists need
   explicit review there. Never declare a higher-level object primitive simply
   because it is unfamiliar or its ancestors are hard to obtain.
5. For every theorem reached on that statement traversal, record which proof was
   inspected: source identifier, exact artifact/version/hash, section/theorem/page,
   and proof route. Reuse an existing inspected proof account when applicable.
   Otherwise first inspect the proof in the assigned/recorded source; if inaccessible,
   use an accessible reliable exposition of the **same statement**, documenting
   why it was chosen. Do not union alternative proofs' requirements silently.
6. Record **all direct concepts needed for that proof**, with brief concept records,
   evidence, purpose and rationale. Prove neither the theorem independently nor
   new subsidiary results as a way to avoid an access barrier. If the inspected
   argument imports a theorem, record that theorem as a proof input rather than
   expanding its own proof. Pure calculations belong in notes, not new concepts.
7. **Do not enqueue a proof-only parent.** Its definition/statement must be precise
   enough to identify it, but its own prerequisite lists remain unexpanded unless
   it is also reached independently through a root's statement/both edges. In that
   case expand it for that independent reason. This is a queue membership rule,
   not a request to construct the entire proof cone.
8. Certify `statement_prerequisites_complete` and `proof_prerequisites_complete`
   separately, and only with inspected evidence. An unavailable proof leaves its
   proof flag false even if statement closure is complete. Treat an open conjecture
   as a conjecture, not a theorem with an invented proof. Independent source-level
   reading/originality/citation flags are unchanged unless explicitly reassessed.
9. Preview transitive reduction as the graph grows. Preserve statement and proof
   reachability separately, with deleted-edge evidence and retained typed witness
   paths. A proof-only path cannot replace a statement edge. Do not create a cycle
   to express a mutual characterization: examine definition/proof choices, retain
   explanatory equivalences in notes, and stage any identity repair explicitly.
10. Write proposed database changes in the format documented in `API.md`.
    The coordinator uses `curation_plans.py` to check and import prepared tasks;
    see `docs/CURATION_TASKS.md`. Do not write shared data/exports. A released plan is immutable;
    correct it in a later numbered plan. Record clashes with concurrent work and
    recompute affected cones after imported changes rather than applying stale routes.

## Required outputs and stopping rule

- `cone-audit.json`: per-root stable identity, node/edge counts, statement frontier,
  theorem proof lists still unknown, and proof-only frontier deliberately unexpanded.
- Numbered payload/review sidecars, identity resolutions and full audited routes
  for any revisions/reorganizations; reduction witnesses if edges are removed.
- `proof-accounts.json`: every encountered theorem's proof choice, artifact and
  locators, complete immediate input list or exact missing information. A checked
  textbook statement without its proof does not certify the proof list.
- `report.txt`, `unresolved.json`, and a resumable `work-log.json` with queue state,
  baseline, sources inspected, reuse/new/adjusted identities and handoffs. The runner
  measures token counts with `task_usage.py` and exports `usage.json`; see
  `docs/TASK_USAGE.md`. Shared cone work has one measured task entry, not a repeated
  charge for every paper. Do not invent unavailable counts.

Recompute the union of the assigned roots' **statement cones** at completion.
Check every reachable node's statement flag and every incident dependency's purpose;
report the roots separately as well as the union. Check every reached theorem's
independent proof judgment and evidence. Run private-copy structural/DAG checks.
Track invalidated shared-node/source reviews and leave them false until rechecked.
Embeddings/exports are a coordinator step after reviewed import; do not overwrite
them from a private copy or claim mathematical completeness from passing checks.

Finish accessible work without depth/count shortcuts. If access, precise statement
or proof scope remains unresolved, keep affected flags false, report the exact
barrier and evidence, and finish other branches. A supplied token budget or deadline
requires a checkpoint, not false completion. Statement closure can be complete
while a proof inventory remains unknown; proof-only recursion is intentionally
outside this task. Do not call that a complete graph of all proofs.
