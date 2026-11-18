# What counts as a concept

A concept is a piece of mathematical vocabulary that a reader could reasonably
learn, retain, and reuse. It usually names a definition, a significant theorem,
or a specific mathematical object. The catalogue should resemble a list of things
a reader needs to know, or could get up to speed on, to understand a paper.

Each record has a name and one short informal definition or theorem statement.
Simple objects deserve short definitions. Any qualifications needed to identify
the object belong in the name and paragraph; there is no separate scope field.

## Names and identity

- A qualified name must distinguish substantially different meanings. For example,
  use **Intertwiner of algebra representations**, **Karoubi envelope of a category**,
  and **Simple object in an abelian category**.
- Specify conventions when they change the object: for example, the angle convention
  for **Euler measure of a surface with assigned corner angles**.
- Check conventions when combining sources: “linear category” may include
  additivity in one source and only vector-space morphisms in another. “Tensor
  category” may mean a monoidal category or additionally an abelian rigid linear
  category. Keep the distinction explicit in the names and definitions.
- Synonyms can share a record when they name the same object. An ambiguous short
  term can help search, but must not silently identify inequivalent concepts.
- A named mathematical theorem is a single concept. Alternative proofs and
  equivalent formulations attach to that theorem. A numbered proof lemma is not
  automatically an independently significant theorem.
- An umbrella such as “Tomita–Takesaki theory” is too broad; an unqualified
  “Riemann–Roch” is insufficiently specific.

## What a reader should retain

Being named, given notation, or placed in a numbered definition is not sufficient.
Ask whether the item belongs in a reader's lasting vocabulary, rather than just
their understanding of this proof. A genuinely new concept can pass this test;
prior use elsewhere is evidence, not a requirement.

The **normalized third twisted moment** in Morrison–Snyder is a local expression
used in the proof. Its formula and choice-independence lemma belong in source
notes attached to the field-of-definition argument, not in the prerequisite
concept list. The same applies to particular numbered projections, coefficient
lists, auxiliary polynomials, and small diagram calculations unless there is an
independent reason to learn that object.

Proof maneuvers such as “recursive extraction” or “geometric encoding” do not
become concepts merely because they describe an argument. A recognised mathematical
method can qualify, but must be identifiable and useful independently of that
description.

## Expanding from a paper to a collection

Maintain a concept prerequisite graph independently of the citation graph.
A missing citation does not imply missing background knowledge. Inspect each
definition, theorem statement, and chosen proof to identify what it presupposes.
Find standard expositions for those prerequisites, including textbooks and lecture
notes that the paper did not cite. A later textbook may be the best learning source.

For one expansion pass:

1. Freeze the current active concept list S₀ for the paper.
2. Review the immediate prerequisites of each member of S₀. Reuse existing concepts
   before creating new records, checking names and definitions for compatibility.
3. Record the chosen direct edges, their reasons, and useful learning sources.
   Recognising a word in a definition suggests a prerequisite; it does not prove
   that the edge is needed. Routine notation need not produce a new concept.
4. The new layer is the selected prerequisites not already in S₀. Some may already
   exist elsewhere in the collection. “New to this paper” and “new to the database”
   are different counts.
5. Stop. Mark newly introduced concepts as awaiting their own prerequisite review.
   Do not recursively follow their definitions during this pass.

The first pass produces a reviewable reading graph, not a claim that every
foundational dependence has been enumerated. Every retained seed concept gets a
review entry, including those for which the existing parents are adequate.

## Learning sources and proof dependencies

An `explains` learning-source link says where a reader can acquire a concept. It is not automatically
a source that the paper logically depends on, and it is not a priority claim.
Attaching a textbook exposition of monoidal categories must not create a strict
paper dependency on that textbook. The original unique-source requirement remains
in force for strict source edges.

Prerequisite edges point from prerequisite to dependent. They concern understanding
a definition or a chosen proof, between pedagogical and logical dependence. They
should not encode mutual relevance or create a cycle. Alternative proof routes
must be explained rather than treated as universally necessary inputs.

## Immediate coverage judgments

Five independent boolean flags record explicit curator judgments:

- `concept.statement_prerequisites_complete`: all immediate inputs needed to understand the statement or definition are recorded.
- `concept.proof_prerequisites_complete`: all immediate inputs to a selected theorem proof are recorded; their cones need not be expanded.
- `source.requirements_complete`: all concepts judged necessary to read the
  inspected source are covered by explicit `relies_on` roots and their inherited prerequisites.
- `source.introductions_complete`: all reusable concepts and significant results
  originating in the source have evidence-backed `introduces` links.
- `source.citations_complete`: every bibliography entry has been captured as text.

Each defaults to false, meaning **not certified**, rather than asserting a known
omission. A true flag is a judgment under the current concept definitions and
chosen proof or learning routes. A concept with no prerequisites or a source
with no references can have its empty list explicitly certified. Having no edges,
being marked `boundary`, or having draft/reviewed status does not certify anything.

Concept and source concept flags concern one step only: their linked concepts'
prerequisites need not be complete. Citation capture completeness does not require
identifiers, linked catalogue sources, or pedagogical judgments. All five flags
are independent. Reviews require a reason recorded in the curation history.

Changes to prerequisite edges reset the dependent concept's flag. Changes to a
concept's name, kind, definition or active status reset its own flag, immediate
dependents' flags, and source flags for its `relies_on` or `introduces` links.
Changing those link memberships resets only the corresponding source concept flag.
Changing citation membership, labels or text resets citation capture completeness;
resolving or assessing a citation does not. Changing source coverage or artifacts
resets all three source flags. Flags do not propagate recursively. Related links
do not reset them. A one-layer draft is not automatically certified complete.

## Roles of concepts in sources

`introduces` records a genuine original contribution to the literature: a reusable
new mathematical concept or significant new result. It requires a precise source
location and checked `introduction_evidence`. A source explaining a definition,
numbering a theorem, or giving a new proof of an old theorem does not establish
novelty. First appearance in our database is unrelated to mathematical origin.
Preserve independent original contributions and leave unresolved priority unknown.

`explains` records a useful exposition, recalled definition, or another proof of an
existing result. It preserves learning references without assigning priority.
`relies_on` is an explicit judgment about the actual background needed for that
source's argument. `discusses` covers other contextual mentions. Roles are independent;
a source can explain material it also requires, and a new concept taught there is
not automatically assumed as prior knowledge.

Morrison’s G₂ paper recalls Kuperberg’s web/spider construction and imports the web
basis and category equivalence. Its abstract and Theorem 2.1 credit Lehrer–Zhang
for the braid-generation result. Its alternate proof belongs to the same theorem
concept. These are explanations or inputs in Morrison, with original attribution
to the earlier works. A numbered theorem or definition in Morrison cannot reverse
that attribution. A new proof does not create a second theorem concept.

Legacy `uses` maps to `relies_on`; former exposition/definition/proof labels map to
`explains`, never automatically to `introduces`. Version 7 demotes ambiguous old
introduction claims to explanations, retains their history, and resets source
introduction-completeness judgments pending evidence-based review. Reviewed original
contributions are restored explicitly. The source-attribution manifest records the
first checked claims. The [collection review](data/full-review.json) and later
curation history in the database record subsequent origin decisions and the
remaining unresolved cases.

A source’s required frontier consists of its maximal explicitly required concepts;
their ancestors are inherited background. Located occurrences remain stored even
when a direct card is redundant. Introduction/explanation links never seed reading
requirements automatically: the global theorem graph may describe a different
proof from the source being ingested. In particular, Lehrer–Zhang must not inherit
Euler measure from Morrison’s later diagrammatic proof of the same theorem.

See [curation workflows](docs/CURATION.md) and [task prompts](prompts/README.md)
for source ingestion, recursive expansion, and all-link review during revisions,
splits and merges.

## Citations

A citation belongs to the citing source and records its original reference text,
an optional printed label, zero or more identifiers, an optional linked catalogue
source, `pedagogically_necessary`, and `needed_material`. Text can be recorded
before the work is identified; no placeholder source is required. Printed labels
are unique within a source; citations without labels are allowed.

The pedagogical judgment has three states: true, false, and null (unknown).
False means the source can be understood without following this reference, for
example a historical comparison. `needed_material` is optional free text such as
“Theorem 2.3, existence part only” or “the definition in §4”. Neither field implies
a strict logical source dependency.

Identifiers are normalized just like source identifiers. Multiple citations can
name the same identifier, while each citation can carry multiple identifiers for
the same work. The extractor recognizes explicit DOI, arXiv, ISBN, zbMATH and URL
identifiers in the text. A curator or agent can supply identifiers found elsewhere.
Resolution matches identifiers to existing catalogue sources and rejects conflicting
identities; unresolved entries remain valid. This command does not search external
bibliographic services or guess an identifier from a title. It can be rerun after
more sources are catalogued. Unknown identifiers remain recorded on the citation.

The text preserves the inspected bibliography, including PDF line breaks when
transcribed from one. Correcting text re-extracts identifiers and clears the old
resolved target; manually supplied identifiers can be supplied again in the edit.
Editing identifiers replaces manually supplied identifiers while retaining those
explicit in the current text. All prior content is retained in the curation event.

A bibliography entry is separate from the curated source-relation graph. Existing
citation/historical/strict-dependency relations retain their fact-level rationale;
adding a raw citation creates none of these edges automatically.

## Related concepts

Relatedness is an undirected link with a short mathematical rationale and optional
source evidence. It means the concepts are useful to encounter together without
asserting a prerequisite in either direction. For example, the principal and dual
even parts of a subfactor are related. The link appears from either endpoint,
is stored only once, and does not participate in prerequisite closure or DAG checks.
Cycles of related links are allowed. Use prerequisite edges when there is an
actual directed dependence; relatedness should not hide a cycle in that graph.

Splits and merges explicitly reroute or justify dropping every incident related
link, just as they do prerequisite edges and source occurrences.


## Recursive review and transitive reduction

We distinguish concepts **needed for the statement** from concepts **needed for
the proof**. Different proofs can require different background, so record which
proof was examined and where to find it. An edge's `purpose` is `statement`,
`proof`, or `both`. This is independent of the logical/pedagogical `basis`.
Definitions and constructions have prerequisites for understanding the definition. A numbered lemma
does not become a concept solely because it occurs in a proof.

The current expansion task follows **every statement prerequisite recursively**.
For every encountered theorem, also inspect a proof and record the concepts it
needs directly, with evidence and a short definition/statement for
each new parent. Do not recursively follow proof-only parents yet. If a proof
parent is independently reached through a statement path, it is expanded for that
reason. Imported theorems get the same treatment: black-box use in a particular
source does not remove the need to investigate its proof separately.

The default **Statement** cone follows `statement` and `both` edges at every
level. The **Proof** cone also follows concepts needed for the proof recursively,
showing where their prerequisites have not yet been investigated. `all` is an
inspection mode that also includes unclassified legacy edges. Unclassified edges
remain visible as a review frontier and prevent a claim of complete typed coverage.

Two separate one-step judgments are authoritative:
`statement_prerequisites_complete` and `proof_prerequisites_complete`. The latter
means that the direct prerequisites for the proof we examined are recorded; their
own prerequisites need not have been investigated. A theorem's statement list may be complete
while its proof list or proof cone remains incomplete. The older
`prerequisites_complete` flag is retained for combined/legacy reviews; new curation
must specify the two judgments explicitly. Definition/construction coverage uses
the statement judgment. Source capture flags remain independent.

Transitive reduction preserves **both** reachability relations. A statement edge
can be removed only using a retained statement path. A proof edge can use a retained
path in the statement-plus-proof graph. Unclassified edges are not silently reduced.
Prior untyped reductions may have removed statement shortcuts through proof paths;
classification must restore those statement dependencies before performing typed reduction.
Migration preserves identities, mathematical paragraphs, vectors, citations and
history; it leaves theorem-edge purposes unknown until an explicit review.

A recursive review visits every prerequisite selected by its mode and reviews
its own immediate list, continuing until an explicit primitive baseline is reached.
A missing parent list is an unreviewed frontier until a curator judges it complete.
The two initial experiments use sets and natural numbers, with elementary logic and
finite arithmetic, as primitive vocabulary. They record the baseline in each review
reason. Their completeness judgments concern the chosen definitions and proof routes.

For a transitively reduced DAG, immediate parents are the covers of the recorded
prerequisite relation. A prerequisite already accessible through another parent is
represented by a path. Thus a center can require functors while having no direct
Functor → Drinfeld center edge. Reduction acts on reachability in the combined
logical/pedagogical graph; edge bases and source evidence remain annotations.

Before deleting an edge, find an alternative path using only the edges retained by
the complete reduction. Record the original edge, its rationale and evidence, and
that retained path in the curation event. Reduce either a complete ancestor cone
or the whole DAG. A cone includes each shared ancestor once. Its longest-path depth
places every prerequisite strictly below its dependents in the visualization.

Pure transitive reduction preserves reachability and existing completeness reviews;
it never certifies unreviewed nodes. New knowledge, changed definitions, and semantic
edge corrections still trigger the normal review invalidation. For example, replacing
integer indexing with natural-number indexing is a mathematical correction, not a
transitive reduction. A new proof route may also require explicit reconsideration.

The browser's “all reviewed” message is computed from immediate-review flags across
the entire recorded cone, including the root. It is not an additional stored flag.
Incomplete cones can be drawn in full, with unreviewed nodes marked explicitly.

## Formalization in libraries

Review a concept separately in each library. Mathlib and Tau Ceti are initial
entries in an extensible registry. These judgments are independent of source
attribution and prerequisite completeness.

- `formalized`: the full stated concept is available, with selected native files
  defining/proving it or developing its core API. Its definition may be supplied
  by a checked dependency; record that ownership explicitly.
- `partial`: selected native files implement an identified part, with the missing
  mathematical scope explained. A narrower special case does not implement the
  general endpoint unless the remaining hypotheses are genuinely covered.
- `inherited`: the full concept is available through an actually checked dependency,
  but the reviewed core API selection has no native files. Name the dependency,
  its pinned revision, and its implementing declarations in the evidence.
- `not_formalized`: a documented search found no complete or partial implementation,
  including through checked dependencies, at the inspected revisions.
- `unknown`: no adequate judgment. No record means unknown, never absence.

Availability and native LOC answer different questions. Tau Ceti can import a
Mathlib definition and add useful native identities; count those native files in
Tau Ceti and the imported implementation in Mathlib. A wholly inherited concept
has zero native LOC and no native files. This is a positive, reviewed availability
claim, unlike an unknown or negative record, whose LOC is null. Never copy dependency
files into the importing project's file namespace or count an import-only wrapper.

Compare actual definitions, hypotheses, conclusions, scalar conventions, and proof
bodies, including generated declarations. A named alias is unnecessary when checked
generic constructors instantiate to the exact concept. Equivalent formulations
belong to the same concept, but explain the equivalence. For example, the two
absolute-Galois-group closure presentations are topologically equivalent; their
ambient fixed-field assertions differ over imperfect fields. A theorem about one
ambient action does not automatically transfer to the other. A roadmap, search hit,
interface, assumed result, or downstream use is insufficient.

Use a declared, bounded **core API** file selection: definitions/proofs, ordinary
identities and normal forms, universal properties, equivalent formulations,
conventional equality cases, and natural maps between instances of that concept.
Stop at separately significant named theorems, extra structures/hypotheses, new
constructions, arithmetic/geometric specializations, and applications. A short
proof from the concept does not by itself make the new endpoint its core API.
Cauchy–Schwarz norm/equality forms qualify; weighted Young does not. Hull membership,
finite-combination descriptions and images qualify; Carathéodory and compactness
are separate endpoints. Half-braiding identities qualify for the Drinfeld center;
rigid/pivotal/ribbon enhancements are outside this generic selection.

For each selected repository-relative `.lean` file, record a contribution note and
representative declaration anchors. State whether it supplies the definition,
proof, equivalent presentation, or API; do not call an imported definition native.
Review nearby candidate files and preserve reasons for consequential exclusions.
A file contributes to several concepts only with direct evidence for each; do not
map every group file to abelian groups merely by inheritance. File selection is a
bounded curation judgment, not certification that every associated result or every
concept inside the file has been catalogued. Formalization completeness and API
file-selection breadth must not be conflated.

Pin the library revision and its dependency revisions independently. Inspect and
measure the same committed bytes; checkout HEAD may differ, and paths may have
moved. `formalization measure --revision COMMIT` avoids changing a working checkout.
Every file count records a commit, timestamp and optional hash. LOC means physical
lines including comments/blank lines and a final unterminated line counted once.
A source review is not a fresh Lean build or a transitive axiom audit; state the
verification actually performed.

The estimate for concept C in library L is
`sum(file LOC / number of currently mapped active concepts for that file)` over
C's native files. Partial reviews participate; their estimates describe only the
implemented part. All current mappings enter the denominator even in a filtered
query. Libraries are not combined implicitly. Missing file counts give null total
LOC plus a separately named `known_loc` subtotal and a measured-file count. Actual
empty files contribute zero. Only `inherited` has an explicitly reviewed zero-file,
zero-native-LOC result. All current shares of each measured file sum to its LOC;
no rounded shares are stored.

These are **catalogued mapped concepts**, not a census of everything in a file.
An early mapping may receive most of a large mixed file and shrink as other concepts
are mapped. The estimate measures allocated whole-file size, not proof length.

A concept name/kind/paragraph revision makes its earlier review stale: effective
status becomes unknown and its old files cease receiving shares until reviewed.
Preserve the earlier evidence. Splits/merges explicitly route every library review,
including inherited and negative judgments, with fresh evidence and full file sets.
Retired concepts retain history but receive no current shares. Updating shared file
counts affects all mappings; it does not itself re-review mathematical coverage.

The [pilot review](data/formalization-pilot-review.txt) records concrete inclusions,
exclusions, ownership decisions, and limits of the first six-concept sample.
