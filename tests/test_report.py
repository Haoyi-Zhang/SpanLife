from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from spanlife.baselines import direct_assertions, existence_and_name
from spanlife.oracle import qualify
from spanlife.report import build_ci_report, format_text
from spanlife.topology_scenarios import run_topology_case


ROOT = Path(__file__).resolve().parents[1]


def cli_env() -> dict[str, str]:
    env = os.environ.copy()
    roots = [str(ROOT / "src"), str(ROOT / "vendor")]
    prior = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(roots + ([prior] if prior else []))
    return env


def qualified(case: str, repeat: int = 0) -> dict:
    run = run_topology_case(case, repeat=repeat)
    run["clock"] = {**run["clock"], "epsilon_ns": 100_000, "timing_eligible": True}
    run["ledger_check"] = qualify(run)
    run["direct_check"] = direct_assertions(run)
    run["name_check"] = existence_and_name(run)
    return run


def test_ci_report_routes_relation_failure_to_propagation() -> None:
    run = qualified("split_missing_relation")
    report = build_ci_report(run)
    assert report["verdict"] == "fail"
    finding = next(row for row in report["findings"] if row["code"] == "MISSING_HANDOFF_RELATION")
    assert finding["owner"] == "propagation"
    assert "parent or link" in finding["action"]
    assert report["record_consistent"] is True
    assert report["ci_exit_code"] == 1


def test_ci_report_preserves_inconclusive_as_separate_exit_class() -> None:
    run = qualified("correlated_duplicate_attribute")
    report = build_ci_report(run)
    assert report["verdict"] == "inconclusive"
    assert report["ci_exit_code"] == 2
    assert report["owners"] == {"instrumentation": 1}


def test_text_report_is_actionable_and_compact() -> None:
    report = build_ci_report(qualified("split_execution_early_end"))
    text = format_text(report)
    assert "SpanLife FAIL" in text
    assert "ENDS_BEFORE_EXIT" in text
    assert "keep the span open" in text


def test_check_record_cli_json_and_exit_codes(tmp_path: Path) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps(qualified("split_link_valid")))
    proc = subprocess.run(
        [sys.executable, "-m", "spanlife.check_record", str(record), "--format", "json"],
        text=True,
        capture_output=True,
        check=False,
        env=cli_env(),
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["verdict"] == "pass"


def test_check_record_cli_can_gate_inconclusive(tmp_path: Path) -> None:
    record = tmp_path / "record.json"
    record.write_text(json.dumps(qualified("correlated_duplicate_attribute")))
    proc = subprocess.run(
        [sys.executable, "-m", "spanlife.check_record", str(record), "--fail-on-inconclusive"],
        text=True,
        capture_output=True,
        check=False,
        env=cli_env(),
    )
    assert proc.returncode == 2
    assert "INCONCLUSIVE" in proc.stdout
