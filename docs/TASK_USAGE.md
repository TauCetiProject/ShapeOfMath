# Measure token usage for each task

Use `task_usage.py` to record tokens reported by a model provider or by a session
log. Each API request or session interval belongs to one task. The ledger is a
separate SQLite file; it does not modify the mathematical database.

Keep one ledger for a survey so duplicate requests and shared work can be detected
across papers. The runner or coordinator records usage; mathematical workers do
not estimate their own tokens. A prepared task directory supplies its task ID and
kind. For other work, such as coordination, register an explicit task ID and kind.

## Record provider usage directly

After each API response, the runner should save the response's usage fields and
call `record`. For example, an Anthropic response can be recorded in this format:

```json
{
  "provider": "anthropic",
  "request_id": "ACTUAL_PROVIDER_REQUEST_ID",
  "model": "claude-opus-5-5",
  "usage": {
    "input_tokens": 1200,
    "cache_read_input_tokens": 8000,
    "cache_creation_input_tokens": 600,
    "output_tokens": 900
  },
  "settings": {"effort": "high"},
  "started_at": "ACTUAL_START_TIME",
  "finished_at": "ACTUAL_FINISH_TIME"
}
```

These numbers are illustrative. Copy the actual provider request ID, model and
usage; include only settings and timestamps the runner recorded. Never include
API keys, headers or message contents in this file.

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite record \
  --task /path/to/source-task --response /path/to/response-usage.json
```

For an OpenAI Responses-style usage object, use `provider: "openai"` and supply
the provider's `input_tokens`, `input_tokens_details.cached_tokens`, `output_tokens`
and `output_tokens_details.reasoning_tokens` where available. Input includes cache
reads in that format; fresh input is computed by subtracting those reads. Anthropic
input excludes its separately reported cache reads and cache creation. The ledger
retains the raw usage and normalized fields so these conventions are inspectable.

If another runner already reports normalized counts, use `provider: "normalized"`
and the fields `fresh_input_tokens`, `cache_read_input_tokens`,
`cache_write_input_tokens`, `output_tokens` and optional `reasoning_output_tokens`.
Missing fields remain null. Do not use zero to mean unavailable.

The Python function `task_usage.record_api(connection, task_id, response)` is the
same hook for a runner that records responses directly. Use `task_usage.connection`
to open the ledger and `register` to register the task first. This hook and CLI do
not run a model or intercept arbitrary SDK calls automatically: wire them into the
runner's response handler. Keep stable request IDs so retrying the accounting call
is harmless; a second charge under another task or changed usage is rejected.

## Measure an interval in a Codex session log

For a worker whose JSONL session log exposes cumulative `token_count` events,
start measurement **before** assigning the task to that session:

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite start \
  --task /path/to/source-task --session /path/to/session.jsonl --model ACTUAL_MODEL
```

Save the returned `window_id`. Complete the worker's task and wait until its usage
event has been written, then finish that exact interval:

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite finish WINDOW_ID
```

The start command records the current complete-line byte offset, counters and a
hash of the log prefix. Finish adds only counter differences written after that
boundary, ignores duplicate counter notifications, and saves the exact offset,
before/after counters and evidence hash. It rejects counter resets, changed prefixes,
overlapping intervals and model changes reported in the interval. One session can
have only one open owner task. Finish before switching that session to another task;
use another window to resume a task later.

A log that does not yet exist has a zero baseline. An existing log with no reported
initial counters has an unknown baseline; its first cumulative counter cannot be
reliably attributed to a later task and is rejected. A window with no new counters
is recorded as unknown, not free work. Partial final JSONL lines are left for a
later window. Do not finish while task usage is still being written; delayed
counters after a boundary otherwise belong to the wrong interval. Descendant
agents and other sessions are not automatically included: register their actual
task intervals or response usage separately.

Session counters are measured telemetry, not an independently reconciled billing
invoice. Providers can tokenize differently, and the ledger cannot verify a model
name not present in the log. Preserve the runner's model/settings evidence.

If counters reset, the log is lost or an interval was otherwise not measurable,
stop that work interval and run `abandon WINDOW_ID --reason 'EXACT_REASON'` using
the same ledger. This closes it with unknown counts and preserves the explanation;
it does not estimate a charge or mark the measurement complete. A later interval
can then start from a known baseline.

## Keep shared prerequisite work separate

A cone needed by several papers should have its own task and its own measurements.
Reference it from those papers instead of copying its token counts into each one:

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite register \
  --task /path/to/shared-cone-task
python task_usage.py --ledger /path/to/survey-usage.sqlite share \
  --task-id PAPER_TASK_ID --shared-task-id CONE_TASK_ID
```

Shared references can point to other shared tasks; cycles are rejected. A report
for several papers includes each shared task once in its total, even when two
papers reference it. A paper's own usage stays separate. This records work actually
done; it does not invent a per-paper allocation for shared background work.

For work without a prepared source/cone directory:

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite register \
  --task-id survey-coordination --kind coordination
```

`register`, `record` and `start` accept `--task-id ID --kind KIND` instead of
`--task DIRECTORY`. Kinds are source, cone, shared, coordination and other.

## Export a report

```sh
python task_usage.py --ledger /path/to/survey-usage.sqlite report \
  --task-id PAPER_TASK_ID --out /path/to/source-task/output/usage.json
```

Repeat `--task-id` to report several tasks, or omit it to include the whole ledger.
The report separates fresh input, cache reads, cache writes, output and reasoning.
Reasoning is a subset of output; never add it a second time. Missing components
stay null, with separately labeled known subtotals. An included task with no samples
or an unfinished interval prevents a complete total. Open intervals and missing
tasks are reported explicitly.

Use provider prices only after checking that the required components are available.
Do not convert a null count into zero to produce a dollar estimate. The report
does not itself promise complete coverage of every request the runner made; the
runner must record every response or correctly bracket every dedicated session.
