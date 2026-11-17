# The Shape of Math

A small database of mathematical concepts and sources. The editorial rules are in [CONCEPTS.md](CONCEPTS.md); executable [curation workflows](docs/CURATION.md) and [task prompts](prompts/README.md) cover identity, reorganization, recursive expansion and source ingestion. Each concept has a **name
and a short informal definition or theorem statement**. There is no separate scope
attribute or second explanatory column. Necessary qualifications belong in the
name or in the paragraph itself.

For example:

- **Convex hull.** The smallest convex set containing a given set of points.
- **Clique.** A set of vertices in a graph, every two of which are adjacent.
- **Independent set in a graph.** A set of vertices containing no edge.
- **Complete rational form of a tensor category.** A rational form whose scalar
  extension is already idempotent complete, so recovering the original category
  requires no new summands.

Definitions should be short when the object is simple. A named theorem is one
concept, independently of its proofs. A broad theory name or an ambiguous theorem
name must be replaced by a specific mathematical object or result. Proof maneuvers
and calculation steps go in source notes and dependency explanations.

## Explore and edit in a browser

To collect journal contents and highly cited papers before concept analysis, use
[the discovery commands](docs/DISCOVERY.md). They take a scope JSON containing
the requested journals, years, categories and cutoff, and save resumable candidate
lists. [Journal discovery](prompts/discover-journals.md) and
[citation discovery](prompts/discover-citations.md) have separate agent prompts;
[the prompt index](prompts/README.md) lists one prompt per task.

Prepared curation tasks use [general reviewed-plan imports](docs/CURATION_TASKS.md)
with `curation_plans.py`, and [measured task usage](docs/TASK_USAGE.md) with
`task_usage.py`. These work independently of the fixed2015 sample coordinators.

```sh
python mathdb_server.py
```

Open **http://127.0.0.1:8000**. The interface has no frontend build step and uses
only local assets. `--port PORT` and `--db PATH` select another port or database.
It opens the existing collection and applies any pending schema migration.

For development, use `make serve`. It replaces this checkout's existing server
on the selected port and automatically restarts when `mathdb.py`,
`mathdb_server.py`, or `schema.sql` changes. JavaScript and CSS are read on each
request; refresh the browser to see edits. Stop with Ctrl+C or `make stop` from
another terminal; `make status` checks for running processes. These management
commands use Linux `/proc` to identify this checkout's server, including servers
started before this tooling was added, without matching other checkouts.
Use `make serve PORT=8001` (and the same `PORT` for stop/status) for another port.
If the port belongs to another application, it is left running and startup fails.
The equivalent command without Make is
`python mathdb_server.py restart --reload`; `stop` and `status` are also supported.

Preview screenshots: [concept view](docs/concept-view.png),
[source view](docs/source-view.png), and [citations](docs/citations-view.png).

The selected definition or theorem statement appears above the neighborhood.
The Neighborhood view puts immediate prerequisites below the selected concept and
immediate dependents above it. Switch to **Entire cone** for the entire
recorded downward cone, with shared ancestors shown once, fit/zoom/pan controls,
and a standalone SVG download. Click a neighbor to recenter the map. Sources
introducing the concept, sources needing it, and related concepts sit beside it.
The **Statement** selector follows concepts needed to understand definitions and
theorem statements. **Proof** also follows concepts needed for the proof. Different
proofs may need different background; the notes identify the proof examined.
Its direct prerequisites remain visible beside a statement cone, without expanding
their own prerequisites. The two completeness judgments are independent.
The source view lists the concepts it needs, the concepts it introduces, and its
captured citations, including pedagogical judgments and needed material. Search,
URLs, browser back/forward, and mobile navigation work across both views.

Editing forms write directly to the database through a versioned JSON API:
concept/source records, prerequisite and related links, concept/source roles,
source identifiers, citations, and completeness judgments. Each edit needs a
reason and appears in the curation history. Stale edits are rejected rather than
overwriting newer work. The server binds to loopback for local use; shared-service
authentication and editor identities remain future work.

The [API reference](API.md) documents read/write endpoints, validation, concurrency
and examples. It is also served at `/api/docs`. Advanced split/merge operations
and ingestion batches reuse the existing audited database operations.

## Source attribution: original contributions and explanations

The G₂ paper introduces neither Kuperberg’s spiders/webs nor the braid-generation
conclusion, which its abstract credits to Lehrer–Zhang. It gives another proof.
Its reviewed introduction list is empty; the explanations remain available and
its required web-basis theorem brings in non-elliptic webs, webs and the spider
transitively. Those concepts are not duplicated as direct prerequisite cards.
Earlier Kuperberg work and Lehrer–Zhang now have explicit origin claims with checked
source passages. Kuperberg 1994 supplies the earlier graphical calculus; the 1996
paper supplies the categorical spider/basis comparison.

The same correction applies across the collection: textbooks and later proofs no
longer acquire priority by teaching something. `introduction_evidence` is required
by the database, API and CLI. [The attribution review](data/source-attribution-review.json)
records positive claims and outstanding priority work. Except for explicitly reviewed
sources, an empty introduction list remains unreviewed rather than certified empty.
The non-cyclotomic paper retains checked original main results; priority of its
other definitions and auxiliary results remains under review.

`curate_attribution.py` applies this audit and `build_example.py` includes the same
claims in fresh ingestion data. Located expositions use `explains`. Source requirements
are explicit and proof-specific: an original source is never assigned ingredients
from a later proof merely through their shared theorem record.

## Current data

The authoritative store is [data/math.sqlite](data/math.sqlite). Current counts
and per-paper expansion frontiers are recorded in
[the sample progress file](experiments/curation-2015/progress.json); readable
exports are regenerated from the live store. The browser's
[2015 sample page](http://localhost:8000/experiments/2015) links each sampled paper
to its concepts and analysis notes.

The [collection-wide review](data/full-review.json) accounts individually for the
267 active concepts, all 465 original prerequisite edges, all 279 original active
source occurrences, 31 sources, 12 source relations, two related links and eight
captured citations. It made 47 identity-preserving name/paragraph revisions,
corrected prerequisite meanings and source roles/locations, and reduced the DAG.
That pass recorded 208 certified immediate prerequisite lists and **59 explicitly
unfinished lists**, with the missing background named in the review. This is a
review of the existing collection, not a completed recursive expansion of every
concept or a full ingestion of every catalogued reference. Niven and Morrison's
G₂ paper have independently reviewed empty introduction lists. Other unresolved
origin and source-coverage questions remain recorded and uncertified.

Reproduce the reviewed content with `python build_full_review.py` and
`python build_example.py`; apply the explicit judgments with
`python curate_full_review.py`. The pre-review database and exact link inventory
are preserved in [archive/before-full-data-review](archive/before-full-data-review/).

The [cone overlap explorer](http://localhost:8000/experiments/2015/overlap) graphs
the marginal and cumulative number of concepts covered as papers are added, within
each sampled category and across all thirty. Means over orderings are exact;
pointwise ranges show order variation. It distinguishes reviewed reading cones
from provisional cones of all linked concepts. Export figures, CSVs, frozen sets,
and a [methods and scaling assessment](experiments/curation-2015/overlap/report.md)
are in `experiments/curation-2015/overlap/`. Reproduce statistics with its
`analyse.py`; render PNG/SVG/PDF figures with its optional `plot.py`.

The [additional source assignments](http://localhost:8000/experiments/2015/more)
track another ten papers per category. The fixed selection and pre-ingestion
snapshot are in `experiments/curation-2015-round2/`. Curators receive fresh contexts
containing the neutral assignments under `curation/source-tasks/`, the catalogue
and the curation policy. Their prompts omit the overlap/modeling objectives and
forecasts. Reviewed plans are imported mechanically with that directory's
`coordinate.py`; reading, introduction, bibliography and cone reviews remain
independent. Original analysis snapshots and forecasts stay frozen.

The [2015 experiment report](experiments/curation-2015/report.txt) records a
reproducible sample of ten papers each from math.FA, math.NT and math.PR
([titles and identifiers](experiments/curation-2015/sample.tsv)). Two delegated
initial source analyses cover *On mapping theorems for numerical range* and *Revisiting
Kneser's Theorem for Field Extensions*, pinned to their 2015 arXiv v1 artifacts.
Separate recursive investigations completely review the numerical-range cone
(35 concepts, 51 links) and the finite-dimensional subspace-product cone
(22 concepts, 27 links). Their intersection has 12 concepts. Both have only Set
and Natural number as primitive leaves. The experiment adds 70 concepts, six
sources and 31 citations; it also repairs five older immediate lists. The combined
collection at that stage had 235 certified lists and 102 not certified complete. The two new
papers' reading and introduction capture remain explicitly incomplete, independently
of the complete selected cones and captured bibliographies.

The subsequent pass processes the remaining 28 papers with three agents. Source
analysis, recursive statement coverage, and reviews of concepts needed for theorem proofs
are tracked separately. Its expansion target is **every required concept of every
paper**, including inputs omitted from the initial drafts. Proof-only parents
receive concept records and edges, but their own prerequisites are not followed
in this phase. Shared mathematical identities are compared before reuse; routing
corrections and completeness judgments retain audit history. Since schema version 8,
records each edge's statement/proof purpose separately from its pedagogical or
logical basis, and reduction preserves both reachability relations.

Each staged paper has `analysis.json`, `analysis-review.json` and `report.txt`
under `experiments/curation-2015/papers/ARXIV_ID/`. After reviewing identities and
mathematical claims, use `python experiments/curation-2015/apply_paper.py ARXIV_ID
--dry-run`, then the same command without `--dry-run`. A `--stage cone` batch
applies independently reviewed recursive coverage. The ingester preflights an
isolated copy, preserves stage hashes and refuses changed already-applied stages.

After building, ingesting and reviewing the base seed, reproduce the additional
curation with `python experiments/curation-2015/ingest.py --dry-run` and then
`python experiments/curation-2015/ingest.py`; use `--db PATH` for an isolated copy.
`python experiments/curation-2015/sample.py` reproduces the sample from the local
inventory and recorded seed. Its date filter uses the arXiv identifier because
the supplied `created` field does not consistently give the first-submission year.
Internal metadata records whether an entry is a definition, theorem, construction,
or conjecture; this is not an additional mathematical description.

The [complete catalogue](data/catalogue.txt) contains definitions and provenance.
There is also a [JSON projection](data/snapshot.json) and a
[spreadsheet-friendly export](data/concepts.tsv).

The normalized third twisted moment and its choice-independence lemma have been
demoted to source proof notes. Their historical records are retained as inactive;
they do not appear in the active reading lists. Ambiguous names have been qualified,
including intertwiners, the Karoubi envelope, and Euler measure with assigned angles.

The first five papers:

- [Zagier's two-square proof](data/zagier-1990.txt)
- [Niven's irrationality proof](data/niven-1947.txt)
- [Erdős–Szekeres](data/erdos-szekeres-1935.txt)
- [Su's Rental Harmony](data/su-1999.txt)
- [Etemadi's strong-law proof](data/etemadi-1981.txt)

The new draft extractions:

- [The braid group surjects onto G₂ tensor space](data/morrison-g2-2011.txt):
  23 direct concepts, including the generic quantum group, its seven-dimensional
  module, the spider and web basis, the braid-generation theorem, and objects
  appearing in the root-of-unity questions.
- [Non-cyclotomic fusion categories](data/morrison-snyder-2012.txt):
  65 directly linked concepts, including split categories, rational versus complete rational
  forms, lopsided planar algebras, the principal
  field-of-definition results, centers, and Galois conjugation.

The lists state where each concept occurs and whether the paper relies on, introduces, explains or discusses it. In particular, the root-of-unity questions in the G₂
paper are not recorded as established equivalence theorems. Theorem 1.2 of the
non-cyclotomic paper is one record containing all four clauses. Specific numbered
idempotents, coefficient lists, and small-graph calculations remain source data.

The new extraction is in [data/author-papers.json](data/author-papers.json), authored
by [build_author_papers.py](build_author_papers.py). It includes basic definitions
and some contextual theorems; it does not claim a recursively complete account of
all categorical or operator-algebra prerequisites. The source's `coverage` field
records which parts of a paper have been inspected. This is ingestion metadata,
not a property of a mathematical concept.

## One layer from the non-cyclotomic paper

The [complete expansion report](data/noncyclotomic-one-layer.txt) freezes the 62
original active direct concepts plus the five background concepts already in the previous
catalogue. Reviewing these 67 seed entries adds **56 concepts and 101 prerequisite
edges**, bringing that pass's reading graph to 123 concepts. Later recursive reviews deepen its shared background further.

Every added edge targets a member of the frozen seed. The 56 new concepts have no
incoming prerequisite edges yet and are explicitly left for the next pass. Some
new links reuse existing concepts, such as the simple-object input to fusion
categories. The pass reviews every seed entry, including those with no new parents. Three
new prerequisites have their selected explanation in the original paper itself;
the current source list therefore has 65 directly linked entries, while the
frozen expansion seed remains unchanged.

The [review data](data/one-layer-review.json) records the frozen list and each
parent decision. The [append-only batch](data/one-layer-batch.json) contains the
new records, links and nine selected learning resources. These resources remain
catalogued; only the located excerpts were inspected. This does not claim full
ingestion of nine textbooks or notes. A dedicated elementary vector-space
exposition remains to be selected; that assumption is explicit in its learning link.

Useful starting points include EGNO Chapters 1–2 and §§4.1/4.16, the Stacks Project
Categories chapter and Karoubian section, Morrison's Jones–Wenzl note §§1–2, Jones's
von Neumann algebra notes Chapters 6/10, and Milne's field-theory notes. Loop and
field conventions are recorded, rather than silently identified across sources.
The one-layer batch creates **no source-dependency edges** from the research paper
to those learning references.

## Recursive prerequisite experiments

Two experiments recursively review every prerequisite until an explicit elementary
baseline: sets, natural numbers, elementary logic and finite arithmetic. These
are pedagogical dependency graphs; formal ZFC encodings and size foundations
for large categories are left outside this route.

| Root concept | Concepts including root | Reduced links | Levels below root |
| --- | ---: | ---: | ---: |
| Drinfeld center of a monoidal category | 16 | 20 | 9 |
| Chebyshev’s inequality | 46 | 71 | 17 |

The experiments add **38 concepts**, reuse **20 existing concepts**, and explicitly
certify the immediate prerequisites of all **58** distinct entries. Each cone is
fully reviewed under the stated baseline. The leaves are Set for the center, and
Set/Natural number for Chebyshev. The rest of the database retains its independent
review status. Source reading cones are now derived from explicit source-specific inputs; explanations and motivation remain separately accessible.

The center review adds natural isomorphisms, product categories and bifunctors.
The probability review supplies measurable maps, the real Borel σ-algebra, simple
functions, and the Markov route to Chebyshev. It expands the real-number definition
through ordered fields and suprema, rather than silently treating that node as
already understood. General topology is unnecessary for the chosen interval-based
Borel definition. Learning references include EGNO, Stacks, Milne, Durrett and Lebl;
precise locations, conventions and proof choices are in the review records.

**Transitive reduction removes 19 redundant edges** across these cones, retaining
reachability and preserving the original rationales/evidence plus alternative paths
in curation history. For example, the direct Functor → Drinfeld center edge is
replaced by the path through Bifunctor, Monoidal category and Braided monoidal
category. Separately, two integer-indexing edges are corrected: natural numbers
suffice for sequences and nonnegative series.

Read the [complete review](data/recursive-experiments.txt),
[cone JSON](data/recursive-cones.json), or the explicit
[curation plan](data/recursive-expansion.json). Preview the
[center cone](docs/drinfeld-center-cone.png) and
[Chebyshev cone](docs/chebyshev-inequality-cone.png). Vector exports: [center SVG](docs/drinfeld-center-cone.svg) and [Chebyshev SVG](docs/chebyshev-inequality-cone.svg).

In the browser, open either concept and choose **Entire cone**. **Fit all** shows
the whole graph; **100%** makes labels readable for panning. On phones, the cone
opens as an **Outline**, with each concept shown once and its direct prerequisites
available beneath it. Levels can be collapsed or expanded; **Jump to level** and
**Back to start** stay visible as you scroll. Switch to **Diagram** to pan through
the graph. Clicking a node
recenters its own cone. Amber nodes elsewhere in the collection indicate missing
prerequisite reviews. The reduction button previews removable links and records
an explicit reason when applying them.

```sh
python mathdb.py cone drinfeld-center
python mathdb.py reduce --concept drinfeld-center --dry-run
python mathdb.py reduce --concept drinfeld-center --reason 'Remove transitive shortcuts'
python curate_recursive.py --dry-run
```

`build_recursive_experiments.py` regenerates the frozen plan from its editorial
records and downloaded reference snapshots. `curate_recursive.py` applies that plan
once and writes the review reports; a plan hash prevents duplicate application.
`build_example.py` includes the same definitions and reduced graph in the ingestion
seed. On a fresh database, run `curate_recursive.py --db PATH` after seed ingestion
to record the explicit completeness judgments; ordinary ingestion never certifies
review flags automatically. The checked-in database includes the reviews and all
337 local concept embeddings, including the subsequent 2015 experiments.

## Sources and dependencies

A source has a UUID and any number of external identifiers. DOI normalization,
arXiv base identifiers, ISBN equivalence/checksums, URLs and zbMATH identifiers are
supported. Exact PDF versions have access dates and SHA-256 hashes. The author
papers use these snapshots:

- [G₂ paper](https://arxiv.org/abs/0907.0256), published DOI
  [10.2140/pjm.2011.249.189](https://doi.org/10.2140/pjm.2011.249.189).
- [Non-cyclotomic paper](https://arxiv.org/abs/1002.0168), published DOI
  [10.1090/S0002-9947-2012-05498-5](https://doi.org/10.1090/S0002-9947-2012-05498-5).

Prerequisite edges point from prerequisite to dependent and carry a rationale.
They represent definitions and chosen proof/learning routes. Alternative proofs
can use different prerequisites; that does not create additional theorem concepts.
The current graph may contain inputs to more than one proof, with the alternatives
explained in source notes. SQLite rejects cycles on insertion and update.

Source citations and historical credit remain separate from strict source
dependencies. The new drafts identify actual imported inputs, such as Kuperberg's
web basis and equivalence, the Haagerup constructions, and Izumi's modular data.
Their unique availability has not been audited, so they are not silently promoted
to strict dependencies. A strict edge needs a specific imported fact, a location,
and evidence that it is not generally available in textbooks or notes.

## Coverage reviews, citations and related concepts

Four independent flags record reviewed completeness:
`concept.prerequisites_complete`, `source.requirements_complete`,
`source.introductions_complete`, and `source.citations_complete`. Each defaults
to false (not certified). Concept reviews concern immediate links, without requiring
completion further down the graph. Citation completeness means all reference text
has been captured; identifiers and assessments may remain unresolved.
The [editorial rules](CONCEPTS.md#immediate-coverage-judgments) describe when changes
reset a judgment. `boundary` and draft/reviewed status remain separate.

Source roles are `relies_on`, `introduces`, `explains`, and `discusses`.
`introduces` is an evidence-backed claim of an original mathematical contribution;
`explains` covers expositions and later proofs. Old definition/proof labels map to
`explains`. A theorem number, a definition printed in a paper, or a new database
record never establishes novelty. Source prerequisite cards show the maximal
explicitly required concepts, with inherited background available separately.
Related links connect concepts without adding a prerequisite, for example principal
and dual even parts. Related links have reasons and appear from either endpoint.

Each optional citation record holds the original reference text and label, multiple
identifiers, an optional linked source, a nullable `pedagogically_necessary` judgment,
and optional `needed_material` text such as “Theorem 2.3 and its proof”. Explicit
identifiers are extracted locally, normalized, and matched against catalogued
sources. Unresolved entries can be assessed or identified later. Adding citations
does not imply strict source dependence.

[data/citations-example.json](data/citations-example.json) captures all eight
references from the G₂ paper's bibliography on p. 198. The current database
certifies this citation list as complete; other source completeness judgments
remain unreviewed. The local identifier extractor also works on future ingestion
batches, which can include a `citations` array with the same format.

```sh
# Review judgments require inspecting the relevant list first.
python mathdb.py review concept fusion-category --prerequisites complete --reason 'Reviewed immediate prerequisites'
python mathdb.py review source morrison-snyder-2012 --requirements complete --reason 'Reviewed reading requirements'
python mathdb.py review source morrison-snyder-2012 --introductions complete --reason 'Reviewed introduced concepts and results'
python mathdb.py review source morrison-g2-2011 --citations complete --reason 'Checked every bibliography entry'
python mathdb.py link SOURCE CONCEPT introduces --locator 'Theorem 1' --introduction-evidence 'Checked original contribution and predecessor attribution' --reason 'Record the original result'
python mathdb.py citation add SOURCE 'Author, Title, arXiv:1002.0168.' --label '[1]' --reason 'Transcribe bibliography'
python mathdb.py citation revise 1 '{"pedagogically_necessary": true, "needed_material": "Theorem 2.3"}' --reason 'Review imported material'
python mathdb.py citation resolve SOURCE --reason 'Match identifiers to newly catalogued sources'
python mathdb.py citation delete 1 --reason 'Remove an erroneous duplicate'
python mathdb.py relate CONCEPT_A CONCEPT_B --reason 'Explanation of their connection'
```

`show source` and JSON/text exports include citation records and flags. Changes
are audited; split/merge plans require `related_routes` for incident related links.
`init` upgrades v3–v6 databases in place to v7, retaining concept UUIDs, vectors
and history. Merged source occurrences retain all notes and the earliest row ID.
Ambiguous origin claims become explanations and source introduction reviews reset; original-contribution claims are restored only by an explicit evidence audit. It is
safe to rerun initialization. Fresh ingestion defaults all review flags to false;
the G₂ citation review is a separate curation judgment in the current database.

## Use and rebuild

The core needs Python 3.12+ and its standard library:

```sh
python mathdb.py verify
python mathdb.py show concept complete-rational-form
python mathdb.py show source morrison-g2-2011
python mathdb.py prerequisites morrison-snyder-2012
```

Start with an empty database:

```sh
python mathdb.py --db /tmp/new-math.sqlite init
python mathdb.py --db /tmp/new-math.sqlite ingest data/seed.json
```

The builder for the original five papers incorporates the author-paper batch when
it exists. Rebuild their ingestion input with:

```sh
python build_author_papers.py
python build_one_layer.py
python build_example.py
```

Apply that input to a fresh database. Re-ingesting an existing source slug is an
error, not an overwrite. For ongoing curation, `revise` preserves the UUID and
records before/after data. Splits and merges require explicit routing for all
incident edges and source occurrences, and commit or roll back atomically.
For the existing earlier database, `refine_concepts.py` applies the editorial
corrections with retained history, and the one-layer batch can then be ingested.
The checked-in database already includes both operations.
Earlier experiments are preserved in [archive](archive); their schemas are not
silently reused for the current model.

## Local search and checks

```sh
uv sync --extra embeddings
HF_HUB_OFFLINE=1 .venv/bin/mathdb search 'complete rational form without new summands'
python -m unittest discover -s tests -v
python export_example.py
```

BGE-small-en-v1.5 runs locally on CPU through FastEmbed. First use downloads the
weights; the current cache supports offline inference. Vectors encode only the
name and definition/statement. Exact cosine search scans the vectors in SQLite.
Title or definition edits invalidate vectors, and an encoder fingerprint prevents
mixing incompatible vector spaces. Search cannot merge concepts or create edges.
The [model card](https://huggingface.co/BAAI/bge-small-en-v1.5) describes the model;
[data/retrieval.json](data/retrieval.json) records manually chosen smoke probes.

The tests cover database invariants, provenance-preserving curation, rejection
of the removed concept attribute, and the distinctions between generic G₂ versus
root-of-unity questions and rational versus complete rational forms. They do not
verify mathematical proofs or settle the editorial boundaries of the concepts.

With the local server running, `node tests/browser_layout.cjs` runs optional
browser checks using Playwright and its Chromium browser (installed separately).
It checks connector routing (including long cone edges), visible definitions,
formula wrapping and script typography, responsive layouts from 320 to 1920
pixels, mobile cone outlines, and diagram zoom, pan, resize and SVG export.
It only reads the collection.
`node tests/browser_interactions.cjs` additionally checks scrolling dialog controls,
mobile drawer dismissal and focus, outline jumps and level controls, reading
widths, and grouped exponent notation. It also runs without database writes.
Set `MATHDB_BASE_URL` to test a server on another port, or `NODE_PATH` to use an
existing Playwright installation.

## Formalization coverage and rough LOC

Concepts can be reviewed independently in Mathlib, Tau Ceti, and additional libraries.
Each review records a status (`formalized`, `partial`, `inherited`, `not_formalized`, `unknown`),
evidence, and the files that define/prove the concept and develop its associated
API. Files that merely use/import it do not qualify. No review means unknown.
The concept page displays and edits these reviews, file mappings and counts.

The rough estimate sums each mapped file's physical LOC divided by the number of
currently mapped active concepts for that file. Multiple files can contribute to
one concept. Partial implementations share files too and are labelled partial.
Missing file counts yield an incomplete estimate, with a separate known subtotal.
Concept revisions require re-review; split/merge plans explicitly route formalization
reviews. Each measured file records its revision and measurement date.

Upgrade an existing database with `python mathdb.py init`. Query coverage with:

```sh
python mathdb.py formalization report --library mathlib --status formalized
python mathdb.py formalization report --library tau-ceti
python mathdb.py formalization measure mathlib /path/to/mathlib4 --reason 'Count mapped committed files at HEAD'
```

See [API.md](API.md#formalization-and-estimated-loc-schema-10) for writes, SQL queries
and CLI examples; [the curation workflow](docs/CURATION.md#5-review-formalization-and-implementing-files)
and [formalization prompt](prompts/formalization.md) explain the evidence and file-selection
policy. Readable exports include `data/formalizations.tsv` and `data/formalizations.json`.

The first [six-concept pilot](data/formalization-pilot-review.txt) distinguishes
checked dependency availability from native contributions. `inherited` displays as
“Available through dependency” with zero native LOC; native API extensions to an
imported definition receive their own file shares. Use `formalization measure
--revision COMMIT` to count the reviewed snapshot. The prompt now requires a
bounded core API selection and declaration/exclusion evidence.
