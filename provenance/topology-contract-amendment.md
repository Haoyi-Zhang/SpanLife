# Topology contract amendment

The principal 800-process matrix and its independent 800-process replay used the
single-span checker frozen on 2026-09-30.  The exact frozen source is retained in
`provenance/frozen-core/` and its hashes remain in `core-freeze.json`.

After those results were retained, the checker was extended without changing the
legacy record path.  The amendment adds:

* a topology contract with named submission, execution, combined, context-only,
  or unknown segments;
* deterministic span association by explicit span identifier or declared
  attributes, never by timing overlap;
* parent, link, parent-or-link, and same-trace handoff relations;
* per-segment findings and operation-level tri-state aggregation; and
* a CI report that maps evidence families to the next responsible engineering
  layer while retaining the raw finding.

The extension was evaluated in 12 isolated processes containing 20 operation
contracts and 28 segment contracts.  The challenge includes valid split parent
and link topologies, missing and misdirected handoffs, segment-boundary faults,
missing segments, and concurrent same-name operations with valid, absent,
duplicate, or swapped correlation attributes.  Expected verdicts and diagnostic
families were fixed in `src/spanlife/topology_scenarios.py` before execution.

The offline verifier recomputes every legacy and topology record.  It also
verifies both the immutable original snapshots and the amended checker hashes.
This separation prevents the new capability from being represented as part of
the pre-evaluation freeze.
