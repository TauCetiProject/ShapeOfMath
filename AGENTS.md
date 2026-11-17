# Mathematical curation in this repository

All actual processing of mathematical sources and concepts must happen in
subagents: reading, concept selection and definitions, prerequisite investigation,
source attribution, and mathematical review. The coordinating agent handles
software, coordination, structural validation, and mechanical database imports.

Before curating concepts or sources, read [CONCEPTS.md](CONCEPTS.md) and
[docs/CURATION.md](docs/CURATION.md). Select the matching template in
[prompts/README.md](prompts/README.md). [API.md](API.md) documents executable edits.

- A concept has a precise mathematical name and at most one short paragraph. No
  scope column, umbrella theories, or paper-local formulas disguised as vocabulary.
- Reuse identities across sources; compare meanings before relying on name/vector
  similarity. Review every incoming/outgoing edge, related link, source occurrence
  and alias when adjusting an identity. Splits/merges require explicit routing.
- `introduces` means an original contribution to the literature. Require checked
  `introduction_evidence`. An exposition or later proof is `explains`, not an origin.
  Do not automatically promote `defines`/`proves` or infer novelty from theorem numbers.
- Source prerequisites are source-specific judgments. Use explicit `relies_on` roots
  and their inherited background. A later proof’s inputs do not become prerequisites
  of the original source through a shared theorem record.
- Morrison’s G₂ paper recalls Kuperberg and gives another proof of Lehrer–Zhang’s
  theorem. Keep this attribution example correct in data, builders, API and UI.
- Empty unreviewed lists are unknown. Certify completeness only after a real review;
  recursive review uses a declared baseline and leaves unfinished frontiers false.
- Preserve deleted shortcut evidence and retained witness paths during reduction.
  Keep history, UUIDs, vectors, flags and reproducible ingestion data consistent.
- Classify theorem inputs with `purpose`: `statement`, `proof`, or `both`.
  `basis` (logical/pedagogical) is independent. Never guess an unclassified role.
- Current expansion follows **every statement prerequisite recursively**, including
  statements of imported theorems. For each encountered theorem, inspect a selected
  proof and record all direct prerequisites for the proof, but **do not follow proof-only edges
  yet**. Keep that proof frontier recorded, with its own completeness judgment.
- Use `statement_prerequisites_complete` and `proof_prerequisites_complete`
  independently. A complete statement cone does not certify expanded proofs.
- Reduction must preserve statement reachability and proof reachability separately;
  a proof-only path cannot replace a statement edge.

- Review concept formalizations independently per library. Map files defining/proving
  the concept and its associated API, never mere imports/uses. Unknown coverage and
  missing file LOC remain unknown. Distinguish checked dependency-only availability
  (`inherited`, zero native LOC) from native definition/proof/core API contributions.
  Declare the core API boundary and measure the reviewed commit with `--revision`.
  Splits/merges require `formalization_routes`.

Use the audited API or core operations. Run the checks appropriate to changed
invariants and update the readable exports. Do not modify unrelated experiments.
