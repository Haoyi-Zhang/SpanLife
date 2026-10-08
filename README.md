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

The current suite contains 324 tests. Current tests and offline recomputation of
retained records are distinct from new execution of all service experiments.
`scripts/verify.py` also checks the companion manuscript in a sibling `paper/`
directory; the standalone code repository uses the tests and record checks.

## Fresh execution without overwriting retained data

```sh
python scripts/run_matrix.py \
  --output results/reproduced-principal --repeats 20 --workers 2
python scripts/run_topology_challenge.py \
  --output results/reproduced-topology --repeats 1 --workers 2
python scripts/run_executable_perturbations.py \
  --output results/reproduced-operators --repeats 10 --workers 2
python scripts/run_speaches_holdout.py \
  --output results/reproduced-speaches --repeats 10 --workers 2
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

## CI report

```sh
python -m spanlife.check_record \
  results/topology-challenge/split_link_valid__000.json
python -m spanlife.check_record \
  results/topology-challenge/split_missing_relation__000.json --format json
```

The text and JSON reports include the finding, operation and segment, suggested
owner, bounded next action, recomputation consistency, and CI exit class.

## Provenance boundary

`provenance/frozen-core/` retains the exact single-span checker used before the
principal evaluation. `provenance/topology-contract-amendment.md` explains the
post-evaluation extension, and `provenance/core-freeze.json` pins both source
generations. The verifier recomputes old records through the preserved legacy
path and the topology records through the amended path.
