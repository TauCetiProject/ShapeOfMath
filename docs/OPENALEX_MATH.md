# OpenAlex mathematics snapshot

`openalex_math.py` republishes the mathematics part of the quarterly
[OpenAlex snapshot](https://help.openalex.org/access/snapshot/) (CC0) in the same layout
and with the same update rules, so that it can be mirrored and kept current the way
upstream is ([sync guide](https://help.openalex.org/access/sync/)).

## Selection

A work is included when `primary_topic.field.id` is
`https://openalex.org/fields/26` (Mathematics) and `is_xpac` is false. Rows are copied
unchanged with every upstream column. Works whose only mathematics topic is a secondary
topic are not included.

## Layout

```
data/parquet/manifest.json                       combined manifest (written last)
data/parquet/works/manifest.json
data/parquet/works/updated_date=D/part_NNNN.parquet
data/parquet/works/deleted_ids.csv.gz            work_id,deleted_date
data/parquet/works/merged_ids.csv.gz             id,merge_into_id,merge_date
data/parquet/citations/manifest.json
data/parquet/citations/updated_date=D/part_NNNN.parquet   cited_work_id,citing_work_id
state.json                                       per-partition bookkeeping for the next release
```

Manifests have the upstream format. The combined manifest also records the upstream
release date, a hash of the upstream works manifest, and the filter.

- **works**: the selected rows of upstream partition `D` are stored in our partition
  `D`. Each work appears exactly once, in the partition of its last change.
- **citations**: one row for each distinct link from a non-xpac work (in any field) to
  a selected work, stored in the partition of the **cited** work. Outgoing references
  of selected works are already present as `referenced_works`. References are resolved
  through upstream `merged_ids` when that file is present. Duplicates are collapsed.
- **deleted_ids**: a cumulative ledger of works that left this dataset. They were
  deleted upstream (with the upstream date), or they stopped being selected because
  their topic changed or they became xpac (dated by the release that dropped them). A
  work that returns is removed from the ledger.
- **merged_ids**: the upstream merge ledger, restricted to ids this dataset has
  published.

## Incremental releases

Each run classifies every upstream partition by comparing its selected ids with the
previous release:

- **keep**: same ids, and the files are left untouched.
- **prune**: a subset of the ids, because records moved to newer partitions or were
  deleted. The previous files are filtered without re-reading upstream.
- **extract**: new ids, so the partition is read from upstream. In practice these are
  the partitions newer than the last release. The first release extracts everything.

Every run reads the small columns `id`, `is_xpac`, `primary_topic` and
`referenced_works` from every upstream file. It must, because a work that newly becomes
mathematics can be cited by records in old partitions. A citations partition is
rewritten only when its content hash changes. Unlike works partitions, an old
citations partition **can gain rows**, so mirror it with `aws s3 sync --delete`, not
by partition date alone.

The run removes our manifests first and writes them last, and it fails if the upstream
manifest changed while it ran.

## Running a release

```
./openalex_math_ec2.sh setup          # once: bucket openalex-math-<account>, IAM instance profile
./openalex_math_ec2.sh launch         # after each upstream release (2nd Wednesday of Jan/Apr/Jul/Oct)
./openalex_math_ec2.sh status RUN
```

The instance (default `r7i.xlarge`, 4 vCPU) runs in us-east-1 next to the upstream
bucket, so reading upstream costs nothing in transfer. It downloads the previous release
from our bucket, runs `openalex_math.py release`, publishes and terminates itself. A
hard stop applies after 12 hours. Logs go to `s3://BUCKET/runs/RUN/log.txt`.

To run locally against any copy laid out like upstream:

```
uv run --with pyarrow --with numpy python openalex_math.py release \
    --upstream s3://openalex/data/parquet --out DIR
```

Tests: `uv run --with pyarrow --with numpy python -m unittest tests.test_openalex_math`.
