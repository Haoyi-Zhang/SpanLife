"""Ordinary baselines. The direct baseline does not call the ledger checker.

Both it and the checker see the same events and intent. A tie is expected:
there is no claimed information-theoretic advantage over correctly written
application assertions. This is NOT a Tracetest reimplementation.
"""
from __future__ import annotations


def existence_and_name(run: dict) -> dict:
    if not run.get("drained"):
        return {"verdict": "inconclusive", "reason": "collection pending"}
    spans = {str(s["span_id"]): s for s in run["spans"]}
    failures = []
    for p in run["policies"]:
        if p["role"] == "unknown":
            return {"verdict": "inconclusive", "reason": "undeclared intent"}
        if p["role"] == "context-only":
            continue
        selected = [spans[str(i)] for i in p.get("span_ids", []) if str(i) in spans]
        if len(selected) != 1 or selected[0]["name"] != p["span_name"]:
            failures.append(p["operation_id"])
    return {"verdict": "fail" if failures else "pass", "failures": failures}


def direct_assertions(run: dict) -> dict:
    """Straight-line explicit assertions, applied per declared operation."""
    spans = {str(s["span_id"]): s for s in run["spans"]}
    failed, uncertain = [], []
    eps = run["clock"]["epsilon_ns"]
    for p in run["policies"]:
        oid = p["operation_id"]
        ev = [e for e in run["ledger"] if e["operation_id"] == oid]
        lookup = {k: [e for e in ev if e["kind"] == k]
                  for k in ("enter", "exit", "submit_enter", "submit_exit", "queue_release")}
        if p["role"] == "unknown" or len(lookup["enter"]) != 1 or len(lookup["exit"]) != 1:
            uncertain.append(oid); continue
        a, b = lookup["enter"][0], lookup["exit"][0]
        if b["monotonic_ns"] < a["monotonic_ns"]:
            uncertain.append(oid)
        if "expected_context" in p:
            if oid not in run.get("contexts", {}):
                uncertain.append(oid)
            elif run["contexts"][oid] != p["expected_context"]:
                failed.append(oid)
        if p["role"] == "context-only":
            continue
        ids = p.get("span_ids", [])
        chosen = [spans[str(i)] for i in ids if str(i) in spans]
        if len(ids) > 1:
            uncertain.append(oid); continue
        if not chosen:
            if not run.get("drained") or not run.get("always_on") or p.get("ended_witness"):
                uncertain.append(oid)
            else:
                failed.append(oid)
            continue
        s = chosen[0]
        checks = []
        if run["clock"]["timing_eligible"]:
            if p["role"] in ("execution", "both"):
                checks.extend([s["start_ns"] <= a["wall_ns"] + eps,
                               s["end_ns"] >= b["wall_ns"] - eps])
            if p["role"] in ("submission", "both"):
                if len(lookup["submit_enter"]) != 1 or len(lookup["submit_exit"]) != 1:
                    uncertain.append(oid)
                else:
                    checks.extend([s["start_ns"] <= lookup["submit_enter"][0]["wall_ns"] + eps,
                                   s["end_ns"] >= lookup["submit_exit"][0]["wall_ns"] - eps])
            if p["role"] == "execution" and p.get("exclude_queue"):
                if len(lookup["queue_release"]) != 1:
                    uncertain.append(oid)
                else:
                    checks.append(s["start_ns"] >= lookup["queue_release"][0]["wall_ns"] - eps)
        else:
            uncertain.append(oid)
        if (p["role"] in ("execution", "both") and p.get("error_on_escape")
                and b["outcome"] == "raised" and b["exception_type"] not in p.get("non_error_types", [])):
            checks.append(s["status"] == "ERROR")
            if p.get("exception_event"):
                checks.append("exception" in s["events"])
        if "expected_parent" in p:
            checks.append(s["parent_id"] == p["expected_parent"])
        if not all(checks):
            failed.append(oid)
    return {"verdict": "fail" if failed else "inconclusive" if uncertain else "pass",
            "failures": sorted(set(failed)), "inconclusive": sorted(set(uncertain))}
