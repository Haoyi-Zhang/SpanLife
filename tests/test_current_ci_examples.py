"""SDK-free CI inputs derived from retained observations, not fresh executions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from spanlife.oracle import qualify
from spanlife.report import build_ci_report

ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts/reanalyze_record.py"
EXAMPLES = ROOT / "results/ci-examples/current-raw"
CASES = (
    ("pass", "split_link_valid", 0, []),
    ("fail", "split_missing_relation", 1, ["MISSING_HANDOFF_RELATION"]),
    ("inconclusive", "correlated_duplicate_attribute", 2, ["AMBIGUOUS_ASSOCIATION"]),
)


def cli(*args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # No site packages: neither the producer nor checker needs a tracing SDK.
    return subprocess.run([sys.executable, "-B", "-S", *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=10, check=False)


@pytest.mark.parametrize("label,case,exit_code,codes", CASES)
def test_shipped_inputs_reproduce_without_changing_recorded_fields(label, case, exit_code, codes):
    source = ROOT / f"results/topology-challenge/{case}__000.json"
    before = source.read_bytes()
    original = json.loads(before)
    derived = runpy.run_path(str(PRODUCER))["reanalyze_record"](source)
    shipped = json.loads((EXAMPLES / f"{label}.json").read_text(encoding="utf-8"))
    assert shipped == derived
    assert set(shipped) == set(original) | {"reanalysis"}
    assert {key: value for key, value in shipped.items()
            if key not in {"ledger_check", "reanalysis"}} == {
                key: value for key, value in original.items() if key != "ledger_check"}
    assert shipped["reanalysis"] == {
        "kind": "current reanalysis of recorded observations",
        "source_record": source.relative_to(ROOT).as_posix(),
        "updated_fields": ["ledger_check"],
        "new_runtime_trials": 0,
    }
    assert shipped["ledger_check"] == qualify(original)
    assert shipped["ledger_check"]["verdict"] == original["ledger_check"]["verdict"] == label
    assert [row["code"] for row in shipped["ledger_check"]["findings"]] == codes
    assert source.read_bytes() == before


@pytest.mark.parametrize("label,case,exit_code,codes", CASES)
def test_real_cli_accepts_current_raw_inputs(label, case, exit_code, codes):
    proc = cli("-m", "spanlife.check_record", EXAMPLES / f"{label}.json",
               "--format", "json", "--fail-on-inconclusive")
    assert proc.returncode == exit_code, proc.stderr
    report = json.loads(proc.stdout)
    assert report["verdict"] == label
    assert report["record_consistent"] is True
    assert report["ci_exit_code"] == exit_code
    assert [row["code"] for row in report["findings"]] == codes


@pytest.mark.parametrize("label,case,exit_code,codes", CASES)
def test_producer_cli_writes_exact_current_input_without_site_packages(tmp_path, label, case, exit_code, codes):
    target = tmp_path / f"{label}.json"
    proc = cli(PRODUCER, ROOT / f"results/topology-challenge/{case}__000.json",
               "--output", target)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == label
    assert target.read_bytes() == (EXAMPLES / f"{label}.json").read_bytes()


def test_missing_handoff_remains_failure_and_original_remains_mismatch():
    source = ROOT / "results/topology-challenge/split_missing_relation__000.json"
    before = source.read_bytes()
    original = json.loads(before)
    current = json.loads((EXAMPLES / "fail.json").read_text(encoding="utf-8"))
    assert original["ledger_check"]["operations"][0]["segments"][1]["verdict"] == "pass"
    assert current["ledger_check"]["operations"][0]["segments"][1] == {
        "segment_id": "execute", "verdict": "fail"}
    assert current["ledger_check"]["findings"] == original["ledger_check"]["findings"]
    assert build_ci_report(original)["ci_exit_code"] == 3
    assert build_ci_report(current)["ci_exit_code"] == 1
    proc = cli("-m", "spanlife.check_record", source)
    assert proc.returncode == 3, proc.stderr
    assert "RECORD_MISMATCH" in proc.stdout
    assert "MISSING_HANDOFF_RELATION" in proc.stdout
    assert source.read_bytes() == before


def test_current_example_tampering_is_not_excused_by_reanalysis_metadata(tmp_path):
    run = json.loads((EXAMPLES / "fail.json").read_text(encoding="utf-8"))
    run["ledger_check"] = {"verdict": "pass"}
    target = tmp_path / "inconsistent.json"
    target.write_text(json.dumps(run), encoding="utf-8")
    proc = cli("-m", "spanlife.check_record", target, "--format", "json")
    assert proc.returncode == 3, proc.stderr
    report = json.loads(proc.stdout)
    assert report["record_consistent"] is False
    assert report["verdict"] == "fail"
    assert report["findings"][0]["code"] == "MISSING_HANDOFF_RELATION"


def test_inconclusive_is_optional_cli_gate():
    proc = cli("-m", "spanlife.check_record", EXAMPLES / "inconclusive.json", "--format", "json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ci_exit_code"] == 2


def test_producer_never_overwrites_source_or_existing_output(tmp_path):
    source = tmp_path / "source.json"
    source.write_bytes((ROOT / "results/topology-challenge/split_missing_relation__000.json").read_bytes())
    target = tmp_path / "existing.json"
    target.write_text("existing output\n", encoding="utf-8")
    for output in (source, target):
        before = output.read_bytes()
        proc = cli(PRODUCER, source, "--output", output)
        assert proc.returncode == 2
        assert output.read_bytes() == before


@pytest.mark.parametrize("relative", ["results/ci-examples/pass.json",
                                    "results/ci-examples/current-raw/fail.json"])
def test_producer_requires_original_raw_observations(tmp_path, relative):
    target = tmp_path / "new.json"
    proc = cli(PRODUCER, ROOT / relative, "--output", target)
    assert proc.returncode == 2
    assert not target.exists()
    assert "Traceback" not in proc.stderr
