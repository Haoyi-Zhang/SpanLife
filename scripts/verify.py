#!/usr/bin/env python3
"""Offline integrity and result-consistency check; no replay or network required."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import types
from collections import Counter
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify
from spanlife.topology_records import EXPECTED, TOPOLOGY_CASES, summarize_rows, trial_row
from cost_records import load_cost_records


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text())


def check_principal() -> tuple[int, int]:
    completed = retained_failures = 0
    for directory in ("evaluation", "holdout-corrected"):
        for path in sorted((ROOT / "results" / directory).glob("*__*.json")):
            run = load_json(path)
            if run["execution"]["status"] != "completed":
                retained_failures += 1
                continue
            if not (qualify(run) == run["ledger_check"]):
                raise AssertionError(f"ledger mismatch: {path}")
            if not (direct_assertions(run) == run["direct_check"]):
                raise AssertionError(f"direct mismatch: {path}")
            if not (existence_and_name(run) == run["name_check"]):
                raise AssertionError(f"name mismatch: {path}")
            completed += 1
    if not ((completed, retained_failures) == (800, 40)):
        raise AssertionError((completed, retained_failures))
    return completed, retained_failures


def check_speaches() -> dict:
    adapter = ROOT / "adapters/speaches/tracing.py"
    source_info = load_json(ROOT / "adapters/speaches/source-info.json")
    if not (git_blob(adapter.read_bytes()) == source_info["git_blob_sha1"]):
        raise AssertionError()
    rows = []
    for path in sorted((ROOT / "results/speaches-holdout").glob("*__*.json")):
        run = load_json(path)
        if not (run["execution"]["status"] == "completed"):
            raise AssertionError(path)
        if not (qualify(run) == run["ledger_check"]):
            raise AssertionError(path)
        if not (direct_assertions(run) == run["direct_check"]):
            raise AssertionError(path)
        if not (existence_and_name(run) == run["name_check"]):
            raise AssertionError(path)
        rows.append(run)
    if not (len(rows) == 40):
        raise AssertionError(len(rows))
    verdicts = Counter(r["ledger_check"]["verdict"] for r in rows)
    if not (verdicts == Counter({"pass": 24, "inconclusive": 9, "fail": 7})):
        raise AssertionError(verdicts)
    summary = load_json(ROOT / "results/speaches-holdout/summary.json")
    if not (summary["trials"] == len(rows)):
        raise AssertionError()
    if not (summary["direct_disagreements"] == 0):
        raise AssertionError()
    if not (summary["name_misses_with_ledger_fail"] == 7):
        raise AssertionError()
    return {"trials": len(rows), "verdicts": dict(verdicts)}


def check_mutations() -> dict:
    rows = []
    for path in sorted((ROOT / "results/mutation-challenge").glob("*.json")):
        if path.name == "summary.json":
            continue
        run = load_json(path)
        if not (run["execution"]["status"] == "completed"):
            raise AssertionError(path)
        if not (qualify(run) == run["ledger_check"]):
            raise AssertionError(path)
        if not (direct_assertions(run) == run["direct_check"]):
            raise AssertionError(path)
        if not (existence_and_name(run) == run["name_check"]):
            raise AssertionError(path)
        expected = run["mutation"]["expected_verdict"]
        code = run["mutation"]["expected_code"]
        if not (run["ledger_check"]["verdict"] == expected):
            raise AssertionError(path)
        codes = {f["code"] for f in run["ledger_check"]["findings"]}
        if code is None:
            if not (not codes):
                raise AssertionError((path, codes))
        else:
            if not (code in codes):
                raise AssertionError((path, code, codes))
        rows.append(run)
    if not (len(rows) == 360):
        raise AssertionError(len(rows))
    summary = load_json(ROOT / "results/mutation-challenge/summary.json")
    if not (summary["mutations"] == 18):
        raise AssertionError()
    if not (summary["derived_trials"] == len(rows)):
        raise AssertionError()
    if not (summary["exact_expected_verdicts"] == len(rows)):
        raise AssertionError()
    if not (summary["exact_expected_diagnostics"] == len(rows)):
        raise AssertionError()
    if not (summary["direct_disagreements"] == 0):
        raise AssertionError()
    return {"kinds": summary["mutations"], "derived_judgments": len(rows)}


def check_replay() -> dict:
    replay_dir = ROOT / "results/replay-20261003-full"
    manifest = load_json(replay_dir / "execution-manifest.json")
    if not (manifest["trials"] == 800):
        raise AssertionError()
    if not (not manifest["failures"]):
        raise AssertionError()
    rows = []
    for path in sorted(replay_dir.glob("*__*.json")):
        run = load_json(path)
        if not (run["execution"]["status"] == "completed"):
            raise AssertionError(path)
        if not (qualify(run) == run["ledger_check"]):
            raise AssertionError(path)
        if not (direct_assertions(run) == run["direct_check"]):
            raise AssertionError(path)
        if not (existence_and_name(run) == run["name_check"]):
            raise AssertionError(path)
        rows.append(run)
    if not (len(rows) == 800):
        raise AssertionError(len(rows))
    comparison = load_json(ROOT / "results/replay-20261003-comparison.json")
    if not (comparison["replay_trials"] == comparison["retained_trials"] == 800):
        raise AssertionError()
    if not (comparison["verdict_agreement"] == 793):
        raise AssertionError()
    if not (comparison["verdict_changes"] == comparison["clock_qualification_changes"] == 7):
        raise AssertionError()
    if not (comparison["pass_fail_flips"] == 0):
        raise AssertionError()
    if not (comparison["direct_disagreements_retained"] == comparison["direct_disagreements_replay"] == 0):
        raise AssertionError()
    return {
        "fresh_process_trials": len(rows),
        "verdict_agreement": comparison["verdict_agreement"],
        "clock_only_changes": comparison["clock_qualification_changes"],
        "pass_fail_flips": comparison["pass_fail_flips"],
    }


def check_executable_perturbations() -> dict:
    directory = ROOT / "results/executable-perturbations"
    manifest = load_json(directory / "execution-manifest.json")
    if not (manifest["trials"] == 100):
        raise AssertionError()
    if not (not manifest["failures"]):
        raise AssertionError()
    rows = load_json(directory / "trials.json")
    if not (len(rows) == 100):
        raise AssertionError()
    expected = {
        "early_end", "late_start", "queue_inclusive", "no_span",
        "duplicate_span", "wrong_parent", "missing_error_status",
        "missing_exception_event", "first_call_only", "empty_context_execution",
    }
    if not ({r["perturbation"] for r in rows} == expected):
        raise AssertionError()
    summary = load_json(directory / "summary.json")
    if not (summary["perturbations"] == 10):
        raise AssertionError()
    if not (summary["fresh_process_trials"] == 100):
        raise AssertionError()
    if not (summary["runner_failures"] == 0):
        raise AssertionError()
    if not (summary["exact_expected_verdicts"] == 99):
        raise AssertionError()
    if not (summary["expected_diagnostic_present"] == 99):
        raise AssertionError()
    if not (summary["direct_disagreements"] == 0):
        raise AssertionError()
    if not (summary["name_misses_with_ledger_fail"] == 69):
        raise AssertionError()
    if not (sum(x["clock_ineligible"] for x in summary["by_perturbation"].values()) == 2):
        raise AssertionError()
    # Recompute every completed raw record rather than trusting trials.json.
    raw = []
    for path in sorted(directory.glob("*.json")):
        if path.name in {"summary.json", "trials.json", "execution-manifest.json"}:
            continue
        run = load_json(path)
        if not (run["execution"]["status"] == "completed"):
            raise AssertionError(path)
        if not (qualify(run) == run["ledger_check"]):
            raise AssertionError(path)
        if not (direct_assertions(run) == run["direct_check"]):
            raise AssertionError(path)
        if not (existence_and_name(run) == run["name_check"]):
            raise AssertionError(path)
        raw.append(run)
    if not (len(raw) == 100):
        raise AssertionError()
    return {
        "operators": summary["perturbations"],
        "fresh_process_trials": len(raw),
        "exact_expected_verdicts": summary["exact_expected_verdicts"],
        "exact_expected_diagnostics": summary["expected_diagnostic_present"],
        "direct_disagreements": summary["direct_disagreements"],
    }



def check_uipath() -> dict:
    source = ROOT / "adapters/uipath/decorators.py"
    info = load_json(ROOT / "adapters/uipath/source-info.json")
    if not (git_blob(source.read_bytes()) == info["git_blob"]):
        raise AssertionError()

    def inspect(directory: str) -> tuple[list[dict], Counter, dict]:
        base = ROOT / "results" / directory
        rows = []
        for path in sorted(base.glob("*__*.json")):
            run = load_json(path)
            if not (run["execution"]["status"] == "completed"):
                raise AssertionError(path)
            if not (qualify(run) == run["ledger_check"]):
                raise AssertionError(path)
            if not (direct_assertions(run) == run["direct_check"]):
                raise AssertionError(path)
            if not (existence_and_name(run) == run["name_check"]):
                raise AssertionError(path)
            rows.append(run)
        summary = load_json(base / "summary.json")
        verdicts = Counter(r["ledger_check"]["verdict"] for r in rows)
        if not (summary["trials"] == len(rows) == 100):
            raise AssertionError()
        if not (summary["direct_disagreements"] == 0):
            raise AssertionError()
        return rows, verdicts, summary

    public, public_verdicts, public_summary = inspect("uipath-holdout")
    if not (public_verdicts == Counter({"pass": 90, "fail": 10})):
        raise AssertionError(public_verdicts)
    if not (public_summary["name_misses_with_ledger_fail"] == 10):
        raise AssertionError()
    early = [r for r in public if r["case"] == "async_generator_partial_close"]
    if not (len(early) == 10):
        raise AssertionError()
    if not (all(r["ledger_check"]["verdict"] == "fail" for r in early)):
        raise AssertionError()
    if not (all({f["code"] for f in r["ledger_check"]["findings"]} == {"ENDS_BEFORE_EXIT"} for r in early)):
        raise AssertionError()
    if not (all(r["name_check"]["verdict"] == "pass" for r in early)):
        raise AssertionError()
    if not (all(r["ledger_check"]["verdict"] == "pass" for r in public if r["case"] != "async_generator_partial_close")):
        raise AssertionError()

    corrected, corrected_verdicts, corrected_summary = inspect("uipath-local-correction")
    if not (corrected_verdicts == Counter({"pass": 97, "inconclusive": 3})):
        raise AssertionError(corrected_verdicts)
    if not (corrected_summary["name_misses_with_ledger_fail"] == 0):
        raise AssertionError()
    corrected_early = [r for r in corrected if r["case"] == "async_generator_partial_close"]
    if not (len(corrected_early) == 10):
        raise AssertionError()
    if not (all(r["ledger_check"]["verdict"] == "pass" for r in corrected_early)):
        raise AssertionError()
    patch = (ROOT / "provenance/uipath-local-correction.patch").read_text()
    if not ("await inner_generator.aclose()" in patch):
        raise AssertionError()

    return {
        "source_blob": info["git_blob"],
        "public_trials": len(public),
        "public_verdicts": dict(public_verdicts),
        "public_early_close_failures": len(early),
        "local_correction_trials": len(corrected),
        "local_correction_verdicts": dict(corrected_verdicts),
        "corrected_early_close_passes": len(corrected_early),
    }


def check_native_mutation_matrix() -> dict:
    summary = load_json(ROOT / "results/native-mutation-matrix/summary.json")
    if not (summary["fresh_process_methods"] == 90):
        raise AssertionError()
    if not (summary["infrastructure_errors"] == 0):
        raise AssertionError()
    if not (summary["by_suite"]["legacy"]["detected_perturbations"] == 2):
        raise AssertionError()
    if not (summary["by_suite"]["updated"]["detected_perturbations"] == 7):
        raise AssertionError()
    expected_updated_misses = {"queue_inclusive", "wrong_parent", "empty_context_execution"}
    updated = summary["by_suite"]["updated"]["matrix"]
    if not ({k for k, v in updated.items() if not v["detected"]} == expected_updated_misses):
        raise AssertionError()
    legacy = summary["by_suite"]["legacy"]["matrix"]
    if not ({k for k, v in legacy.items() if v["detected"]} == {"no_span", "duplicate_span"}):
        raise AssertionError()
    raw = [p for p in (ROOT / "results/native-mutation-matrix").glob("*.json") if p.name not in {"summary.json", "rows.json"}]
    if not (len(raw) == 90):
        raise AssertionError(len(raw))
    rows = load_json(ROOT / "results/native-mutation-matrix/rows.json")
    if not (len(rows) == 90):
        raise AssertionError()
    if not (all(r["tests_run"] == 1 and not r["errors"] for r in rows)):
        raise AssertionError()
    return {
        "fresh_process_methods": 90,
        "legacy_detected_operators": 2,
        "updated_detected_operators": 7,
        "updated_missed_operators": sorted(expected_updated_misses),
    }



def _topology_archive_checkers() -> tuple:
    """Load only the three pinned, pure topology-era modules, not live code.

    The namespace has no package initializer or search path. Verify all source
    hashes before executing any module; relative imports resolve only to the
    explicitly loaded frozen contracts. These checkers are archival, never the
    authority for current acceptance.
    """
    hashes = load_json(ROOT / "provenance/core-freeze.json")["topology_amendment"]["sha256"]
    paths = {name: ROOT / f"provenance/evaluated-core/src/spanlife/{name}.py"
             for name in ("contracts", "oracle", "baselines")}
    sources = {name: path.read_bytes() for name, path in paths.items()}
    for name, path in paths.items():
        if not (hashlib.sha256(sources[name]).hexdigest() == hashes[path.relative_to(ROOT).as_posix()]):
            raise AssertionError(f"archival topology source changed: {path}")
    namespace = "_spanlife_topology_archive"
    package = types.ModuleType(namespace)
    package.__path__ = []
    sys.modules[namespace] = package
    modules = {}
    try:
        for name, path in paths.items():
            module = types.ModuleType(f"{namespace}.{name}")
            module.__file__ = str(path)
            module.__package__ = namespace
            sys.modules[module.__name__] = module
            # Execute the exact verified source bytes, not a cached .pyc or
            # a second loader read of potentially different source.
            exec(compile(sources[name], str(path), "exec"), module.__dict__)
            modules[name] = module
        return (modules["oracle"].qualify, modules["baselines"].direct_assertions,
                modules["baselines"].existence_and_name)
    finally:
        for name in paths:
            sys.modules.pop(f"{namespace}.{name}", None)
        sys.modules.pop(namespace, None)


def _check_current_topology_acceptance(run: dict, current: dict, direct: dict) -> None:
    """Require current outcomes AND segment aggregation, not historical PASS."""
    verdict, expected_codes = EXPECTED[run["case"]]
    if not (run["expected"] == {"verdict": verdict, "codes": list(expected_codes)}):
        raise AssertionError(run["case"])
    if not (current["verdict"] == direct["verdict"] == verdict):
        raise AssertionError(run["case"])
    codes = {finding["code"] for finding in current["findings"]}
    if not (set(expected_codes).issubset(codes)):
        raise AssertionError((run["case"], expected_codes, codes))
    if verdict == "pass":
        if not (not current["findings"]):
            raise AssertionError(run["case"])
    if not ([op["operation_id"] for op in current["operations"]] == [
        policy["operation_id"] for policy in run["policies"]]):
        raise AssertionError(run["case"])

    def aggregate(findings: list[dict], complete: bool = True) -> str:
        return ("fail" if any(row["verdict"] == "fail" for row in findings) else
                "inconclusive" if findings or not complete else "pass")

    for policy, operation in zip(run["policies"], current["operations"]):
        oid = policy["operation_id"]
        local = [row for row in current["findings"] if row["operation_id"] == oid]
        enter = [row for row in run["ledger"] if row["operation_id"] == oid and row["kind"] == "enter"]
        exit_events = [row for row in run["ledger"] if row["operation_id"] == oid and row["kind"] == "exit"]
        complete = (len(enter) == len(exit_events) == 1
                    and exit_events[0]["monotonic_ns"] >= enter[0]["monotonic_ns"])
        segments = [{"segment_id": segment["segment_id"],
                     "verdict": aggregate([row for row in local
                                           if row.get("segment_id") == segment["segment_id"]], complete)}
                    for segment in policy["segments"]]
        if not (operation["segments"] == segments):
            raise AssertionError((run["case"], operation, segments))
        if not (operation["verdict"] == aggregate(local)):
            raise AssertionError((run["case"], operation))
    if not (current["verdict"] == aggregate(current["findings"])):
        raise AssertionError(run["case"])


def check_topology_challenge() -> dict:
    """Exact archival replay plus bounded current reanalysis of the same traces."""
    directory = ROOT / "results/topology-challenge"
    manifest = load_json(directory / "execution-manifest.json")
    if not (manifest["trials"] == 12):
        raise AssertionError()
    if not (not manifest["failures"]):
        raise AssertionError()
    rows = load_json(directory / "trials.json")
    summary = load_json(directory / "summary.json")
    if not (len(rows) == summary["fresh_process_trials"] == 12):
        raise AssertionError()
    if not (summary["cases"] == 12):
        raise AssertionError()
    if not (summary["operation_contracts"] == 20):
        raise AssertionError()
    if not (summary["segment_contracts"] == 28):
        raise AssertionError()
    if not (summary["exact_expected_verdicts"] == 12):
        raise AssertionError()
    if not (summary["expected_diagnostics_present"] == 12):
        raise AssertionError()
    if not (summary["direct_disagreements"] == 0):
        raise AssertionError()
    if not (summary["name_false_alarms_on_valid_correlation"] == 1):
        raise AssertionError()
    if not (summary["relation_faults_missed_by_name"] == 2):
        raise AssertionError()
    if not (summary["name_disagreements"] == 6):
        raise AssertionError()
    archive_qualify, archive_direct, archive_name = _topology_archive_checkers()
    paths = {path.name: path for path in directory.glob("*.json")
             if path.name not in {"summary.json", "trials.json", "execution-manifest.json"}}
    expected_names = {f"{case}__000.json" for case in TOPOLOGY_CASES}
    if not (set(paths) == expected_names):
        raise AssertionError((set(paths), expected_names))
    process_keys = [(row["case"], row["repeat"]) for row in manifest["processes"]]
    if not (process_keys == [(case, 0) for case in TOPOLOGY_CASES]):
        raise AssertionError(process_keys)
    if not (all(row["returncode"] == 0 for row in manifest["processes"])):
        raise AssertionError(manifest)
    archive_rows, current_rows, changed_checks = [], [], []
    for case in TOPOLOGY_CASES:
        path = paths[f"{case}__000.json"]
        run = load_json(path)
        if not ((run["case"], run["repeat"]) == (case, 0)):
            raise AssertionError(path)
        if not (run["execution"]["status"] == "completed"):
            raise AssertionError(path)
        if not (archive_qualify(run) == run["ledger_check"]):
            raise AssertionError(f"archival ledger mismatch: {path}")
        if not (archive_direct(run) == run["direct_check"]):
            raise AssertionError(f"archival direct mismatch: {path}")
        if not (archive_name(run) == run["name_check"]):
            raise AssertionError(f"archival name mismatch: {path}")
        current = {**run, "ledger_check": qualify(run),
                   "direct_check": direct_assertions(run), "name_check": existence_and_name(run)}
        _check_current_topology_acceptance(run, current["ledger_check"], current["direct_check"])
        # Exactly two known source-segment summaries changed. Compare the
        # entire expected structure; no generic ignored keys or fallback to
        # the old evaluator is permitted for current evidence.
        expected_current = deepcopy(run["ledger_check"])
        if case in {"split_missing_relation", "split_wrong_relation"}:
            source = expected_current["operations"][0]["segments"][1]
            if not (source == {"segment_id": "execute", "verdict": "pass"}):
                raise AssertionError(path)
            source["verdict"] = "fail"
            changed_checks.append({"case": case, "operation_id": "op-0",
                                   "segment_id": "execute", "archival": "pass", "current": "fail"})
        if not (current["ledger_check"] == expected_current):
            raise AssertionError(f"unexpected current ledger change: {path}")
        if not (current["direct_check"] == run["direct_check"]):
            raise AssertionError(f"current direct mismatch: {path}")
        if not (current["name_check"] == run["name_check"]):
            raise AssertionError(f"current name mismatch: {path}")
        raw = path.relative_to(ROOT).as_posix()
        archive_rows.append(trial_row(run, raw))
        current_rows.append(trial_row(current, raw))
    if not (rows == archive_rows):
        raise AssertionError("archival topology trials do not match raw records")
    archive_summary = summarize_rows(archive_rows, len(manifest["failures"]))
    if not (summary == {**archive_summary, "wall_s": manifest["wall_s"]}):
        raise AssertionError("archival topology summary mismatch")
    # No new measurements or wall times: derived current outputs are kept
    # only in memory and checked separately against this bounded challenge.
    if not (current_rows == archive_rows):
        raise AssertionError("current topology rollup changed")
    current_summary = summarize_rows(current_rows, 0)
    if not (current_summary == archive_summary):
        raise AssertionError("current topology summary changed")
    return {
        "fresh_process_trials": 12,
        "operation_contracts": 20,
        "segment_contracts": 28,
        "exact_expected_verdicts": 12,
        "direct_disagreements": 0,
        "name_disagreements": summary["name_disagreements"],
        "archival_replay": {"source_generation": "provenance/evaluated-core/src/spanlife",
                            "exact_record_checks": len(archive_rows),
                            "trials_and_summary_match_generator": True},
        "current_reanalysis": {"source_generation": "src/spanlife",
                               "retained_observations": len(current_rows),
                               "new_runtime_trials": 0,
                               "exact_expected_verdicts": current_summary["exact_expected_verdicts"],
                               "expected_diagnostics_present": current_summary["expected_diagnostics_present"],
                               "direct_disagreements": current_summary["direct_disagreements"],
                               "derived_rows_and_summary_unchanged": True,
                               "changed_record_checks": changed_checks},
    }

def check_gate_ablation() -> dict:
    rows = load_json(ROOT / "results/gate-ablation/rows.json")
    summary = load_json(ROOT / "results/gate-ablation/summary.json")
    if not (len(rows) == summary["derived_judgments"] == 120):
        raise AssertionError()
    if not (summary["gates"] == 6):
        raise AssertionError()
    if not (summary["unsupported_definitive_actions"] == 120):
        raise AssertionError()
    if not (summary["unsupported_passes"] == 80):
        raise AssertionError()
    if not (summary["unsupported_failures"] == 40):
        raise AssertionError()
    if not (all(r["reference"] == "inconclusive" for r in rows)):
        raise AssertionError()
    return {
        "derived_judgments": 120,
        "unsupported_passes": 80,
        "unsupported_failures": 40,
    }

def check_release_lineage() -> dict:
    base = ROOT / "provenance/release-lineage"
    data = load_json(base / "opentelemetry-asyncio-releases.json")
    if not ([r["version"] for r in data["releases"]] == ["0.44b0", "0.65b0", "0.66b0"]):
        raise AssertionError()
    if not ([r["classification"] for r in data["releases"]] == ["affected", "affected", "fixed"]):
        raise AssertionError()
    for release in data["releases"]:
        if not (re.fullmatch(r"[0-9a-f]{40}", release["tag_commit"])):
            raise AssertionError()
        if not (re.fullmatch(r"[0-9a-f]{40}", release["source_blob"])):
            raise AssertionError()
        if not (re.fullmatch(r"[0-9a-f]{64}", release["wheel_sha256"])):
            raise AssertionError()
    if not ("return func" in (base / "v0.44b0-trace_to_thread.py.txt").read_text()):
        raise AssertionError()
    if not ("return func" in (base / "v0.65b0-trace_to_thread.py.txt").read_text()):
        raise AssertionError()
    fixed = (base / "v0.66b0-wrap_to_thread_func.py.txt").read_text()
    if not ("@functools.wraps(func)" in fixed and "func(*args, **kwargs)" in fixed):
        raise AssertionError()
    return {
        "versions": [r["version"] for r in data["releases"]],
        "classifications": [r["classification"] for r in data["releases"]],
        "wheel_hashes_recorded": len(data["releases"]),
    }


def check_counterfactuals() -> dict:
    with (ROOT / "results/policy-counterfactual/evaluations.csv").open(newline="") as f:
        evaluations = list(csv.DictReader(f))
    with (ROOT / "results/policy-counterfactual/matrix.csv").open(newline="") as f:
        matrix = list(csv.DictReader(f))
    summary = load_json(ROOT / "results/policy-counterfactual/summary.json")
    if not (len(evaluations) == 300):
        raise AssertionError()
    if not (len(matrix) == 15):
        raise AssertionError()
    if not (summary["source_observations"] == 60):
        raise AssertionError()
    if not (summary["policy_evaluations"] == len(evaluations)):
        raise AssertionError()
    grouped: dict[tuple[str, str], Counter] = {}
    for row in evaluations:
        grouped.setdefault((row["observation"], row["declared_role"]), Counter())[row["verdict"]] += 1
    for row in matrix:
        counts = grouped[(row["observation"], row["declared_role"])]
        for verdict in ("pass", "fail", "inconclusive"):
            if not (counts[verdict] == int(row[verdict])):
                raise AssertionError((row, counts))
    return {"source_observations": 60, "policy_evaluations": len(evaluations)}


def check_costs() -> int:
    load_cost_records(ROOT / "results/costs")
    return len(load_cost_records(ROOT / "results/costs-local"))


def check_references() -> dict:
    bib_text = (PROJECT / "paper/references.bib").read_text()
    bib_keys = set(re.findall(r"^@[A-Za-z]+\{([^,]+),", bib_text, flags=re.M))
    tex = (PROJECT / "paper/main.tex").read_text()
    cite_keys: set[str] = set()
    for match in re.finditer(r"\\cite\{([^}]+)\}", tex):
        cite_keys.update(k.strip() for k in match.group(1).split(",") if k.strip())
    missing = cite_keys - bib_keys
    uncited = bib_keys - cite_keys
    if not (not missing):
        raise AssertionError(f"missing BibTeX keys: {sorted(missing)}")
    if not (not uncited):
        raise AssertionError(f"uncited BibTeX keys: {sorted(uncited)}")
    audit = load_json(ROOT / "provenance/reference-audit.json")
    records = audit["records"]
    audit_keys = {r["bib_key"] for r in records}
    if not (audit["reference_count"] == len(records) == len(bib_keys)):
        raise AssertionError()
    if not (len(bib_keys) >= 60):
        raise AssertionError(len(bib_keys))
    if not (audit_keys == bib_keys):
        raise AssertionError((audit_keys - bib_keys, bib_keys - audit_keys))
    if not (all(r.get("verified_on") and r.get("source_url") and r.get("checked_fields") for r in records)):
        raise AssertionError()
    return {"bibliography_entries": len(bib_keys), "all_entries_cited": True}


def main() -> None:
    upstream = load_json(ROOT / "provenance/upstream-files.json")
    verified_upstream = []
    for path, expected in upstream.items():
        if not (git_blob((ROOT / path).read_bytes()) == expected):
            raise AssertionError(f"upstream blob mismatch: {path}")
        verified_upstream.append(path)

    frozen = load_json(ROOT / "provenance/core-freeze.json")
    original_hashes = frozen["original_freeze"]["sha256"]
    amendment_hashes = frozen["topology_amendment"]["sha256"]
    for path, expected in original_hashes.items():
        if not (hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected):
            raise AssertionError(f"original frozen snapshot changed: {path}")
    for path, expected in amendment_hashes.items():
        if not (hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected):
            raise AssertionError(f"amended core changed: {path}")

    principal, failed = check_principal()
    result = {
        "schema": 6,
        "verified_upstream_files": len(verified_upstream),
        "original_frozen_core_files": len(original_hashes),
        "amended_core_files": len(amendment_hashes),
        "principal_completed_trials": principal,
        "retained_failed_attempts": failed,
        "speaches_holdout": check_speaches(),
        "uipath_holdout_and_correction": check_uipath(),
        "independent_replay": check_replay(),
        "executable_perturbations": check_executable_perturbations(),
        "native_mutation_matrix": check_native_mutation_matrix(),
        "topology_challenge": check_topology_challenge(),
        "gate_ablation": check_gate_ablation(),
        "release_lineage": check_release_lineage(),
        "mutation_challenge": check_mutations(),
        "policy_counterfactual": check_counterfactuals(),
        "cost_samples": check_costs(),
        "references": check_references(),
    }
    out = ROOT / "results/integrity-check.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
