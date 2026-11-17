# Find highly cited papers in a requested cohort

Identify the most cited papers in the requested collection using OpenAlex citation
counts. Record the collection, ranking rule and retrieval dates so the result can
be reproduced. Find arXiv links and preserve uncertain identities. Do not extract
mathematical concepts or edit the mathematics database in this task.

## Define the collection before ranking it

You need the repository path, a new results directory, the collection to rank,
the desired percentage or count policy, and whether to rank separately by field.
If these were already supplied by the user, use them without asking again.

For arXiv categories, specify the categories, inclusive submission years and the
local metadata inventory. Use all matching IDs, including crosslists; the program
deduplicates repeated IDs. The arXiv identifier encodes submission year/month.
An OAI record-creation date or later journal publication year is not its submission
date. Category labels come from the declared inventory, not a guessed OpenAlex
field correspondence. Do not silently replace FA with all analysis.

For a collection defined in OpenAlex, supply an explicit API filter: for example,
a publication-year range and particular journal ISSNs or topic IDs. This is a
different collection from arXiv submissions in those years. Record the exact filter
and explain what it includes. If the user requests several independently ranked
OpenAlex-filtered collections, create one run for each filter.

Use the requested percentage. If the user says only “most cited”, propose or ask
for a cutoff rather than silently using all returned search hits. The provided
example uses10%. By default, rank separately within requested arXiv categories,
use ceil(percentage × full cohort size), and include all ties at the cutoff.
The program also supports a pooled ranking and an exact-size cutoff with a stated
OpenAlex-ID tie break. Do not change that policy after seeing the results.

## Run the collection program

Read `docs/DISCOVERY.md` and create a scope JSON with the actual requested values.
Then run:

```sh
python discovery.py init --scope /path/to/scope.json --out /path/to/new-run
python discovery.py run /path/to/new-run
python discovery.py status /path/to/new-run
```

The commands save an immutable scope, response timestamps, a resumable cache,
the full cohort, rankings, candidates and unresolved metadata. Resume by repeating
`run` on the same directory. To change scope, code or the citation snapshot, create
a new run and preserve the previous one. Cached results are not silently refreshed.

## Check what the ranks mean

Inspect `cohort.json`, `rankings.json`, `candidates.csv` and `unresolved.json`.
Citation counts are lifetime counts at response retrieval, not counts in the year
the paper appeared. No arXiv match or unknown citation count must be replaced by
zero. Multiple OpenAlex works for the same arXiv ID require review, not summing
their citations or selecting the larger count. OpenAlex may also link several
arXiv IDs to one work; retain those aliases and deduplicate the ranked work.

The denominator is the full declared cohort before work-identity deduplication
and configured retraction exclusion. That reproduces the current survey rule;
report both the cohort size and distinct eligible works. Missing metadata makes
the ranking provisional because an unresolved paper could cross the cutoff.
An exclusion is not the same as an unknown count. Show retracted records separately.

Check unresolved identifiers against arXiv, publisher metadata or authoritative
author pages. Record evidence-backed proposals in `match-review.json`; do not
rewrite the generated cache or manufacture a complete ranking. A fuzzy title
search can help locate candidates but cannot establish the mathematical identity
or the equivalence of two papers.

## Finish or checkpoint

Run `python discovery.py verify /path/to/new-run`. Report each collection's
denominator, matched works, unknown/ambiguous counts, excluded records, cutoff,
number selected including ties, data dates and cross-category duplicates.
Distinguish collection completion from complete citation coverage. Do not claim
an exact population decile when unresolved records remain.

If authentication, quota or a request limit blocks progress, retain the run and
report how to resume. `OPENALEX_API_KEY` is read from the environment and sent only
as a header. Ask for a key when required; do not create an account or purchase
credits. Never put credentials in scope files, URLs, logs or reports.

Deliver bibliographic candidates and metadata-review notes only. Citation-selected
papers are not a random sample of the literature. Keep rankings, model predictions
and desired reuse rates out of later mathematical curators' task instructions.
