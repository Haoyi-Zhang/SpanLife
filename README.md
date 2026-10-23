# SpanLife artifact

The topology runner requires every planned observation to complete and satisfy
its predeclared verdict and diagnostic codes. Two implementations agreeing on
the same wrong answer is a failing campaign.

`results/current-offline-validation.json` separates exact archival replay from
current reanalysis of retained observations; it runs no new SDK trials. The
current-compatible raw CI inputs are in `results/ci-examples/current-raw/`, with
pass, fail, and inconclusive examples derived from recorded observations. The
historical missing-handoff compatibility diagnostic remains in
`results/ci-examples/current-reanalysis.json`: it preserves the scientific
failure and reports record mismatch with exit code 3. The older reports and raw
observations remain unchanged. To write a new offline verification report without
replacing an older one, use `python -B scripts/verify.py --output <new-output.json>`.

## Environment

The lifecycle executions used Linux, Python 3.13.5, OpenTelemetry API/SDK 1.42.1,
OpenTelemetry semantic conventions 0.63b1, FastAPI 0.128.2, Starlette 0.50.0,
AnyIO 4.13.0, HTTPX 0.28.1, and wrapt 2.2.1. The exact Python closure is in
`requirements.txt`; host details are in `provenance/environment.json`.

The paper's local cost campaign uses Windows 11, CPython 3.12.14, an Intel
Core i7-12700KF, and OpenTelemetry API/SDK 1.42.1. Its 90 fresh-process samples
and measured environment are in `results/costs-local`. The original Linux
cost observations remain in `results/costs`; the two environments are not
pooled. Summary generation selects `costs-local` by default and accepts an
explicit `--cost-dir` for a separate campaign.

All experiments are local and CPU-only. They require no credentials, live
service, model inference, GPU, paid API, production load, or remote collector.

The paper's timing illustrations are generated from retained observations with Python and ReportLab. The workflow is drawn directly with Matplotlib. Install `requirements-figures.txt` and use the Times AFM/PFB fonts supplied by TeX Live. `scripts/build_paper_assets.py` regenerates the tables, interval CSV, vector PDFs and matching LaTeX inclusion wrappers together:

```sh
python -m pip install -r requirements-figures.txt
python scripts/build_paper_assets.py --font-root /path/to/texmf-dist/fonts
```

Without `--font-root`, the script locates the font directory with `kpsewhich`.
Fonts and input files are checked before generation. All tables, PDFs, CSV and
wrappers are generated in an isolated tree before publication; an ordinary
publication failure rolls back replaced files and removes newly installed files.
If rollback itself fails, the error reports a retained recovery-backup directory
outside the disposable build tree. This is not a crash-safe transaction.
Use `--paper-dir <directory>` to select a separate output. The workflow helper
stages its PDF and wrapper together and preserves both old files on renderer
failure. No TikZ source is written over that wrapper. This regenerates
presentation assets, not experimental measurements. The topology table requires
the supplied summary to match trial rows and rejects direct-check disagreement.

## Verify retained evidence

Run from this `artifact/` directory. The bounded SDK-free pytest subset below
can use Python 3.12 with `python -m pip install pytest==9.0.2`; `pytest.ini`
adds `src` and `vendor` on every platform. Native/service replay additionally
requires `python -m pip install -r requirements.txt` in the declared environment.
Those frozen Linux/Python 3.13.5 dependency versions and results are not replaced
by a Windows offline check.

For the direct `scripts/` and `python -m spanlife.check_record` commands, set the
source path explicitly. On POSIX:

```sh
export PYTHONPATH="$PWD/src:$PWD/vendor"
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "$PWD/src;$PWD/vendor"
```

Then:

```sh
python scripts/verify_release_lineage.py
python scripts/audit_references.py
python scripts/verify.py
python -m pytest -q
```

Expected retained results include:

* 800 principal processes plus 40 preserved failed preflight attempts;
* 800 independent replay processes with 793 verdict agreements, seven
  clock-only transitions, and no pass--fail reversal;
* 100 executable-operator processes with 99 exact outcomes and 90 native-test
  mutation processes with 2/10 legacy and 7/10 strengthened mechanism coverage;
* 12 topology/correlation processes, 20 operation contracts, 28 segment
  contracts, 12 exact outcomes, no direct-assertion disagreement, and six
  name-baseline disagreements;
* 40 Speaches, 100 UiPath confirmation, and 100 UiPath correction processes;
* 360 serialized transformations, 300 role counterfactuals, 120 evidence-gate
  ablations, and 90 process-level cost samples;
* the recorded unit suite and 69 current cited bibliography records; and
* affected 0.44b0/0.65b0 and fixed 0.66b0 release lineage.

`results/integrity-check.json` is the machine-readable verification record.

The 18 serialized challenge kinds are targeted record transformations, including
valid controls and mechanism-specific changes that can affect multiple evidence
fields. For example, `missing_span` removes a span and changes its end witness;
`collection_unqualified` also clears the drain flag, and `duplicate_association`
adds both a span and its association ID. The historical "one-field" wording in
`provenance/evaluation-amendment.md` is retained as recorded, not as a description
of every transformation. Original raw records, classification labels, expected
diagnostics, judgments, and summary values are unchanged; current generator
documentation and generated presentation labels use the targeted-record term.

The source suite includes focused policy-evidence, operation-execution,
cost-record, raw-record validation, and failure-preserving asset regressions. Source
tests and offline recomputation of
retained records are distinct from new execution of all service experiments.
`scripts/verify.py` also checks the companion manuscript in a sibling `paper/`
directory; the standalone code repository uses the tests and record checks.
Native-matrix verification reads the exact expected raw suite/operator/method
coverage, compares complete raw rows with `rows.json`, and recomputes the full
summary using the producer's aggregation. Historical result files are not rewritten.

`python scripts/check_retained_records.py` checks records without running the
service experiments. For the 12 topology records it reports two separate
checks: exact archival replay using the hash-pinned topology-era checker and
baselines, and current qualification of the same observations in memory.
The retained raw JSON, stored judgments, process receipts, timings, trial rows,
and summary are not rewritten. Shared pure row/summary functions are used by
both the topology runner and verifier; the verifier checks their full outputs.

Current relation findings affect the source segment's verdict. In the retained
missing- and wrong-handoff cases, that changes only `execute` from `pass` to
`fail`; both historical overall verdicts were already `fail`. The verifier
requires these two precise changes, all other judgment fields to agree, and
current valid controls, abstentions, diagnostics, and segment aggregation to
meet their contracts. Current in-memory rollups retain 12 outcomes, 20 operation
contracts, 28 segment contracts, and zero direct disagreements. This is
reanalysis, not another 12 fresh processes or a new timing measurement.

The single-record CI checker still compares stored judgments with current
qualification exactly: these two historical JSONs report `RECORD_MISMATCH`
and exit 3. Archival reproducibility does not make their old segment `pass` a
current acceptance result. The current CI examples below are derived inputs,
not a new execution dataset.

## Fresh execution without overwriting retained data

```sh
python scripts/run_matrix.py \
  --output results/reproduced-principal --repeats 20 --workers 2
python scripts/run_topology_challenge.py \
  --output results/reproduced-topology --repeats 1 --workers 2
python scripts/run_executable_perturbations.py \
  --output results/reproduced-operators --repeats 10 --workers 2
python scripts/run_speaches_holdout.py \
  --output results/reproduced-speaches --repeats 10
python scripts/run_uipath_holdout.py \
  --output results/reproduced-uipath --repeats 10 --workers 2
```

Runners refuse to overwrite a directory containing an execution manifest.
The topology runner reserves that manifest before launching children, retains
process receipts for nonzero exits, timeouts and missing/malformed records,
and excludes failed or invalid records from scored rows.

The cost driver calls every warm-up and measured operation unconditionally,
checks the arithmetic result explicitly, and checks the ledger event count
after timing. These checks remain active under Python optimization. The
SDK-free operation controls can be run with either interpreter configuration:

```sh
PYTHONPATH=src python -B -m unittest discover -s tests -p test_benchmark_operation_execution.py
PYTHONPATH=src python -B -O -m unittest discover -s tests -p test_benchmark_operation_execution.py
```

Each invocation tests both ordinary and optimized child processes. These
execution and rejection controls are separate from the 90 measured local
SDK samples. The campaign launches fresh interpreters without forwarding a
parent's command-line `-O`; an inherited `PYTHONOPTIMIZE` setting does apply
to those children. The measured local campaign used ordinary execution.

```sh
python scripts/benchmark.py --output results/reproduced-costs --blocks 15 --n 1000 --warmup 200
python scripts/summarize.py --cost-dir results/reproduced-costs --output results/reproduced-summary --no-paper
```

The cost reader checks complete block pairing, typed operation denominators,
ledger and SDK span counts, and elapsed-time consistency before aggregation.
Its malformed-record controls run with the following command, also under `-O`:

```sh
python -m unittest discover -s tests -p test_cost_records.py
```

## Multi-segment contract sketch

A policy may retain the legacy fields or declare `segments` and `relations`:

```json
{
  "operation_id": "op-17",
  "segments": [
    {
      "segment_id": "submit",
      "role": "submission",
      "span_name": "operation.submit",
      "association": {
        "kind": "attributes",
        "match": {
          "spanlife.operation_id": "op-17",
          "spanlife.segment": "submit"
        }
      }
    },
    {
      "segment_id": "execute",
      "role": "execution",
      "span_name": "operation.execute",
      "association": {
        "kind": "attributes",
        "match": {
          "spanlife.operation_id": "op-17",
          "spanlife.segment": "execute"
        }
      },
      "exclude_queue": true,
      "exclude_submission": true
    }
  ],
  "relations": [
    {"from": "execute", "to": "submit", "kind": "parent-or-link"}
  ]
}
```

Exactly one span must satisfy each segment association before semantic checks
run. Relations are evaluated only after both endpoints are uniquely associated.
An unresolved declared relation contributes `RELATION_EVIDENCE_MISSING` and an
inconclusive result to its source segment, including when an endpoint is
context-only. An observed context identity alone is not span-relation evidence;
without a declared span relation, matching context-only identity can still pass.
Relation findings contribute to the source segment's final status. Legacy flat
policies retain explicit `span_ids` selection in mixed records; name fallback
belongs to normalized segments, not to unrelated flat policies. Context-only
policies abstain without a declared `expected_context` or its observation.
For an absent candidate, omitted `ended_witness` is unknown, explicit zero
permits a missing-span failure after collection qualification, and a positive
count indicates export loss. No span or clock qualification is required merely
to check an observed context identity.

## CI report

Run the complete SDK-free adapter example from this directory:

```sh
python -B -S scripts/ci_contract_smoke.py
```

It invokes the real CLI in four isolated interpreters: a current passing
record exits 0, a current semantic failure exits 1, strict inconclusive exits
2, and the retained historical missing-handoff record exits 3 for stored/current
disagreement. The wrapper checks both exit status and semantic JSON; success
means these adapter contracts held, not that the failing service record passed.
The same command is an explicit step in the supplied Windows/Linux workflow.
The recorded execution is `results/ci-examples/cli-contract-smoke.json`; it
binds the four inputs and current checker sources, with zero new SDK/service
trials. Use `--output <new-file.json>` to retain a separate run without replacing
that record. This demonstrates executable CI routing, not measured human
integration effort or field deployment.

Use the current raw inputs for ordinary CI examples:

```sh
python -m spanlife.check_record \
  results/ci-examples/current-raw/pass.json
# exit 0: PASS
python -m spanlife.check_record \
  results/ci-examples/current-raw/fail.json --format json
# exit 1: FAIL, MISSING_HANDOFF_RELATION; execute segment fails
python -m spanlife.check_record \
  results/ci-examples/current-raw/inconclusive.json --format json --fail-on-inconclusive
# exit 2: INCONCLUSIVE, AMBIGUOUS_ASSOCIATION
```

These are **current reanalysis of recorded observations**, not new SDK
executions. Their respective sources are
`results/topology-challenge/split_link_valid__000.json`,
`results/topology-challenge/split_missing_relation__000.json`, and
`results/topology-challenge/correlated_duplicate_attribute__000.json`.
Only `ledger_check` is recomputed with the current oracle; the added `reanalysis`
field identifies the source, updated field, and zero new runtime trials.
All other fields, including policies, observations, calibration, revision,
execution status, and baseline judgments, are copied from the historical record.
The missing-handoff example remains an overall failure; its current `execute`
segment is also `fail`.

To derive another raw input without changing the source, choose a new output
file in an existing directory (the producer refuses to overwrite any file):

```sh
python -B scripts/reanalyze_record.py \
  results/topology-challenge/split_missing_relation__000.json \
  --output results/ci-examples/my-record.json
```

The producer's successful exit means the derived file was written, not that its
observations passed qualification. Run `spanlife.check_record` on that output
to obtain the semantic exit code. Without `--fail-on-inconclusive`, inconclusive
records exit 0 even though the report's `ci_exit_code` remains 2.

For the historical compatibility diagnostic, check the original raw record:

```sh
python -m spanlife.check_record \
  results/topology-challenge/split_missing_relation__000.json --format json
# exit 3: FAIL with record_consistent=false (RECORD_MISMATCH in text format)
```

This diagnostic and `results/ci-examples/current-reanalysis.json` retain the
stored-versus-current difference; no mismatch check is bypassed. The existing
`results/ci-examples/{pass,fail,inconclusive}.json` files are report outputs,
and `current-reanalysis.json` wraps a report; none is a raw checker input.

The text and JSON reports include the finding, operation and segment, suggested
owner, bounded next action, recomputation consistency, and CI exit class.

The SDK-free example and historical-boundary tests can be run directly:

```sh
python -B -m pytest -q tests/test_current_ci_examples.py tests/test_retained_topology.py
```

### External-record admission and partial evidence

Malformed record or contract fields are rejected with `INVALID_RECORD` and
CLI exit 2, without a semantic judgment. Timestamps must be integer nanoseconds;
floats (including NaN/infinity), booleans, and strings are not timestamps.
Omitted or null timestamp observations are instead unresolved evidence.
Interval checks require complete, ordered wall and monotonic operation bounds,
ordered span bounds, and `epsilon_ns <= cap_ns`; records without `cap_ns` use
the protocol's 100,000 ns default. The external producer remains responsible
for its calibration and declared cap.

An execution/both policy with `error_on_escape` needs a known exit outcome and,
if raised, a known exception type to resolve `non_error_types`. Missing/null or
`unknown` outcome/type evidence cannot silently satisfy that obligation.
Missing/null or `unknown` status and missing/null event capture abstain when
required; an observed `UNSET`/`OK` status or empty event list can fail a qualified
escaping-error policy. Qualified independent violations retain fail priority.
Null expected context/parent identities are unknown expectations, and an
incomplete link identity is not proof of a missing handoff.

The bounded offline subset can run without a tracing SDK:

```sh
python -m pytest -q tests/test_oracle.py tests/test_p119_contract_repair.py \
  tests/test_policy_evidence_regressions.py tests/test_external_qualification.py \
  tests/test_uipath_close_order.py
```

On CPython 3.12.14 with pytest 9.0.2, this subset passes 513 tests and 440
subtests. It is not the complete native/service suite. The UiPath ordering test
executes the hash-pinned public function and the retained local replacement
with a recording-only tracer seam: ten public early closes return before inner
cleanup finishes, and ten corrected closes finish cleanup before span end.
Those are in-process semantic checks, not new SDK measurements, fresh-process
study trials, complete-package execution, or maintainer validation.

## Render retained timing illustrations

The workflow is a separate direct Matplotlib vector with embedded fonts.
In the project bundle, `paper/build.py` regenerates it before compilation.
TeX engines are checked first; workflow generation and compilation occur in an
isolated work tree. The workflow PDF/wrapper and manuscript PDF are published
together only after the build and log checks succeed.

```sh
python scripts/workflow_assets.py --output-dir ../paper/figures
```

Install `requirements-figures.txt`, then run
`python scripts/render_paper_figures.py --source plot_inputs/trace_intervals.csv --output-dir figures --font-root /path/to/texmf-dist/fonts`.
The two embedded-font vector plots select one retained pair each; they are
illustrations rather than aggregate timing estimates. The renderer preserves
negative pre-entry times and does not run the SDK or replace study records.
Its five route checks are included in the ordinary test suite.

## License

Original code is licensed under MIT; see `LICENSE`. Retained upstream sources
keep their own notices and licenses.

## Provenance boundary

`provenance/frozen-core/` retains the exact single-span checker used before the
principal evaluation. `provenance/topology-contract-amendment.md` explains the
post-evaluation extension, and `provenance/core-freeze.json` pins both source
generations. The verifier recomputes old records through the preserved legacy
path. Topology records replay exactly through the pinned evaluated snapshot
and are separately reanalyzed through the current checker as described above;
the frozen sources and their hashes remain historical evidence.

## Portable path notation

Published execution records use `<PYTHON_ROOT>`, `<NODE_ROOT>` and `<RUNTIME_ROOT>` for local tool installations, `<DEPENDENCIES_ROOT>` for local dependencies, and `<PROJECTS_ROOT>`, `<ARTIFACT_ROOT>`, `<SOURCE_ROOT>` and `<WORK_ROOT>` for the workspace, artifact checkout, source checkout and temporary work directory of the recorded run. These are path aliases, not literal directories or claims that historical temporary files are included in this bundle. Substitute the corresponding local roots when replaying a command. Recorded tool versions, source/input identities, measurements, outcomes and failures are unchanged. Current file inventories bind the portable published bytes; any `recorded_` identity denotes pre-normalization bytes.
