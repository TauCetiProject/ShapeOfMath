# Discover papers programmatically

Use `discovery.py` to collect journal contents and citation-ranked paper lists.
It writes bibliographic candidates and evidence; it does not ingest mathematical
concepts or modify the mathematics database.

## Choose a scope and run it

Create a JSON file describing the requested journals/years or citation collection.
Examples are in `discovery_examples/`. Paths in a scope file are relative to that
file. A run can contain journal discovery, citation discovery, or both.

```sh
python discovery.py journals
python discovery.py init --scope discovery_examples/journals-2015.json --out /tmp/journal-run
python discovery.py run /tmp/journal-run
python discovery.py status /tmp/journal-run
python discovery.py verify /tmp/journal-run
```

Replace the example scope values and directory with the requested ones. `init`
refuses to overwrite an existing directory. It saves the resolved `scope.json`,
hashes of the code and local input inventory, and copies of the discovery prompts.
The original source instructions and all previous survey data stay untouched.

Repeat `run` on the same directory to resume. Successful responses are cached with
query URLs and timestamps and are reused; citations are not silently refreshed.
To change scope, input inventory, code or the data snapshot, initialize a new run.
An existing run's code hash is enforced rather than claiming that different code
reproduced it. Run with the originally recorded code or start a new run after edits.

`--request-budget N` limits actual HTTP attempts in that invocation (default500,
including retries). Reaching it leaves a checkpoint; it does not shrink the cohort.
`--offline` permits only saved responses. `--seed-cache /path/to/cache` can reuse
prior discovery responses; the response dates remain their original dates and
used responses are copied into the new run. Seeded responses are not fresh counts.
Keep old and new run directories separate and report their relationship.

Exit status0 means collection stages finished,2 means a stage needs attention,
and1 means invalid inputs or an unrecoverable command error. `status.json` explains
which stage stopped and why. Even a finished collection can have provisional
rankings and unresolved paper identities. A populated CSV is not a completeness
certificate.

## Journal contents

```json
{
  "version": 1,
  "journals": {
    "start_year": 2018,
    "end_year": 2020,
    "journals": ["annals", "inventiones", "acta", "jams"],
    "include_errata": true,
    "date_padding_years": 2
  },
  "title_search": true
}
```

The range is inclusive and uses issue year. The four supported journal readers
discover volume/issue URLs from publisher indexes; no fixed2015 volume list or
arithmetic formula is used. An incomplete/unrecognized index leaves the requested
year explicit as missing. Metadata is collected from Crossref with cursor paging
where necessary. A wider publication-date window catches online-first records;
DOIs found in actual contents but absent from that window are retrieved individually.
Changing `date_padding_years` controls efficiency, not permission to omit an issue.

For another journal, supply its name, ISSN, and either an index reader or explicit
issues. Explicit issues are useful for publishers without a supported archive layout:

```json
{
  "version": 1,
  "journals": {
    "start_year": 2015,
    "end_year": 2015,
    "journals": [{
      "name": "Annals of Mathematics",
      "issn": "0003-486X",
      "style": "annals",
      "issues": [{
        "year": 2015, "volume": "181", "issue": "1",
        "url": "https://annals.math.princeton.edu/2015/181-1"
      }]
    }]
  }
}
```

This example deliberately scopes collection to one supplied issue. If the user
asked for a whole year, the agent must enumerate every issue before using an
explicit list. The program can verify the supplied issue sets; it cannot know
that a manually supplied list omitted an issue. Report whether issue enumeration
came from the publisher index or an explicit list. A custom `style: "generic"`
extracts DOI links as candidates only and requires review of the layout/coverage;
do not mistake reference links for the journal's own articles. Add a tested parser
when a new publisher's layout warrants it.

The program compares publisher DOI sets and record counts against Crossref.
Annals structured article URLs and AMS article PIIs need publisher-specific
conversion, including Crossref's alternative identifiers. Pages that fail, contain
unidentified articles or disagree with metadata stay unresolved. Metadata errors
do not authorize changing issue-year conventions. Corrections and errata are
separate records; their arXiv matches are not inherited from the original article.

## Citation-ranked arXiv cohorts

```json
{
  "version": 1,
  "citations": {
    "cohort": {
      "kind": "arxiv",
      "inventory": "/path/to/arxiv-metadata.jsonl.gz",
      "start_year": 2015,
      "end_year": 2017,
      "categories": ["math.FA", "math.NT", "math.PR"]
    },
    "top_percent": 10,
    "group_by": "category",
    "ties": "include",
    "exclude_retracted": true
  }
}
```

Inventories can be JSONL or gzip JSONL, with `id` and either `cats` (array) or
`categories` (array/space-separated string). Standard old and modern arXiv IDs
provide the submission year/month; invalid IDs are not assigned a guessed date.
The inventory must cover the requested years/categories. A local archive file's
existence does not establish this; the agent must state its provenance and known
coverage. The manifest hashes the inventory, and resume rejects changed input.

`group_by: "category"` ranks independently within each requested category,
including crosslists in each relevant group. `"pool"` ranks their deduplicated union.
Use `top_count: 100` instead of `top_percent` for a requested fixed count; do not
supply both. `ties: "include"` retains every work at the cutoff; `"exact"` uses
OpenAlex ID as the deterministic tie break. Report that policy, especially when
the list exceeds the nominal percentage/count.

The percentage denominator is the full cohort of IDs, before grouping IDs mapped
to one OpenAlex work and before the configured retraction exclusion. This is the
previous survey's convention. Rankings report both this denominator and matched
eligible works. Unknown counts are not zero. Multiple works for one ID remain
ambiguous; citations are not summed or chosen by maximum. Missing records make
rankings provisional. Excluded retractions remain separately visible.

## Citation-ranked OpenAlex cohorts

```json
{
  "version": 1,
  "citations": {
    "cohort": {
      "kind": "openalex",
      "filter": "publication_year:2015,primary_location.source.issn:0003-486X"
    },
    "top_count": 20,
    "group_by": "pool",
    "ties": "include"
  }
}
```

The filter is an explicit OpenAlex API filter, not prose translated silently into
guessed fields. It can specify journal ISSNs, years, topics, authors or other
supported attributes. This mode retrieves the full filtered population before
ranking, with basic paging through10,000 results and cursor paging beyond it.
Larger cursor retrieval may require a free API key. Several independently filtered
collections should use separate scopes; do not silently equate an OpenAlex topic
with an arXiv category. Counts are lifetime citations at response retrieval.

## Outputs and agent review

- `scope.json`, `manifest.json`, `status.json`: fixed request, hashes and progress.
- `journals.json`, `issues.json`: records and per-issue reconciliation where requested.
- `cohort.json`, `rankings.json`: full citation cohort, ranks, ties, exclusions and unknowns.
- `candidates.json`, `candidates.csv`: combined candidates with all selection reasons,
  deduplicated where OpenAlex supplies one work identity.
- `unresolved.json`: missing/ambiguous links, metadata and blocked requests.
- `cache/`: dated raw responses necessary to replay/inspect the evidence.

An optional `catalogue` path in the scope lets the program mark existing arXiv
identifiers using read-only SQLite; it does not exclude them from a ranking or
change the database. `ready_for_artifact_check` means a single identifier-linked
arXiv candidate can be inspected; it is not a claim of equivalent contents or a
mathematical ingestion approval.

Title searches produce review candidates, including an exact-normalized-title
signal. They are not automatically accepted as identity matches. Agents inspect
author lists, publisher/arXiv identifiers and version information, then save
`match-review.json` with evidence-backed decisions. Manual decisions are returned
separately; the collector does not silently apply them to the mathematics database
or overwrite the recorded metadata. For new parser support, save fixtures/tests
and start a new run under the new code, reusing the old cache explicitly.

Use [the journal prompt](../prompts/discover-journals.md) and
[the citation prompt](../prompts/discover-citations.md) to assign these tasks.
Give a worker the actual scope file/path, repository and run directory. It needs
no originating conversation. Handoff to mathematical curation uses the resulting
paper identifiers and inspected versions, without citation rankings or experiment
targets in the mathematical worker's instructions.

## API access and costs

`OPENALEX_API_KEY`, if set, is sent only in an Authorization header. Do not put it
in JSON, command arguments, URLs, fixtures or reports. A rate limit, unavailable
publisher or missing key leaves a resumable stage with its reason. Retries obey
short `Retry-After` delays; long waits are reported for later resume instead of
aggressively retrying. These commands do not create accounts, buy credits or call
a language-model API.

Current API details: [OpenAlex pagination](https://help.openalex.org/api/paging/)
and [Crossref API guidance](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/).
