# Curation prompts

Run source and concept analysis, prerequisite investigations, and mathematical
review in subagents. The coordinating agent handles software, structural checks,
and imports of reviewed plans. A subagent can carry out its assigned curation
directly; it need not delegate it again.

Choose one prompt for the task below. Each starts with the task, lists its inputs,
and explains what to inspect and return. Supply actual paper/concept identifiers,
repository and database paths, and an output directory; no earlier conversation
is required.

| Task | Prompt |
| --- | --- |
| Decide whether a phrase denotes a concept; reuse/create/revise its record | [Concept identity](concept.md) |
| Modify, split or merge concepts and review every affected relationship | [Reorganize concepts](reorganize-concepts.md) |
| Identify a paper's required, introduced and explained concepts | [Identify concepts in a paper](ingest-source.md) |
| Complete prerequisites of one or several concepts | [Expand prerequisites](expand-prerequisites.md) |
| Reconcile a finished task's result with the live catalogue before import | [Merge a task](merge.md) |
| Review or update formalization coverage, files and estimated LOC | [Review formalization](formalization.md) |
| Find journal contents and matching arXiv versions for specified years | [Discover journal papers](discover-journals.md) |
| Find highly cited papers in specified collections | [Discover highly cited papers](discover-citations.md) |

[Curation tasks](../docs/CURATION_TASKS.md) describes how a task directory is
prepared, handed to a worker, merged and imported, and the format of the
`result.json` a worker writes.

Operational detail: [Curation workflows](../docs/CURATION.md).
Mathematical policy: [CONCEPTS.md](../CONCEPTS.md).
Commands and API: [API.md](../API.md).

Each prompt requires explicit judgments and evidence. A finished-looking graph,
a source theorem number or a successful database insertion cannot replace those
judgments. Keep uncertainty and incomplete coverage visible.

The expansion target is every statement prerequisite of every required root, not a
representative concept. Theorem concepts needed for the proof are also recorded immediately, but
proof-only edges are not recursively followed in this phase. See the statement/proof
policy in each prompt and the curation workflow.

Unless the user narrows the task, “update formalization coverage” means the whole
active catalogue in Mathlib and Tau Ceti, including unreviewed concepts. Use the
update workflow, including an
explicit scope baseline, pinned upstream/dependency commits, delegated mathematical
review, audited full-file-set updates, exact LOC counts, exports and website checks.
The generic Group power-law and Drinfeld half-braiding APIs in Tau Ceti remain
valid native contributions even though their definitions are imported from Mathlib.
