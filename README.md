# SpanLife artifact

## Environment

The retained executions used Linux, Python 3.13.5, OpenTelemetry API/SDK 1.42.1,
OpenTelemetry semantic conventions 0.63b1, FastAPI 0.128.2, Starlette 0.50.0,
AnyIO 4.13.0, HTTPX 0.28.1, and wrapt 2.2.1. The exact Python closure is in
`requirements.txt`; host details are in `provenance/environment.json`.

All experiments are local and CPU-only. They require no credentials, live
service, model inference, GPU, paid API, production load, or remote collector.

## Verify retained evidence

```sh
export PYTHONPATH="$PWD/src:$PWD/vendor"
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
* the recorded unit suite and 70 cited bibliography records; and
* affected 0.44b0/0.65b0 and fixed 0.66b0 release lineage.

`results/integrity-check.json` is the machine-readable verification record.

The earlier source-suite count was 340 tests; ten focused policy-evidence
regressions are supplied separately. Source tests and offline recomputation of
retained records are distinct from new execution of all service experiments.
`scripts/verify.py` also checks the companion manuscript in a sibling `paper/`
directory; the standalone code repository uses the tests and record checks.

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
current acceptance result. No new current JSON dataset is installed here.

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

```sh
python -m spanlife.check_record \
  results/topology-challenge/split_link_valid__000.json
python -m spanlife.check_record \
  results/topology-challenge/split_missing_relation__000.json --format json
```

The text and JSON reports include the finding, operation and segment, suggested
owner, bounded next action, recomputation consistency, and CI exit class.

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
