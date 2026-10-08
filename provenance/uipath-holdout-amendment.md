# UiPath holdout discovery and confirmation amendment

Date: 2026-10-04

The UiPath public-source holdout was added after the original OpenTelemetry and
Speaches experiments to broaden the execution-boundary mechanisms.  The first
100-process exploratory run covered ten sync, async, generator, and async-
generator cases (ten repeats each).  Nine cases passed.  In all ten explicit
`aclose()` trials, the public async-generator wrapper ended its span before the
wrapped async generator completed cleanup; the operation ledger exited later
with `CancelledError`.  The qualified gap was diagnosed as
`ENDS_BEFORE_EXIT`; the span-name baseline passed, and direct assertions agreed
with the ledger checker.

This outcome was not an a-priori expected defect.  The raw exploratory files
are retained under `results/uipath-holdout-discovery/` and are not counted as a
confirmatory evaluation.  After observing it, we froze the source blob, the
consumer action (`__anext__` followed by explicit `aclose()`), the execution-
coverage policy, the clock gate, and the expected diagnostic.  We then ran a
new independent confirmation directory.  The paper labels the result as a
local, unconfirmed public-source observation rather than a maintainer-confirmed
UiPath defect or evidence from a deployed product.
