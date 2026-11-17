# Find journal papers and their arXiv versions

Identify the articles published in the requested journals during the requested
years, and find their arXiv versions where available. Return a bibliographic list
with the evidence for each match and an explicit list of unresolved cases.
Do not read papers to extract mathematical concepts or change the mathematics
database during this task.

## Establish the requested scope

You need the journal names or ISSNs, the inclusive year range, the path to this
repository and a new directory for the results. Unless the user says otherwise,
use the year of the journal issue, include corrections/errata as separate records,
and retain articles even when an arXiv version cannot be found. If an existing
discovery run was supplied, read its `scope.json` before doing anything else.

Use `python discovery.py journals` to list journals already supported. Annals,
Inventiones, Acta and JAMS have publisher-specific readers. For another journal,
identify its correct ISSN and an official issue index. Supply explicit issue URLs
if automatic extraction cannot establish the requested contents. Do not guess
volumes from a numerical formula or infer completeness from a search result.

Read `docs/DISCOVERY.md` for the scope-file format and commands. Create the JSON
scope with actual requested values, then initialize and run it:

```sh
python discovery.py init --scope /path/to/scope.json --out /path/to/new-run
python discovery.py run /path/to/new-run
python discovery.py status /path/to/new-run
```

The `init` command fixes the scope and instruction copies. `run` collects cached,
dated API responses and publisher pages. Repeat `run` on the same directory to
resume; use a new directory for changed scope or refreshed data. Do not edit the
frozen `scope.json`, caches or generated matches to make a result look complete.

## Check contents and matches

Inspect `issues.json`, `journals.json` and `unresolved.json`. The program compares
publisher contents with Crossref identifiers, handles pagination, looks up DOI
and arXiv links in OpenAlex, and writes JSON/CSV candidates. Publication online
may precede the issue year; issue contents decide inclusion. A correction is not
automatically the same work or arXiv file as the original paper.

For each unresolved case, check the publisher article page, arXiv metadata and
author publication pages where useful. Prefer explicit identifiers and matching
DOIs. A similar title or matching surname suggests a candidate; it does not prove
identity. Verify full authorship, title changes, version dates and what the article
page says. Multiple preprints may be separate parts rather than interchangeable
versions. Do not choose one arbitrarily or claim that no preprint exists because
OpenAlex has no link.

Record manual findings in `match-review.json`, with the candidate key, proposed
arXiv/OpenAlex identifiers, inspected URLs, the exact identifying evidence and a
reason. This is a review document, not a way to silently modify generated results.
If a new journal layout needs a parser fix, preserve the failing page as a test
fixture, update the parser and tests, and initialize a new run using the saved
responses. Record which run supersedes the old one. Do not weaken matching or
completeness checks to make the parser pass.

## Finish or checkpoint

Run `python discovery.py verify /path/to/new-run`. Report the requested scope,
articles found, issue contents verified, arXiv matches, corrections, duplicates,
and unresolved cases. Link `candidates.csv`, `candidates.json`, `unresolved.json`
and any manual review. A successful download is not proof of complete coverage;
an unfinished issue or unidentified contents entry stays explicit.

The program sends an optional `OPENALEX_API_KEY` from the environment in a request
header and does not save it. If authentication or quota blocks progress, report
the exact command/stage and resume instructions, and ask the user for help with a
key only if needed. Do not create accounts, buy credits or paste keys into scope
files, URLs, logs or reports. No agent should change the requested selection
because a journal or paper is harder to access.

Return discovery results only. Before later mathematical analysis, supply fresh
curators with paper identifiers, versions and the concept-analysis instructions;
do not pass citation ranks, expected reuse or experiment results to them.
