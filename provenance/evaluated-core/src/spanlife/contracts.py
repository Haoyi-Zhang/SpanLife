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


def normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Return a validated policy with an explicit ``segments`` list.

    Legacy records describe one segment at policy level.  New records place
    segment-specific association and lifetime obligations in ``segments`` and
    may add ``relations`` between them.  Unknown keys are preserved so raw
    evidence remains forwards compatible.
    """
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
        if role not in ALLOWED_ROLES:
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
