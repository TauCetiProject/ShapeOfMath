# Revise, split, merge or retire concepts

Correct the specified concept records and review every relationship affected by
the correction. Decide first whether the mathematical identity stays the same,
one record contains several different concepts, or several records describe the
same concept. Return proposed edits and the evidence for each decision.

## Inputs

You need the database to read, the identifiers or slugs of the concepts to review,
the mathematical issue that prompted the review, the repository path, and a
directory for your proposed changes. A slug is the short unique name used in
concept URLs. If the issue is unclear, inspect the records and their sources
before proposing an operation.

Read `CONCEPTS.md` for concept identity and granularity, `docs/CURATION.md` section 2
for the relationship-review procedure, and `API.md` for the edit format. Work on
proposals or a private database copy. The coordinator applies accepted changes to
the shared database. Do not overwrite shared records or exports from a private copy.

## Choose the operation

Inspect the full current records, their history, and the relevant mathematical
sources. Compare actual definitions, hypotheses, conventions and conclusions.
Names and vector similarity help find candidates; they do not establish identity.

- **Revise** a name or paragraph when it still describes the same mathematical
  concept. Preserve its UUID, the database's permanent identifier. Preserve an old
  name as a search alias when appropriate.
- **Split** a record that conflates distinct concepts. Create the replacement
  records and decide separately which relationships belong to each one.
- **Merge** records for the same mathematical concept, including equivalent
  formulations of one theorem. A new proof does not create a second theorem.
- **Retire** a false or unsuitable record when there is no equivalent replacement.
  Preserve its statement, source evidence and reason in history. A different true
  theorem is not a replacement identity for a refuted claim.

Explain why the chosen operation fits. Use precise names and at most a short
paragraph for each retained concept. Do not change a shared meaning merely to fit
one paper. Splits and merges create new replacement identities and leave the old
records in history; do not arbitrarily reuse one of the old UUIDs.

## Review every affected relationship

Read the actual rows, including historical source occurrences, rather than only
the visible graph. Save their identifiers and current values with your proposal.
For each row, explicitly keep it, change it, move it to named replacements, or
remove it with a reason.

| Data to inspect | Decision required |
| --- | --- |
| Every prerequisite of the old concept | Which replacement needs it, and for its statement, proof, or both? |
| Every concept depending on it | Which replacement does that dependent actually need? |
| Every related-concept link | Which replacements remain related? |
| Every occurrence in every source | Which mathematical meaning occurs there, in which role, and at what location? |
| Every claim that a source introduces the concept | Does the evidence establish originality for that particular replacement? |
| Every alias | Which replacement does it identify? Does it instead need to remain only a historical label? |
| Every formalization review and implementing-file mapping | Which replacement is actually defined/proved by the inspected code? |
| Completeness flags, embeddings and previous reductions | Which judgments become stale, which vectors must be regenerated, and which removed edges need reconsideration? |

Do not move all old relationships to every new concept. Inspect relationships
between two records being merged too: self-dependencies and related self-links
must be explicitly removed with reasons.

An `introduces` occurrence needs a fresh originality judgment and checked
`introduction_evidence` for its replacement. Do not copy the old claim to every
child of a split. A source may instead explain or rely on the replacement. Preserve
the old located occurrence as history.

For formalizations, use `formalization.md` to check the actual definitions,
hypotheses, proofs and contributing files. Route every existing review, including
negative and unknown judgments. Do not fabricate a positive mapping or treat a
renamed concept as automatically re-reviewed. If evidence is unavailable, record
the uncertainty and make no stronger claim.

Citations link sources rather than concepts, so splitting a concept does not
itself change citation identifiers. Check citation `needed_material`, source notes
and descriptions of imported facts if they refer to a meaning being changed.
Preserve bibliography text as printed; put corrections in assessment notes.

## Describe and check the edits

Use the operations in `API.md`. A split/merge/retirement plan must account for
exactly the current incident relationship IDs in `edge_routes`, `link_routes`,
`related_routes` and `formalization_routes`. A route names its replacements;
an empty replacement list needs a reason. Introduction routes use the structured
form containing the reviewed role and fresh evidence. Retirement also needs the
exact current inventory and a disposition for every alias. A same-identity revision
needs its own complete before/after review; it is not an excuse to skip links.

For theorem dependencies, preserve `purpose`: `statement`, `proof`, or `both`.
This is separate from `basis`, which says logical or pedagogical. An edge for a
statement cannot be removed merely because a path through proof-only edges exists.
When removing a redundant edge, preserve its evidence and a path through retained
edges with the appropriate purposes. Check that the graph remains acyclic.

If the database changed while you worked, refresh the affected records and
relationship inventory before import. The API uses an ETag, a version value sent
with a write to reject stale edits. Do not blindly retry a rejected plan. Apply
accepted reorganizations atomically so a failed operation leaves no partial split.

After import, the coordinator checks the resulting active and historical records,
all routed relationships, source roles, affected reading cones and invalidated
reviews, then refreshes embeddings and exports. Structural validation does not
establish that the mathematical routing decisions are correct.

## Return

Save the proposed operation, old and proposed concept records, the complete
relationship inventory, and a reason for every disposition. Include the exact
source/proof/code locations inspected, unresolved judgments, and any changes
needed outside the original records. Once a proposal is released for import,
leave that file unchanged and use a new numbered proposal for corrections.

Report which operation is ready, what still needs mathematical review, and which
completeness judgments must remain false. Do not mark a source inventory or a
whole cone complete merely because the reorganization passed a software check.
