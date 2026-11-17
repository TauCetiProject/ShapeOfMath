# Concept identity and granularity

Decide whether the specified phrase or source passage denotes a reusable
mathematical concept, or whether an existing concept record needs correction.
Compare its meaning with the database before proposing a new record.

Read CONCEPTS.md, docs/CURATION.md §1, and API.md. Inspect the actual database and
source before writing. Apply authorized changes; do not stop at a list of proposals.

Identify one reusable mathematical definition, construction, significant theorem or
conjecture that an expert can identify from a precise name. Give one short informal
paragraph; use a short sentence for a simple object. Put needed qualifications in
the name/paragraph. Do not add a separate scope field or an umbrella theory node.
A named theorem is one concept across its proofs and equivalent formulations.

Search existing names, aliases, descriptions, vectors and neighbors. Compare actual
hypotheses, conventions and conclusions. Choose reuse, identity-preserving revision,
split/merge, creation, or retention in source notes. Explain the choice. A local
expression, projection label or proof maneuver is not a concept merely because the
paper names or numbers it. Use Morrison–Snyder’s normalized third twisted moment
as the exclusion example. Creating a record does not establish mathematical novelty.

For revisions, inspect every prerequisite, dependent, related link, alias and source
occurrence. Recheck original-source attribution if meaning changes. Use the full
reorganization workflow for a split/merge. Preserve UUIDs for the same identity,
audit changes, re-review invalidated lists, and refresh affected vectors. Report
the final name and paragraph, reused/new identities, relationship changes and any
uncertain mathematical or attribution judgments.

When touching an existing concept, inspect its library formalization reviews and
implementing-file mappings too. Revisions make old reviews stale; a split/merge
requires explicit formalization_routes with fresh judgments and full file sets.
If reviewing code coverage, follow prompts/formalization.md: map defining/proving
files and their associated API, exclude mere uses, and keep unknown coverage or LOC
unknown. Source ingestion and prerequisite expansion do not automatically certify
formalization.
