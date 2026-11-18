# Cohort analysis

A *cohort* is a named, reproducible selection of catalogued sources: a random
arXiv sample, the papers of some journals, the sources of one field, or a
combination. `cohorts.py` resolves a cohort against the database and measures how
much the sources' prerequisite cones overlap. It only reads the database.

```sh
python cohorts.py cohorts/arxiv-2015-sample.json
python cohorts.py cohorts/arxiv-2015-sample.json --roles relies_on,introduces --json /tmp/overlap.json
python cohorts.py cohorts/top-four-journals-2006-2025.json --list
```

`--db PATH` reads a different database. `--list` prints the selected sources and
reports explicit identifiers that are not in the database.

## Cohort files

Cohort definitions live in [cohorts/](../cohorts/). A file has a `name`, a
`description`, optional free-form `provenance` (seeds, harvest hashes, selection
rules), and either a `select` selector, named `groups` of selectors, or both. With
only `groups`, the cohort is their union; with both, each group is restricted to
`select`. Groups are analysed separately as well as together.

A selector is a JSON object. Each key picks a set of sources, and the selector is
the intersection of those sets:

| Key | Picks |
| --- | --- |
| `sources` | source slugs |
| `identifiers` | `"scheme:value"` strings, e.g. `"doi:10.4007/annals.2008.167.481"` |
| `arxiv`, `doi` | identifiers of that scheme |
| `doi_prefixes` | sources with a DOI starting with one of the prefixes (case-insensitive) |
| `fields` | sources whose `field` is one of the given strings |
| `years` | `[first, last]`, inclusive, on the source's `year` |
| `any` | the union of a list of selectors |

Two further keys modify the result: `exclude` (a selector whose sources are
removed) and `sample` (`{"count": N, "seed": "..."}`, a reproducible random subset
of the selected sources, drawn from their sorted slugs).

The database does not store arXiv categories. A cohort defined by arXiv category
records the chosen identifiers explicitly, with the selection rule and seed in
`provenance`, as [the 2015 sample](../cohorts/arxiv-2015-sample.json) does.
Explicit identifiers that are not catalogued are reported, not silently dropped.

## What is measured

For each source, the roots are its active concept links with the requested roles
(default `relies_on`, the reading prerequisites). Its cone is the roots and all
their ancestors along `statement` and `both` edges; proof-only edges are not
followed. Each concept counts once per cone.

The result gives, for the cohort and each group:

- each source's root count, cone size, number of cone concepts whose statement
  prerequisites are not certified complete, and its `requirements_complete` flag;
- the union of the cones and its uncertified concepts;
- how many concepts are shared by exactly k sources, and the most shared ones;
- pairwise Jaccard similarity of the cones (mean, median, closest pairs) and
  between group unions;
- the expected union size after n sources, averaged exactly over all orderings:
  with M sources and f_c cones containing concept c,
  E[U_n] = Σ_c (1 − C(M − f_c, n) / C(M, n)).

Counts describe what is recorded. A source without roots, or with
`requirements_complete` false, has not been fully curated, and uncertified concepts
may have further prerequisites. The summary lists both so incomplete coverage
stays visible.
