# Source, literature, and unavailable-evidence register

Compiled from primary-source retrieval used through 2026-10-04
(America/Los_Angeles). This record distinguishes executed source, documented
contract, bibliographic identity, local observation, deliberate challenge, and
unavailable empirical evidence. It is not an independently signed systematic
review.

## Executed OpenTelemetry historical pair

OpenTelemetry Python Contrib issue #4900 was opened 2026-07-30 and closed when
pull request #4901 merged on 2026-09-14. The executed affected revision is the
immediate parent `f7788970bca275c99f65ba9c9e186b662f054c7e`; the fixed revision
is merge `e008b0e315b7d0a219c43e7ded1dc02e5abbeb69`. Both development trees
report `0.66b0.dev`. The release-lineage audit resolves v0.44b0 and v0.65b0 as
affected and v0.66b0 as the first verified fixed release.

`release-lineage/opentelemetry-asyncio-releases.json` retains release dates, tag
commits, source/version blobs, wheel names, and official SHA-256 values. The
wheel bytes were not dynamically executed. Full relevant asyncio/threading
implementations, helpers, and exact native-test methods are retained with Git-
blob verification in `upstream-files.json`.

Primary URLs:

* https://github.com/open-telemetry/opentelemetry-python-contrib/issues/4900
* https://github.com/open-telemetry/opentelemetry-python-contrib/pull/4901

The separate iterable pull request #5085 was open and unmerged when checked on
2026-10-03. It motivates accepted-input-shape cases but is not classified as a
confirmed defect in this work.

## Public application and tracing sources

### fastapi-best-architecture

Pinned revision `123a44aed02daf5ea60d2a7469625c933d3bb759`. The complete
telemetry file and MIT license are retained. The unchanged `init_tracer`
function is executed with only its OTLP exporter constructor replaced by an
in-memory exporter. Local routes execute the installed FastAPI/Starlette/AnyIO/
HTTPX stack. Redis/database integrations and the complete upstream application
suite are not executed.

### Speaches independent holdout

Pinned revision `993994f7984bf3fe9655b267448328cf66fccb42`, tracing-file Git
blob `709e44eb95a292e0b8074cd2efd0fff34d39afa7`. The application entry confirms
asyncio instrumentation setup, and `src/speaches/tracing.py` defines separate
synchronous and generator decorators. Only those decorators plus local bounded
operations are executed. The complete speech/model service, collector, and
deployment are not. Applying the synchronous decorator to a generator is a
researcher-created challenge, not a reported Speaches defect.

### UiPath async-generator transfer and local correction

Pinned revision `7181c279993fbca453b948cf767781282e1e6017`, path
`packages/uipath-core/src/uipath/core/tracing/decorators.py`, Git blob
`b7204271a784b7fccce420c11c8c6a9db1d48837`. The exact MIT-licensed source is
retained. It defines distinct synchronous, coroutine, generator, and async-
generator wrappers. The source file is executed unchanged with transparent
local seams for parent-context and metadata helpers; non-recording product
paths and the complete UiPath package are outside scope.

An exploratory 100-process run observed that explicit early `aclose()` of the
wrapped async generator ended the public-source span before the wrapped cleanup
exit. `uipath-holdout-amendment.md` froze the mechanism and expected diagnostic
before a separate 100-process confirmation. The confirmation reports
`ENDS_BEFORE_EXIT` in 10/10 early-close runs and no failure in the other nine
case families. A local patch awaits the inner generator's `aclose()` before
ending the span; its 100-process regression has 97 pass, 0 fail, and 3 clock-
inconclusive results, with all ten early-close cases passing. This is a local,
source-level observation and correction, not a maintainer-confirmed project bug
or adoption claim.

Primary source:

* https://github.com/UiPath/uipath-python/blob/7181c279993fbca453b948cf767781282e1e6017/packages/uipath-core/src/uipath/core/tracing/decorators.py

## Documentation and tool contracts

Official records support Python asyncio/contextvars behavior, AnyIO and
Starlette worker dispatch, FastAPI concurrency, OpenTelemetry tracing/context/
error conventions, W3C Trace Context, ThreadingInstrumentor behavior, and PEP
525 asynchronous-generator finalization. Documentation supports contracts; it
does not replace related research.

Tracetest documentation at commit `64eb49ff2037e0ba5d16237278d984758e7c7309`
and release v1.7.1 were identified. Its CLI and Docker were absent, and the
release binary/source could not be materialized because terminal network/DNS was
unavailable. `results/external-analyzer-availability.log` retains the attempt.
No empirical Tracetest result exists, and no substitute linter is named
Tracetest.

## Research literature audit

`reference-audit.json` contains 70 cited records verified through 2026-10-04:

* 37 peer-reviewed research entries using publisher or official venue metadata;
* 18 official specifications/documentation entries;
* 13 primary issue, pull-request, release, commit, or source entries; and
* 2 research preprints using original arXiv records.

Audit records retain title/authors/year/identifier sources, checked fields,
verification depth, record-specific dates, and scoped notes. The closest
verified objectives include TraceLink, OmniLink, TLA+ trace validation, runtime
verification, linearizability/history checking, distributed tracing,
concurrency testing, test-oracle/mutation/metamorphic testing, flaky-test work,
performance methodology, case-study guidance, and Tang et al.'s 2024 Empirical
Software Engineering article. Verification establishes bibliographic identity
and the scoped use made in the paper; it is not a citation ranking or independent
full-text systematic review.

## Unavailable or unresolved evidence

| Item | Status and consequence |
|---|---|
| Tracetest empirical comparison | Unavailable; no score or inferiority claim |
| Historical wheel execution | Release boundary resolved by official tags/metadata; wheel bytes not dynamically executed |
| Complete fastapi-best-architecture application | Not run; public configuration source plus real local framework dispatch only |
| Complete Speaches service/deployment | Not run; pinned decorator holdout only |
| Complete UiPath package/product/deployment | Not run; exact decorator source with documented seams only |
| Private/industrial field evidence | None; no deployment, incident, user, or adoption claim |
| Developer-effort benefit | Not measured; reviewability is an artifact property, not a productivity result |
| Universal checker soundness | Not established by finite tests, operators, or derived challenges |
| Independent full replay | Completed: 793/800 agreement; seven clock-only changes; no pass--fail reversal |

## Venue-format basis

The manuscript uses the supplied, unmodified IEEEtran `10pt,conference` class,
a non-anonymous author block, exactly 10 main-content pages, and 2 reference-only
pages. The Data Availability section immediately follows Conclusion and remains
inside the 10-page body. References begin on page 11. No public repository, DOI,
artifact badge, camera-ready status, or venue acceptance is invented.
