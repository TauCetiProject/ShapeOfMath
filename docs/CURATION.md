# Curation workflows

For a fresh worker with no conversation history, use the bounded
[source inventory task](../prompts/ingest-source.md) or
[multi-root cone task](../prompts/expand-prerequisites.md), with a pinned package prepared
according to [the dispatch contract](CURATION_TASKS.md). These separate paper
inventory from recursive expansion; the sections below give the full edit policy.

The current recursive task distinguishes concepts needed for a theorem's statement
from concepts needed for its proof. Record which proof was examined, since proofs
can require different background. Dependency `purpose` is `statement`, `proof`, `both`, or explicitly
`unclassified`; it is separate from logical/pedagogical `basis`. Follow every
statement dependency recursively, and record each encountered theorem's direct
prerequisites for the proof without following proof-only edges yet. The two immediate completeness
judgments are `statement_prerequisites_complete` and
`proof_prerequisites_complete`; source flags stay independent. The default cone is
statement-only; the proof view follows both kinds and exposes unfinished proof
frontiers. Every workflow below must preserve this distinction. Reduction must
preserve both reachability relations, so proof paths cannot replace statement edges.

Read [CONCEPTS.md](../CONCEPTS.md) for mathematical identity and granularity, and
[API.md](../API.md) for executable operations. The [prompt collection](../prompts/README.md)
provides task templates. These workflows apply to both human and agent curation.

## 1. Identify, create or revise a concept

A record names one reusable mathematical definition, construction, significant
theorem or conjecture. An expert should identify its subject and extent from the
name and its short paragraph. Examples are Convex hull, Independent set in a graph,
II₁ subfactor, Jones’s allowed index theorem for II₁ subfactors, and Serre relations
for a Lie algebra. Qualify ambiguous names in the name and paragraph. There is no
separate scope field. Simple concepts deserve very short definitions.

1. Search active names, aliases, descriptions and nearby nodes. Use vector search
   to find candidates, then compare actual definitions. A missing embedding or a
   different name does not establish that a concept is absent.
2. Compare hypotheses, conventions, mathematical objects, and theorem conclusions.
   Reuse an identical concept, including across different fields or sources.
   Equivalent formulations and new proofs normally belong to the existing theorem.
3. Correct an imprecise name/paragraph in place when mathematical identity is
   preserved. Keep the UUID; retain an old title as a search alias. If meanings
   diverge, follow the split workflow. A conventional special case can be a
   separate concept when it has independent mathematical significance.
4. Keep calculations, named local expressions and proof steps in source notes or
   dependency rationales. The normalized third twisted moment in Morrison–Snyder
   is the regression example: a useful expression in that proof, not lasting
   vocabulary a reader should acquire as a separate concept.
5. Supply a concise definition or complete significant theorem statement. Do not
   replace an ambiguous umbrella with several vague umbrellas. Check that the
   paragraph is compatible with every source using the record.
6. Review both incoming prerequisite and outgoing dependent edges, related links,
   aliases and every source occurrence. A renamed theorem can retain its links;
   a changed hypothesis may invalidate them. Record each keep/change/drop decision.
7. Use an audited revision, or an atomic reorganization where identity changes.
   Recheck affected completeness flags and regenerate invalidated embeddings.

Creating a record today does not make today’s source its mathematical origin.
An unknown original source can remain unknown while the concept is used and taught.

## 2. Modify, split or merge, reviewing every link

First capture a full snapshot and the current API ETag. `GET /state` contains raw
link IDs; `GET /concepts/SLUG` provides neighboring concepts and source occurrences.
Inspect active and historical records, rather than relying on the visible graph.

Use `revise` / `PATCH /concepts/SLUG` for the same mathematical identity. A split
has one old concept and at least two new ones; a merge has at least two old concepts
and one new one. Keep retired records and their history. Do not reuse an old UUID
for one side of a split or arbitrarily choose one UUID as a merged identity.

If a recorded claim is refuted and has no equivalent valid replacement, retire
it rather than keeping an unqualified theorem active with incomplete review
flags. Preserve the printed claim, counterexample and source locations in the
audit and source notes. Use an explicit retirement plan with an exact current
inventory and a reason for every removed relationship and historical alias;
see [the API retirement contract](../API.md). Review dependents and source
inventories afterward. A true theorem with a different conclusion is not a
replacement identity for the false claim.

Build an inventory and disposition for:

| Relationship or data | Required review |
| --- | --- |
| Every incoming prerequisite edge | Which replacement(s) need this input? Is the rationale and proof route still valid? |
| Every outgoing dependency edge | Which replacement(s) does the dependent need? Does it need several? |
| Every related link | Which replacement is actually related, and why? Drop self-links after a merge with a reason. |
| Every source occurrence, in every role | Does it refer to one, several, or none of the replacements? Recheck location and notes. |
| Every introduction claim | Re-evaluate originality for each replacement. Evidence for the old concept is never copied automatically to all children. |
| Library formalization reviews and file mappings | Recheck definitions/theorems/API in code and explicitly route every review, including negative judgments, with fresh evidence and full file sets. |
| Aliases | Put each unambiguous synonym on the correct replacement. Preserve ambiguous historical terms without conflating meanings. |
| Vectors, review flags and historical evidence | Retire old vectors, embed new records, and re-review invalidated direct lists. Inspect relevant reduction history. |

Citations and source relations point to sources, so their identifiers need no concept
rerouting. Inspect their `needed_material`, imported-fact descriptions and source
notes if these mention an affected meaning. Preserve bibliography text as printed;
edit the assessment or add a correction note instead of silently rewriting history.

The reorganization manifest must contain exactly the IDs of all incident current
`edge_routes`, `link_routes`, and `related_routes`. Each route has `replacements`;
an empty replacement list needs a nonempty reason. Route both endpoints of an
internal edge when merging, or explicitly drop it. Check every new endpoint,
mathematical rationale, source locator and relationship role. Do not send all links
to every replacement merely to satisfy the routing checker.

For source links, strings remain supported for ordinary routing:

```json
{"replacements": ["replacement-concept"]}
```

An introduction must use an explicit object with a reviewed role and fresh evidence:

```json
{
  "replacements": [{
    "concept": "replacement-concept",
    "role": "introduces",
    "locator": "Definition 3.1",
    "introduction_evidence": "The paper explicitly constructs this new object; the earlier object has different defining data."
  }]
}
```

A replacement can instead be `explains` or `relies_on`. Evidence strings must state
what was actually checked; the illustrative sentence above is not a substitute for
source review. A merge may legitimately retain multiple independently supported
origin claims. The original source occurrences remain attached to the superseded
record as historical evidence, and new active occurrences are routed explicitly.

Submit the plan with `POST /reorganize` and `If-Match`, or `mathdb.reorganize` /
`python mathdb.py reorganize PLAN.json`. The operation rolls back on missing routes,
bad endpoints, missing origin evidence or cycles. A conflict requires refreshing
and reviewing the plan, not blindly resubmitting it.

Validate the resulting statements, retained and retired IDs, all incident link
counts/roles, alias placement, source attribution, and affected reading cones.
Preview and apply transitive reduction where appropriate. Semantic changes reset
reviews; a pure reduction preserves existing ones. `verify` must pass and active
concept vectors must be current. Preserve before/after data and reasons.

## 3. Fill the downward cone of a concept

Use `cone ROOT` or `GET /concepts/ROOT/cone` to inspect the whole recorded ancestor
DAG. A leaf with no review is an unexplored frontier. It is not evidence that the
concept is elementary or needs no prerequisites.

1. State the target meaning, chosen definition/proof route, and stopping baseline.
   The existing experiments treat sets and natural numbers, elementary logic and
   finite arithmetic as primitive vocabulary. Use that baseline deliberately;
   unfamiliar higher-level objects cannot be declared primitive to finish faster.
2. Put the root in a work queue. Inspect its statement, definition, and selected
   proof in primary sources or reliable authored expositions. Source citations
   help locate imported results; they do not enumerate uncited background.
3. Identify necessary reusable concepts, rather than creating a node for every
   word, notation or proof maneuver. A theorem may have alternative proofs; record
   the selected route and its evidence rather than merging their inputs silently.
4. Search the database before adding each parent. Inspect meaning and conventions
   even for an exact name match. Reuse, revise, split or merge existing concepts
   with the full link review above. Record a useful exposition separately from
   the source that originally introduced the concept.
5. Add justified edges prerequisite → dependent. If an input is already reachable
   through another parent, a path suffices. Preview reduction and retain every
   removed edge’s evidence and a witness path made only of retained edges.
6. Queue every statement parent that still needs review, including reused nodes. An already
   existing record is not automatically an already expanded record. Deduplicate
   the queue for shared ancestors; record one mathematical concept only once.
7. Certify an immediate list only after reviewing it. Review an empty list explicitly
   at the stated baseline. New parents start unreviewed. Revisions to a shared
   concept can invalidate reviews done earlier in the pass; revisit these nodes.
8. Continue until every reachable concept is reviewed under the baseline, or report
   an explicit unreviewed frontier with the missing work and leave its flags false.
   Do not silently stop at an arbitrary depth or set flags from node existence.

At the end, recompute the cone and reduction plan. Confirm shared nodes are unique,
every edge points in the right direction, every removed shortcut has a retained
path, and every claimed review is still valid. Report node/edge counts, baseline,
reused/new/adjusted concepts, changes outside the initial cone, learning references,
and unresolved questions. Full-cone review is computed from local flags, not stored
as another certification. Source completeness flags remain independent.

## 4. Ingest a source: prerequisites and original contributions

### Inspect the actual work

Resolve the source UUID and identifiers before adding another record. Several DOIs,
an arXiv identifier, URL or ISBN may identify one work. Preserve the exact inspected
artifact/version and locations. Read its contribution statements, definitions,
theorems, proofs, references and credit to predecessors. A title, abstract, citation
list or theorem-number extraction alone is insufficient for a complete ingestion.

Prepare four separate judgments for each candidate occurrence:

- **`relies_on`**: knowledge needed for the inspected source’s actual argument.
- **`introduces`**: an enduring concept/result originating in this work, supported
  by an explicit `introduction_evidence` judgment and a location.
- **`explains`**: a useful exposition, recalled definition or another proof of an
  existing concept/result. Preserve learning references without assigning priority.
- **`discusses`**: contextual mention that is neither an input nor an explanation
  or original contribution.

Several roles can apply, but never infer them from one another. In particular,
“Definition 2.1” and “Theorem 3.2” are locations, not evidence of novelty. A new
proof of a known theorem uses the same concept and can get an `explains` link.
A source introducing a new concept is not assumed to require that concept as prior
knowledge. Existing concepts can originate in an older source newly added today;
a freshly created concept record can originate in a paper centuries old.

For a positive origin claim, inspect the paper’s claim of contribution and its
attribution of earlier work. Check cited predecessors when relevant. Match the
same mathematical statement/object across conventions. Record the actual evidence
and preserve independent discoveries or unresolved priority. A proof, numbered
definition, publication date, or “earliest source currently in the database” is not
sufficient by itself. Leave the origin unresolved when the evidence is insufficient.

### The G₂ regression example

Morrison’s *The braid group surjects onto G₂ tensor space* says in its abstract that
Lehrer–Zhang proved the surjectivity result and that this paper gives another proof.
Section 1 recalls Kuperberg’s spider; p. 190 explicitly imports the web-basis and
category-equivalence theorems from Kuperberg. Therefore:

- Do not credit Morrison with introducing G₂ spiders, G₂ webs, non-elliptic webs,
  their basis theorem, or the braid-generation conclusion.
- Record the original Kuperberg and Lehrer–Zhang attribution with source evidence.
  Kuperberg’s earlier 1994 graph calculus and his 1996 spider/basis work are both
  relevant; preserve the distinction between the original construction and later
  terminology/formalism.
- Retain Morrison as an explanation and alternate-proof source. Its original
  contribution is a proof; this does not create a second theorem concept.
- Use the imported web-basis/equivalence results as prerequisite roots. The web
  basis already depends on non-elliptic webs → G₂ webs → G₂ spider. Those appear
  transitively in the reading cone and need no duplicate direct prerequisite card.
- The chosen diagrammatic proof can need Euler measure. Lehrer–Zhang’s earlier
  paper does not inherit that requirement just because it introduced the same
  theorem. Read each paper’s argument separately.

### Build the source-specific reading frontier

Select what a reader must know for this source’s argument, including uncited
background. Record explicit `relies_on` judgments with locations and reasons.
Reduce the visible frontier to its maximal required concepts; expand their full
prerequisite cones to obtain inherited background. Preserve located occurrences
for provenance even when a direct card is redundant. A source’s introduced or
explained conclusions must not automatically seed its requirements: they may have
different proofs from the one selected in the global concept graph.

The API’s `requirements.direct` and `requirements.inherited` implement this
frontier over explicit required occurrences. They show one concept per mathematical
identity and tell which direct roots bring an inherited concept into the list.
Raw occurrences remain in `source.concepts` and the database for editing/auditing.
Reusing a concept never creates a novel-source claim automatically.

### Citations, source dependencies, and completion

Optionally transcribe all references as printed, resolve identifiers without
inventing them, and link existing source records. Citation pedagogical necessity
is true/false/unknown, independently of citation capture. `needed_material` records
what is actually imported, such as a theorem number or part of a proof.

A cited source, an original-source credit, and a useful exposition are different
from a strict unique-source logical dependency. Create a strict dependency only
for a particular indispensable research fact whose availability beyond that
source has been reviewed. Standard textbook facts do not acquire strict edges.

Judge the flags independently:

- `requirements_complete`: all necessary concepts for reading the source have
  explicit judgments or are inherited through its required frontier.
- `introductions_complete`: every genuine reusable original contribution has
  been considered, with evidence-backed links for retained concepts. This can
  certify an empty list after reviewing a source that only gives another proof.
- `citations_complete`: every bibliography entry has been captured as text,
  even if identification or pedagogical assessment remains unfinished.

Leave a source flag false for a partial inspection or unresolved relevant question.
A false origin-completeness flag means an empty introduction list is unknown,
not a claim that the work introduced nothing. Distinguish that case in reports.
Ordinary ingestion never certifies flags automatically. Concept prerequisite
reviews and source-level reviews are independent.

## Finish and report

Use audited APIs/core operations, preserve stable identities and historical records,
and keep reproducible builders/plans in agreement with live curation. If a needed
metadata edit lacks an endpoint, use a reviewed SQLite transaction with explicit
before/after curation events. Never make silent data edits. Check `verify`, active
embedding freshness, affected cone reachability and source roles. Test the invariants
you changed, including the G₂ attribution example. Report actual edits, reviewed
coverage, unresolved judgments and concrete references.

## 5. Review formalization and implementing files

Use [the formalization prompt](../prompts/formalization.md) for both initial reviews
and updates. It covers scope, revisions, mathematical review, file selection,
measurements and audited imports. Executable commands are in [API.md](../API.md). The library registry initially contains `mathlib`
and `tau-ceti`; record their repository URLs through the audited library operation
when known. Additional libraries use the same schema.

1. Inspect the concept's exact statement and existing library reviews and files.
   Search the actual library at a stated revision. Inspect declarations, hypotheses,
   proof bodies and any remaining assumptions or placeholders. A search hit, import,
   roadmap or downstream use is insufficient.
2. Decide `formalized`, `partial`, `inherited`, `not_formalized` or `unknown` separately for each
   library. Explain the comparison and inspected revision in `evidence`; identify
   what is still missing for partial coverage. Negative searches are scoped to what
   was actually checked, not timeless claims of absence.
3. For native positive/partial coverage, select files implementing the definition, theorem,
   associated API and immediate consequences. Record each canonical repository-relative
   path, its contribution (`note`), and optional declaration names (`declarations`).
   Declare the bounded core API selection from CONCEPTS.md. Record representative
   declaration anchors and meaningful excluded candidates. Do not include every
   importer, extra-structure theorem, or prerequisite file. Reuse the shared file
   record for other concepts mapped to the same path.
4. Save the full file set with the review. Empty file sets are required for
   inherited, negative or unknown reviews. This atomically replaces the old set and audits the old data.
   A stale review must be consciously rechecked rather than mechanically refreshed.
5. Measure files from a local Git repository using `formalization measure`, which
   reads committed bytes at `--revision COMMIT` (HEAD by default) and ignores worktree edits. Every counted file
   must exist as a regular tracked file; a missing file aborts the batch. Alternatively,
   record a checked whole-file count with its revision via `formalization file`.
   Clear an obsolete count with `loc: null`. Renames require reviewing the mapped paths.
6. Inspect the LOC report, including unknown counts and the denominator for each
   file. Shares use every current active mapping, including partial implementations,
   regardless of report filters. Per-file revisions are visible; a report of counts
   from different revisions is not a claim about one repository snapshot.

For concept revisions, review formalizations along with sources and incident links.
For splits/merges, `formalization_routes` must cover exactly the IDs of the old
reviews. Each replacement is a complete object with `concept`, `library`, `status`,
`evidence` and `files`; its library must match the old review. Never blindly copy
old positive or negative judgments. Empty replacement lists need a drop reason.
When merging two reviews for one library, consolidate their file sets/evidence into
one replacement and explicitly drop the duplicate route with a reason. Old reviews
remain attached to retired concepts as history. Verify and regenerate exports.

For inherited availability, inspect the exact dependency pin in the project's
manifest and the actual declarations/proofs at that dependency revision. Record
those separately from the project revision. An inherited-only review has no native
files and zero native LOC. A borrowed definition plus native core API can be
`formalized`, with ownership explicit; only native files get that project's LOC.
Do not infer absence from the lack of a project-owned definition.
