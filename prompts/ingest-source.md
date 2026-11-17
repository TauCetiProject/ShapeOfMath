# Identify the concepts in a paper

Read the specified paper and record the mathematical concepts a reader needs to
know, the concepts it introduces, and the concepts it explains. Match these to
existing database records wherever their mathematical meanings agree.

Return proposed database changes and the evidence for them. Do not edit the shared
database. This task stops at identifying the paper's concepts and its required
background. Expanding the prerequisites of that background is a separate task,
described in [expand-prerequisites.md](expand-prerequisites.md).

## Inputs

Before starting, you need:

- The paper's identifier or URL, and a local PDF if one is available. If a particular
  version was requested, use that version.
- The path to this repository and the path to the mathematical database to read.
- The directory in which to save your work.
- Any restriction on coverage. Unless specified otherwise, read the entire paper,
  including appendices, and capture its bibliography.

If you received a directory containing `assignment.json`, these values are in
that file: `source_identifiers` identifies the paper, `artifact.path` gives the
local paper when supplied, `repository` and `catalogue` give the two paths,
`output_directory` says where to save work, and `coverage` says what to inspect.
Relative paths are relative to that directory. If it contains an `instructions/`
directory, read the copies of the reference files there; otherwise read them in
the repository. `policy-manifest.json`, when present, records the file hashes used
to prepare this task so later reviewers can identify the same inputs.

If a required input is missing, state exactly what is missing. Obtain an accessible
copy if necessary, and record its URL, version and SHA256 hash before reading it.
Do not replace the requested paper with another one.

## What to record

A concept is a reusable definition, construction, significant theorem or conjecture
with a precise name an expert can recognize and at most one short informal paragraph.
Use a sentence for simple objects. Include necessary qualifications in the name and
paragraph: “linear intertwiner of G-representations” is preferable to an ambiguous
“intertwiner”; specify which Riemann–Roch theorem. Do not add a scope column.
Keep a named theorem as one concept across its proofs and equivalent formulations.
Do not create umbrella theories, routine notation, arbitrary proof steps, temporary
hypothesis bundles or paper-local expressions. A named local calculation such as
“normalized third twisted moment” does not become enduring vocabulary.

Search the supplied catalogue's names, aliases, descriptions and neighbors before
creating each record; use vectors if available. Compare actual definitions,
hypotheses and conclusions, not name similarity alone. Reuse compatible identities.
For an imprecise/incompatible existing record, follow the full revision/split/merge
workflow, reviewing all prerequisites, dependents, source occurrences, aliases,
related links and formalization mappings. Keep existing UUIDs for the same identity.
Stage such changes for review rather than mutating shared data.

Use these source roles independently, with precise locations and reasons:

- `relies_on`: prior knowledge actually needed to read this paper's argument,
  including uncited background. Do not assume a result introduced here as prior knowledge.
- `introduces`: a reusable original contribution, with checked priority evidence.
  A theorem number, a new database record or a new proof of a known theorem is not
  evidence of originality. Unknown origin stays unknown.
- `explains`: a useful exposition, recalled definition, or another proof of a known result.
- `discusses`: contextual or passing mention.

An original proof does not create a second theorem concept. A later proof's methods
must not become requirements of the original paper through that shared theorem.
For example, Morrison's G₂ paper recalls Kuperberg's webs/spider and gives another
proof of a Lehrer–Zhang theorem; it does not introduce those concepts/results.
Preserve each source's actual proof route and required knowledge separately.

Only explicit `relies_on` roots seed source reading cones. Introduced, explained
or mentioned concepts do not seed them automatically. Keep located occurrences
even where a prerequisite is inherited transitively. Citations, origin claims and
strict source dependencies differ: ordinary textbook background does not justify
a strict unique-source dependency.

## Procedure

1. Read `CONCEPTS.md`, `docs/CURATION.md` sections 1, 2 and 4, `API.md`, and
   `prompts/reorganize-concepts.md` from the repository. Inspect schema
   and catalogue version. This task identifies the paper's concepts; it does not include recursive
   prerequisite expansion. Those files explain the complete database edit rules.
   Report material contradictions instead of guessing.
2. Resolve the source identity and all its identifiers. Read the specified version
   of the paper, including proofs, appendices, credits and references. Abstract-only
   extraction cannot certify a full source inventory. Record inaccessible sections.
3. Keep a list of candidates in `candidate-ledger.json`. For each candidate,
   record its proposed name and paragraph, kind, paper location, existing concept
   to reuse or reason to create one, source roles, attribution evidence, and any
   exclusion or uncertainty. Consider all significant definitions/results,
   not just named or cited ones; exclude local expressions with reasons.
4. Identify prior knowledge needed for the actual paper, including uncited
   background. Use existing prerequisite paths to
   distinguish concepts required directly from those already brought in by them. Do not recursively expand the whole graph
   in this job; write its exact root IDs/slugs for subsequent cone jobs.
5. For originality, inspect contribution claims and predecessor credits. Verify
   relevant predecessors where accessible. Do not certify an unresolved priority
   claim; preserve what was inspected and what is missing. Do not independently
   develop a new proof or repair a paper to finish an inventory. If a claim appears
   false, preserve evidence and request a focused mathematical review; never install
   it as a known true theorem. Existing false active claims need audited retirement.
6. Unless bibliography capture was excluded, record every entry as printed, including textual
   references not resolved to identifiers. Store checked identifiers; missing ones
   remain unknown. `pedagogically_necessary` is true/false/null, and `needed_material`
   may specify a theorem/section or the exact part used. Do not invent identifiers.
7. Write proposed database changes in the ingest format documented in `API.md`.
   The coordinator checks and imports prepared tasks using `curation_plans.py`,
   as documented in `docs/CURATION_TASKS.md`. A check does not certify mathematical
   completeness. Do not write the shared database or shared exports. A released plan is immutable; corrections
   use a new numbered plan. Distinguish self-review from independent peer review.

## Required outputs and stopping rule

- `candidate-ledger.json`: retained/reused/new/revised/excluded candidates and
  exact evidence, inspected version, and decisions.
- Numbered `plan-NNN.json` and `plan-NNN-review.json`, plus resolutions or audited
  reorganization plans where necessary. If the import format uses `reviewed_ready`, that means
  the proposed changes are ready to import, **not** that all mathematical inventories are complete.
- `cone-roots.json`: all explicit reading roots by stable ID and current slug,
  source identity, and the point at which later prerequisite expansion should stop.
  Use sets, natural numbers, elementary logic and finite arithmetic unless another
  stopping point was explicitly requested. No introduction-only roots.
- `report.txt` and `unresolved.json`: inspected coverage, evidence, independent
  completeness judgments and concrete remaining questions.
- `work-log.json`: actual task sessions and handoffs. Token usage, when reported by the
  agent software, is recorded by the runner with `task_usage.py` and exported to
  `usage.json`; see `docs/TASK_USAGE.md`. Keep shared prerequisite tasks separate.
  Never estimate elapsed work or token counts as if measured.

Review `requirements_complete`, `introductions_complete`, `citations_complete`
independently. True means the immediate inventory was actually checked; false
means unknown/incomplete, not an assertion of absence. An empty introduction list
can be certified after a genuine review. Source flags say nothing about full cone
closure or concept proof completeness. Leave irrelevant flags unchanged.

Finish accessible inventory work. If an artifact, exact statement, access or priority
barrier remains, report it and leave only affected judgments false. Do not silently
stop at an arbitrary concept count, change scope, invent a primitive baseline, or
declare success because the recorded graph has no unfinished leaves. A supplied token budget or deadline requires a resumable checkpoint and explicit remaining work; it
never authorizes certification. Finish by checking that outputs agree with the
catalogue snapshot and list all assumptions required for the next worker.
