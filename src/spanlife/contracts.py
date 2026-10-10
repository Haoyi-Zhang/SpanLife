"""Contract normalization for single-span and multi-span lifetime policies.

The public JSON format deliberately stays small and reviewable.  Existing
single-span records remain valid; newer records may declare several named
segments plus handoff relations.  This module performs shape validation only.
It does not evaluate telemetry and is safe to share with independent checkers.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

ALLOWED_ROLES = {"execution", "submission", "both", "context-only", "unknown"}
ALLOWED_RELATIONS = {"link", "parent", "parent-or-link", "same-trace"}


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
    for policy in policies:
        normalize_policy(policy)
    for field in ("ledger", "spans"):
        rows = run.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"run.{field} must be a list of objects")
    if "contexts" in run and not isinstance(run["contexts"], dict):
        raise ValueError("run.contexts must be an object")
    clock = run.get("clock")
    if not isinstance(clock, dict):
        raise ValueError("run.clock must be an object")
    epsilon = clock.get("epsilon_ns")
    if type(epsilon) is not int or epsilon < 0:
        raise ValueError("clock.epsilon_ns must be a non-negative integer")
    if not isinstance(clock.get("timing_eligible"), bool):
        raise ValueError("clock.timing_eligible must be a boolean")
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
        segment_id = str(segment.get("segment_id", f"segment-{index}"))
        if segment_id in seen:
            raise ValueError(f"duplicate segment_id: {segment_id}")
        seen.add(segment_id)
        segment["segment_id"] = segment_id
        role = segment.get("role", "unknown")
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            raise ValueError(f"unsupported segment role: {role}")
        segment["role"] = role
        segment.setdefault("span_name", "")
        if "span_ids" in segment and not isinstance(segment["span_ids"], list):
            raise ValueError("segment.span_ids must be a list")
        association = segment.get("association")
        if association is not None:
            if not isinstance(association, dict):
                raise ValueError("segment.association must be an object")
            kind = association.get("kind")
            if kind not in {"attributes", "name"}:
                raise ValueError(f"unsupported association kind: {kind}")
            if kind == "attributes":
                match = association.get("match")
                if not isinstance(match, dict) or not match:
                    raise ValueError("attributes association requires non-empty match")
        normalized.append(segment)
    result["segments"] = normalized

    relations = result.get("relations", [])
    if not isinstance(relations, list):
        raise ValueError("policy.relations must be a list")
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("each relation must be an object")
        if relation.get("kind") not in ALLOWED_RELATIONS:
            raise ValueError(f"unsupported relation kind: {relation.get('kind')}")
        if relation.get("from") not in seen or relation.get("to") not in seen:
            raise ValueError("relation endpoints must name declared segments")
    return result


def iter_segments(policy: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return normalize_policy(policy)["segments"]
