"""Contract normalization for single-span and multi-span lifetime policies.

The public JSON format deliberately stays small and reviewable.  Existing
single-span records remain valid; newer records may declare several named
segments plus handoff relations. This module validates admission shapes and
provides a pure boundary-order helper; it does not assign telemetry verdicts.
Independent checkers may share admission without sharing predicate logic.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Iterable

ALLOWED_ROLES = {"execution", "submission", "both", "context-only", "unknown"}
ALLOWED_RELATIONS = {"link", "parent", "parent-or-link", "same-trace"}


def _identity(value: Any, field: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not ((isinstance(value, str) and value) or type(value) is int):
        raise ValueError(f"{field} must be a non-empty string or integer")


def _timestamp(value: Any, field: str) -> None:
    # JSON null or an omitted observation is unknown; malformed numbers are
    # rejected, not silently compared (NaN defeats both inequality directions).
    if value is not None and type(value) is not int:
        raise ValueError(f"{field} must be integer nanoseconds or null")


def _attribute(value: Any) -> bool:
    if isinstance(value, (str, bool)) or type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return isinstance(value, list) and all(_attribute(item) for item in value)


def ordered_bounds(first: dict[str, Any], last: dict[str, Any]) -> bool:
    """Both recorded clocks must have complete, nondecreasing boundaries."""
    return all(type(first.get(key)) is int and type(last.get(key)) is int
               and first[key] <= last[key] for key in ("wall_ns", "monotonic_ns"))


def is_legacy_policy(policy: dict[str, Any]) -> bool:
    """Keep the old evaluator only for the original, explicitly declared shape.

    Amended flat policies have the same semantics as one explicit segment,
    including when an added obligation is present but disabled.  An omitted
    role must use normalization's ``unknown`` default rather than the legacy
    evaluator's required role lookup.
    """
    amended_fields = {"association", "exclude_submission", "must_end_before_operation_entry"}
    return ("role" in policy and "segments" not in policy
            and not policy.get("relations") and not amended_fields.intersection(policy))


def validate_run(run: dict[str, Any]) -> None:
    """Admit a nonempty contract and basic evidence containers before dispatch.

    Empty observations remain legitimate evidence of an incomplete operation
    or missing span.  Empty contracts are not a successful qualification.
    Detailed evidence prerequisites remain the evaluators' responsibility:
    context-only policies without an expected identity abstain, and an absent
    end-witness observation is not an observed zero.
    """
    if not isinstance(run, dict):
        raise ValueError("run must be an object")
    policies = run.get("policies")
    if not isinstance(policies, list) or not policies:
        raise ValueError("run.policies must be a non-empty list")
    seen_operations = set()
    for policy in policies:
        normalize_policy(policy)
        if policy["operation_id"] in seen_operations:
            raise ValueError("duplicate policy.operation_id")
        seen_operations.add(policy["operation_id"])
    for field in ("ledger", "spans"):
        rows = run.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"run.{field} must be a list of objects")
    if "contexts" in run and not isinstance(run["contexts"], dict):
        raise ValueError("run.contexts must be an object")
    for value in run.get("contexts", {}).values():
        if isinstance(value, dict):
            for observed in value.values():
                _identity(observed, "context observation", optional=True)
        else:
            _identity(value, "context observation", optional=True)
    for row in run["ledger"]:
        if not isinstance(row.get("operation_id"), str) or not row["operation_id"]:
            raise ValueError("ledger.operation_id must be a non-empty string")
        if not isinstance(row.get("kind"), str) or not row["kind"]:
            raise ValueError("ledger.kind must be a non-empty string")
        for key in ("wall_ns", "monotonic_ns"):
            _timestamp(row.get(key), f"ledger.{key}")
        outcome = row.get("outcome")
        if outcome is not None and (not isinstance(outcome, str)
                                    or outcome not in {"returned", "raised", "unknown"}):
            raise ValueError("ledger.outcome must be returned, raised, unknown or null")
        exception = row.get("exception_type")
        if exception is not None and (not isinstance(exception, str) or not exception):
            raise ValueError("ledger.exception_type must be a non-empty string or null")
        if row["kind"] == "exit" and outcome == "returned" and exception is not None:
            raise ValueError("returned exit cannot carry an escaping exception type")
    for span in run["spans"]:
        _identity(span.get("span_id"), "span.span_id")
        if not isinstance(span.get("name"), str):
            raise ValueError("span.name must be a string")
        for key in ("start_ns", "end_ns"):
            _timestamp(span.get(key), f"span.{key}")
        for key in ("trace_id", "parent_id"):
            _identity(span.get(key), f"span.{key}", optional=True)
        status = span.get("status")
        if status is not None and (not isinstance(status, str)
                                   or status not in {"UNSET", "OK", "ERROR", "unknown"}):
            raise ValueError("span.status must be UNSET, OK, ERROR, unknown or null")
        events = span.get("events")
        if events is not None and (not isinstance(events, list)
                                   or any(not isinstance(event, str) for event in events)):
            raise ValueError("span.events must be a list of names or null")
        if "attributes" in span and not isinstance(span["attributes"], dict):
            raise ValueError("span.attributes must be an object")
        links = span.get("links")
        if links is not None:
            if not isinstance(links, list) or any(not isinstance(link, dict) for link in links):
                raise ValueError("span.links must be a list of objects or null")
            for link in links:
                for key in ("span_id", "trace_id"):
                    _identity(link.get(key), f"link.{key}", optional=True)
    clock = run.get("clock")
    if not isinstance(clock, dict):
        raise ValueError("run.clock must be an object")
    epsilon = clock.get("epsilon_ns")
    if type(epsilon) is not int or epsilon < 0:
        raise ValueError("clock.epsilon_ns must be a non-negative integer")
    if not isinstance(clock.get("timing_eligible"), bool):
        raise ValueError("clock.timing_eligible must be a boolean")
    if "cap_ns" in clock and (type(clock["cap_ns"]) is not int or clock["cap_ns"] < 0):
        raise ValueError("clock.cap_ns must be a non-negative integer")
    for field in ("drained", "always_on"):
        if field in run and not isinstance(run[field], bool):
            raise ValueError(f"run.{field} must be a boolean")


def normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Return a validated policy with an explicit ``segments`` list.

    Legacy records describe one segment at policy level.  New records place
segment-specific association and lifetime obligations in ``segments`` and
    may add ``relations`` between them.  Unknown keys are preserved so raw
    evidence remains forwards compatible.
    """
    if not isinstance(policy, dict):
        raise ValueError("each policy must be an object")
    if not isinstance(policy.get("operation_id"), str) or not policy["operation_id"]:
        raise ValueError("policy.operation_id must be a non-empty string")
    if "role" in policy and (not isinstance(policy["role"], str)
                             or policy["role"] not in ALLOWED_ROLES):
        raise ValueError(f"unsupported segment role: {policy['role']}")
    result = deepcopy(policy)
    if "segments" not in result:
        segment_keys = {
            "role", "span_name", "span_ids", "ended_witness", "association",
            "error_on_escape", "exception_event", "non_error_types",
            "expected_parent", "expected_context", "exclude_queue",
            "exclude_submission", "must_end_before_operation_entry",
        }
        segment = {key: deepcopy(result[key]) for key in segment_keys if key in result}
        segment.setdefault("segment_id", "primary")
        segment.setdefault("role", result.get("role", "unknown"))
        segment.setdefault("span_name", result.get("span_name", ""))
        result["segments"] = [segment]
    if not isinstance(result["segments"], list) or not result["segments"]:
        raise ValueError("policy.segments must be a non-empty list")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(result["segments"]):
        if not isinstance(raw, dict):
            raise ValueError("each segment must be an object")
        segment = deepcopy(raw)
        segment_id = segment.get("segment_id", f"segment-{index}")
        if not isinstance(segment_id, str) or not segment_id:
            raise ValueError("segment.segment_id must be a non-empty string")
        if segment_id in seen:
            raise ValueError(f"duplicate segment_id: {segment_id}")
        seen.add(segment_id)
        segment["segment_id"] = segment_id
        role = segment.get("role", "unknown")
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            raise ValueError(f"unsupported segment role: {role}")
        segment["role"] = role
        segment.setdefault("span_name", "")
        if not isinstance(segment["span_name"], str):
            raise ValueError("segment.span_name must be a string")
        if "span_ids" in segment and not isinstance(segment["span_ids"], list):
            raise ValueError("segment.span_ids must be a list")
        for value in segment.get("span_ids", []):
            _identity(value, "segment.span_ids entry")
        for key in ("error_on_escape", "exception_event", "exclude_queue",
                    "exclude_submission", "must_end_before_operation_entry"):
            if key in segment and not isinstance(segment[key], bool):
                raise ValueError(f"segment.{key} must be a boolean")
        non_error = segment.get("non_error_types", [])
        if not isinstance(non_error, list) or any(not isinstance(value, str) or not value
                                                 for value in non_error):
            raise ValueError("segment.non_error_types must be a list of exception names")
        for key in ("expected_parent", "expected_context"):
            _identity(segment.get(key), f"segment.{key}", optional=True)
        if ("ended_witness" in segment and segment["ended_witness"] is not None
                and type(segment["ended_witness"]) is not int):
            raise ValueError("segment.ended_witness must be an integer or null")
        association = segment.get("association")
        if association is not None:
            if not isinstance(association, dict):
                raise ValueError("segment.association must be an object")
            kind = association.get("kind")
            if not isinstance(kind, str) or kind not in {"attributes", "name"}:
                raise ValueError(f"unsupported association kind: {kind}")
            if kind == "attributes":
                match = association.get("match")
                if not isinstance(match, dict) or not match:
                    raise ValueError("attributes association requires non-empty match")
                if any(not isinstance(key, str) or not key or not _attribute(value)
                       for key, value in match.items()):
                    raise ValueError("attributes match requires named, non-null finite attribute values")
        normalized.append(segment)
    result["segments"] = normalized

    relations = result.get("relations", [])
    if not isinstance(relations, list):
        raise ValueError("policy.relations must be a list")
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("each relation must be an object")
        if not isinstance(relation.get("kind"), str) or relation["kind"] not in ALLOWED_RELATIONS:
            raise ValueError(f"unsupported relation kind: {relation.get('kind')}")
        if (not isinstance(relation.get("from"), str) or not isinstance(relation.get("to"), str)
                or relation["from"] not in seen or relation["to"] not in seen):
            raise ValueError("relation endpoints must name declared segments")
    return result


def iter_segments(policy: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return normalize_policy(policy)["segments"]
