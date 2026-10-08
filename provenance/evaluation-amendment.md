# Evaluation amendments and freeze boundary

## Before the 20-repeat principal evaluation — 2026-09-29

The pilot used one gated operation per basic lifetime scenario and three per
repeated-call/lifecycle scenario. Independent replication is at the fresh-process
trial level. The expanded smoke set contained 38 discovery/regression
configurations. After checker tests passed, the three core module hashes were
frozen. Two BackgroundTasks integration paths were held out from checker
debugging and first executed in the repeated evaluation. All 40 principal
configurations were run 20 times with at most two child processes.

Requested gate delay cycled through 2, 5, and 9 ms; observed timestamps, not
requested delays, determine outcomes. Native tests preserve exact upstream method
files while using a local compatibility fixture. No full upstream CI claim is made.

The first BackgroundTasks attempt failed before callback entry because a postponed
local annotation was unresolved by FastAPI, producing 40 HTTP-422 responses.
Those attempts remain retained and excluded. The harness correction changed no
frozen checker/ledger code and generated a separate 40-trial corrected holdout.

## Post-freeze extensions — 2026-09-30

### Independent public-source holdout

A second project, `speaches-ai/speaches` at commit
`993994f7984bf3fe9655b267448328cf66fccb42`, was selected after the principal
protocol freeze. Its unmodified tracing-decorator source and MIT license are
retained and blob-verified. Four bounded cases run ten times each. The
synchronous-decorator-on-generator case is a deliberate misuse and is never
attributed to Speaches as a defect. The complete service and model stack are out
of scope.

### Diagnostic mutation challenge

The challenge reads retained real-SDK records and applies 18 predeclared
one-field transformations, 20 judgments per kind. Expected verdict and primary
diagnostic are determined by transformation definition before replay. These 360
items are derived oracle checks, not runtime executions, independent annotations,
or defects.

### Policy counterfactual

Sixty unchanged retained observations (20 execution, 20 submission, 20 combined)
are evaluated under five declared roles, producing 300 derived results. The
analysis demonstrates contract dependence and explicit abstention. It does not
search for a favorable role or estimate policy quality.

### Literature and page audit

The bibliography was expanded and re-audited to 68 entries. Every entry is cited,
and each audit record states category, verification depth, source, identifier,
checked fields, and limitations. The manuscript is compiled to exactly 10
main-content pages plus 2 reference-only pages without modifying IEEEtran layout.

## Post-freeze extensions — 2026-10-03

### Published-release lineage

Official release records and tags establish v0.44b0 as the first verified
published package exposing the studied `to_thread` surface, v0.65b0 as still
affected, and v0.66b0 as the first verified release carrying #4901. The audit
retains dates, tag commits, source/version blobs, wheel filenames, and official
wheel SHA-256 values. Dynamic evidence continues to use byte-verified affected
parent and merged-fix source with compatible installed SDK dependencies; wheel
bytes were not executed.

### Independent full replay

The complete 40-configuration matrix was repeated 20 times in 800 new processes,
with zero runner failures. It produced 458 pass, 278 fail, and 64 inconclusive
outcomes. Verdicts agree with the retained matrix in 793/800 cases. All seven
changes involve clock qualification and none is a pass--fail reversal. Direct
assertions agree in both matrices. The replay is retained separately rather than
replacing the principal observations.

### Executable perturbation challenge

Ten predeclared runtime perturbations were executed ten times each through the
real SDK capture path. Ninety-nine of 100 processes produced the expected
verdict and primary diagnostic. One queue-inclusive process had an ineligible
clock and returned inconclusive. It was not selectively rerun. Direct assertions
agree on all processes; the name baseline misses 69 qualified failures.

### Literature, authors, and page audit

The bibliography now has 68 audited and cited entries, including an official
citation for the disclosed ChatGPT assistance. The non-anonymous author block
contains the three user-supplied authors, affiliations, and email addresses. The
paper remains exactly 10 main pages plus 2 reference-only pages, with no layout
modification.

## 2026-10-04: executable-operator orthogonalization

The first native-test sensitivity matrix showed that the queue, parent, and
context operators also changed cancellation error reporting because their
wrappers passed `CancelledError` to `record_process`.  That made the updated
suite appear to detect the target mechanism when it was detecting a secondary
status/event change.  Before interpreting the matrix, we changed those
operators (and the duplicate/missing-status controls) to preserve the fixed
implementation's cancellation semantics.  The late-start operator was also
changed to preserve error status/events while moving only the span interval.
The pre-correction raw results are retained under
`results/failed-attempts/*-nonorthogonal/`; all reported challenge and
sensitivity results are fresh executions of the corrected operators.
