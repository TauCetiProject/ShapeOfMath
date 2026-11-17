# Review formalization coverage

Determine which specified mathematical concepts are implemented in the specified
formal mathematics libraries. For each concept and library, inspect the actual
code, record what it defines or proves, identify the files that contribute, and
record what remains missing. Use the same procedure when reviewing a concept for
the first time or refreshing an earlier review.

## Inputs and responsibility

Before starting, identify:

- The database and the concepts to review. An explicit list limits the task to
  those concepts. For a general request to update coverage, use the whole active
  catalogue, including concepts without existing reviews.
- The libraries and their repository locations. For a general request without a
  library restriction, use Mathlib and Tau Ceti.
- The exact commits to inspect. If the user requests current upstream code,
  resolve and record the upstream default-branch commits before reviewing it.
- Where to save proposals, evidence and measurements.
- Whether you are reviewing proposals or coordinating their application.
  Mathematical workers return proposals. The coordinator applies accepted changes
  through the database's audited operations and regenerates exports.

Read `CONCEPTS.md`, `docs/CURATION.md` section 5 and `API.md` in the repository for
concept meanings, file-selection policy and executable database operations.
Mathematical matching, code inspection and independent review happen in subagents,
following `AGENTS.md`. The coordinator handles scope, snapshots, software checks
and mechanical imports. A worker can perform its assigned review directly; it
need not delegate the same task again.

## Establish the scope and baseline

Honor the user's stated scope. Unless the user narrows it, “update formalization
coverage” means the whole active catalogue in Mathlib and Tau Ceti: refresh existing
reviews AND investigate unreviewed concepts. A request for particular concepts or libraries overrides this default. Do not
substitute a small sample for the requested scope. Inventory the data and
prepare snapshots before starting the delegated work.

Freeze the intended concept roster at the start: UUID, slug, title, paragraph,
kind, active status and concept revision. Record all selected concept/library
pairs, including unknown/unreviewed ones, and retain the existing reviews/files.
This is the update baseline; concepts ingested concurrently belong to a later
pass unless explicitly added. State the libraries and scope in the run manifest.

Read each library's registry entry and repository remote. Resolve current upstream
default-branch commits unless the user supplies revisions, and pin the exact SHAs.
Inspect committed bytes using immutable snapshots or git show. Do not inspect local
uncommitted changes as if they were upstream, reset another checkout, or assume its
HEAD equals the selected upstream revision. Inspect the importing project's actual
dependency manifest and pin the supplying library separately. Its dependency may
be older than the independently reviewed Mathlib snapshot.

## Delegate mathematical work and review proposals

Follow AGENTS.md: all mathematical processing, source reading, concept matching,
file selection, and mathematical review happen in subagents. The coordinator
handles scope, snapshots, software, structural checks and mechanical audited
imports. Give each worker disjoint concept/library pairs, exact concept paragraphs,
current records, immutable revisions, and these instructions. Workers return
proposals and evidence; they do not overwrite the live database independently.

For expansion, search the full scoped roster, reuse concept identities, and batch
related entries to expose shared files. Name/vector searches locate candidates;
actual declarations, hypotheses, proof bodies and conventions decide the match.
A missing hit remains unknown until a real scoped negative review supports absence.
Before classifying a concept as inherited, enumerate its native namespace directory
and direct API siblings, then search representative declaration names and related
formulations. Do not truncate a broad repository filename listing so early that
native Basic/API files disappear from view. A checked supplying dependency proves
availability; it does not by itself establish absence of native contributions.

For existing records, inspect every selected file and its representative anchors,
check renamed/moved/removed declarations, and search nearby API for meaningful
changes. Review partial, inherited and negative records too; an implementation
might have appeared or been completed.

For analytic/function-space matches, identify the topology and the exact kind of
regularity being required. Joint or locally uniform regularity must not be silently
replaced by separate-slice regularity, or conversely. If a catalogue paragraph is
ambiguous about that distinction, state the interpretation and its source evidence;
leave the stronger unidentified scope unresolved rather than inventing equivalence.

Check numeric normalizations explicitly, including distance conventions and
constant factors, Fourier/convolution scalings, measure normalizations and signs.
Matching a familiar name is insufficient when the library uses a different factor;
record the exact checked conversion and keep any unverified conversion unresolved.

Check the domain of generic and totalized constructors. Integrals, divisions,
limits and similar library functions may return a default value outside the intended
mathematical domain. Verify the integrability, nonzero-denominator, existence or
other domain hypotheses needed for the catalogue meaning; a well-typed expression
alone does not establish the intended definition or theorem on invalid inputs.

Review every material clause in the catalogue paragraph. If it asserts an
algorithmic complexity bound, quantitative normalization, uniqueness, equivalence,
or realization theorem in addition to a definition, distinguish which clauses the
checked source establishes. A formula or implementation alone does not certify an
asserted operation-count bound. Record the unresolved clause as partial/unknown
rather than silently dropping it, and do not rewrite the concept to force a match.

Keep statement formalization distinct from a proof. A proposition declaration or
a theorem assuming the desired conclusion does not prove a theorem entry. For
conjecture entries, state explicitly whether the evidence supplies only the formal
statement; never describe an unproved conjecture as proved. Mark that distinction
in saved evidence, the webpage, readable exports and aggregate counts; a positive
conjecture-statement record is not a solved conjecture. Record uncertainty
about representation or file attribution explicitly rather than inventing a file
or presenting that uncertainty as a mathematical absence.

Use these database statuses. The criteria for selecting the associated API
are described immediately below and in `CONCEPTS.md`:

- `formalized`: complete availability with selected native definition/proof/API.
- `partial`: identified native coverage with an explicit missing endpoint/scope.
- `inherited`: complete availability through a checked dependency, no selected
  native files, zero native LOC. Record supplier, pinned commit and declarations.
- `not_formalized`: a documented search found no native or dependency implementation.
- `unknown`: an adequate review is unavailable or unfinished; never invent absence.


The selected API consists of definitions/proofs and their ordinary identities,
normal forms, universal properties, equivalent presentations, equality cases and
natural maps between instances. It is not an inventory of every theorem about the
concept. For example, include ordinary Cauchy–Schwarz equality cases but not the
separately significant weighted Young inequality; include convex-hull membership
and image lemmas but not Carathéodory's theorem or compactness results; include
basic center identities but not extra rigid/pivotal/ribbon structure.

Inspect both statement and proof locations. A file named `Defs.lean` may contain
the proof while `Basic.lean` exposes its API. Generated declarations, one-sided
class axioms with proved converses and generic constructors require inspection.
For complex Cauchy–Schwarz, check the conversion between the real-part and
modulus-squared formulations. For absolute Galois groups, distinguish the group
presentations using separable/algebraic closures from the different fixed-field
assertions over imperfect fields. Identify which library proves any comparison.

A dedicated alias is not required when an independently checked generic
constructor is already the exact representation. Ordinary sequences and real
sequences can use the language's function type at the checked toolchain revision;
parameter types are identified separately, and no fictitious native sequence file
is invented. Such a source-backed representation claim is different from merely
being able to write down a proposition: theorem entries still need an actual proof.
If representation or file attribution is genuinely unresolved, record that exact
uncertainty instead of claiming absence.

When only a proper part of the catalogue meaning is available through checked
dependencies and no native core files qualify, save `unknown` with an empty file
set under the current schema. State explicitly that this is **checked dependency-only
partial availability**, name the covered component and supplier/pin/anchors, and
state the unresolved endpoint. Do not call it inherited, invent native files, or
describe it as an unsearched concept. Report this subgroup separately when possible.
The present status field combines availability extent and native ownership; this
fallback records that limitation without requiring a schema change during a pass.

For a generic representation, write the actual mathematical/type-level
instantiation, identify every supplied semantic input, and state which structures
or existence results are not being constructed. Supplied inputs may match the domain
of a bare definition; they may not assume away a realization, existence, comparison
or other material endpoint asserted by the catalogue. Identify the exact supplying
language/library constructor and revision. State whether the evidence was inspected
in source or actually elaborated/build-checked as a Lean declaration.

An imported definition plus genuine native ordinary API can count. For example,
Tau Ceti's generic group power-law file contributes to Group/Abelian group, and
its monoidal Center/Basic file contributes half-braiding identities to Drinfeld
center. Their definitions remain attributed to Mathlib; count only native files
in Tau Ceti. Pure imports and downstream uses receive no native LOC. Do not demote
these mappings merely because the concept's definition is inherited.

For a compound concept, identify the defining object or operation to which each
selected declaration contributes. Ordinary laws under weaker hypotheses may qualify
when they act directly on that object and are valid for the catalogue subclass;
explain the instantiation and any extra admissibility conditions. A formula about
a prerequisite input alone does not qualify merely because that input occurs in
the definition. Record this boundary judgment for independent mathematical review.

Preserve the declared core API boundary. Record why files were added, retained,
removed or excluded. A different file selection needs evidence, not a silent
redefinition of “associated API”. Shared files require a direct contribution to
each concept, rather than subclass inheritance alone. Keep separately significant
endpoints and extra structures outside the generic concept unless the user's scope
expressly includes them. Retain representative declaration names and line anchors.

Arrange mathematical review of proposals in a subagent other than the author.
Review statement equivalence, hidden hypotheses, proof completeness, native versus
dependency ownership, selected/excluded files and the declared API boundary. Return
explicit accept/change/reject decisions. The coordinator validates proposal schema,
path/ID uniqueness, concept revisions, file existence, hashes and LOC mechanically.
An unexplained difference or unresolved mathematical judgment stays unreviewed.

## Apply reviewed changes and measure files

Use save_formalization / the API's full-review replacement operation, not ad hoc
SQL or replay of the old pilot. Re-read concept IDs/revisions before saving: if a
concept changed during the pass, send it back for mathematical review. Preserve
stable review IDs and historical evidence. An updated concept does not inherit a
previous positive/negative judgment automatically. Do not alter concept meanings,
prerequisites, source attribution or other experiments just to fit a code match.

For unchanged meanings and unchanged committed implementation/dependency bytes,
retain the existing judgment after checking its evidence; record the no-change
verification in the run manifest. Do not fabricate a new mathematical review from
file-hash equality if the original evidence was inadequate. Save changed reviews
atomically with nonempty reasons, including removed files and negative/inherited
transitions. New positive/partial reviews need native files; inherited/negative/
unknown reviews need empty file arrays.

Measure selected native files at the same commit that was reviewed:

```sh
python mathdb.py formalization measure mathlib /path/to/mathlib4 --revision COMMIT --reason 'Count reviewed Mathlib snapshot'
python mathdb.py formalization measure tau-ceti /path/to/TauCeti --revision COMMIT --reason 'Count reviewed Tau Ceti snapshot'
```

Count physical lines including comments, blanks and a final unterminated line.
Preserve exact counts, SHA-256 hashes, commit IDs and measurement times. Missing or
moved files need review; never substitute another file or silently count HEAD.
The measurement command operates on all current native mappings for that library:
check that those mappings have been validated for the chosen commit before running
it. For a scoped update with other mappings at different revisions, measure and
save only the reviewed files using the audited file operation; do not refresh
unreviewed outside-scope mappings accidentally.

Recompute LOC with all current active mappings as denominators, including mappings
outside this run and partial implementations. Do not use the worker's subset to
allocate whole files, round stored shares, duplicate dependency code, or replace
unknown counts with zero. Report inherited zero separately from missing estimates.

## Verify, export and report

Run python mathdb.py verify and checks appropriate to changed invariants. Confirm
that unrelated mathematical tables, concept identities/revisions, source roles,
prerequisite flags and vectors were preserved. Regenerate readable exports with
python export_example.py and validate the saved scoped results against the exports.
Check the live API and representative concept pages, including native, inherited,
partial or missing-count cases present in this update. Verify file URLs use the
recorded commits and correct owning repository.

Save a reproducible reviewed batch and a run/review manifest under data/ with the
scope baseline, revisions/dependency pins, worker/reviewer decisions, selected and
excluded files, exact measurements, prior/new results and unresolved frontier.
Keep historical pilot/update manifests intact. Do not claim the entire catalogue
was reviewed if any scoped pairs were skipped, delegated but unfinished, or merely
matched by names. Finish with actual concept/library counts, added/changed/unchanged
judgments, LOC changes, verification, artifact links and unfinished coverage.
