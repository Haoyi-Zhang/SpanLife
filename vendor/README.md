# Source-level OpenTelemetry input

These are relevant upstream source files, not a complete installed wheel.
Fixed revision: e008b0e315b7d0a219c43e7ded1dc02e5abbeb69.
Affected immediate parent: f7788970bca275c99f65ba9c9e186b662f054c7e.
Both bundled asyncio source files declare 0.66b0.dev because they are the affected parent and merged-fix commits used for runtime replay. A separate release-lineage audit establishes v0.44b0 as the first published affected package, v0.65b0 as still affected, and v0.66b0 as the first fixed release. Published wheel hashes are retained, but wheel bytes were not downloaded or executed in this network-restricted environment.

The full asyncio implementation, threading implementation, BaseInstrumentor, and listed helpers are byte-verified against Git blob hashes in `../provenance/upstream-files.json`. `asyncio/affected.py` is the affected revision's `__init__.py`, renamed only for side-by-side loading. Native tests are retained elsewhere with their own blob hashes. No imported callback or wrapper is replaced by a mock SDK.

`_semconv.py` is explicitly an excerpt of upstream initialization (original full-file blob e1af0c0960624bd5ad2f4ce5e402f09ee3bd2e54), with the stability-signal enums and initialization path used by BaseInstrumentor plus necessary constants/imports. Unused HTTP/database conversion helpers are omitted. It is NOT claimed byte-identical to the full upstream module and is not listed as such in the blob manifest. Its comments mark this seam. The installed real SDK is 1.42.1 and semantic-convention distribution 0.63b1. These compatibility choices limit whole-distribution conclusions.

Copyright and Apache-2.0 source headers remain in all copied files. The license is `LICENSE-OpenTelemetry-Apache-2.0.txt`. Primary repository: https://github.com/open-telemetry/opentelemetry-python-contrib . Reconstruct an original source tree on an internet-connected machine with `git clone` and `git checkout` of the exact revision; paths in the bibliography and provenance identify each input. Retrieval is not needed to replay this bundled subset.
