# ATTR-02 — a span's eligibility is not knowable when `on_start` runs

Captured evidence for Phase 03 Plan 01. Every fenced block below is verbatim stdout of the command
shown immediately above it, produced on this machine against the working tree at the commit this
file is committed in. Nothing was re-typed, re-wrapped, or tidied.

**What this file has to prove.** Plan 03-01 opened with a `checkpoint:decision` — `gate="blocking-human"` —
about what `ReveniumAttributionSpanProcessor.on_start` may consult before it stamps a span. The
phase's stated constraint was that the processor consult `eligibility.classify_span` so that
orchestration spans are not stamped. That constraint cannot be implemented as written, and the way it
fails is silent: at `on_start` MLflow has not yet set `mlflow.spanType`, so `classify_span` returns
`WRONG_TYPE` for **every** span in the process, genuinely billable ones included. A processor gated on
it is installed, observes every span, stamps nothing, and reports no error — the exact shape
`processor.py`'s own module docstring says the Phase-1 constructor raised in order to prevent.

The decision was answered **`declared-only`**: resolve the operation with
`semconv.operation_for_span`, and skip the stamp only when the result is *not* `None` **and** is not a
member of `BILLABLE_GENAI_OPERATIONS`. An unresolved operation means undecided, and undecided is
stamped. Section 2 is the measurement that rule rests on.

**Scope and boundaries.**

- **No CI has run.** `.github/workflows/version-matrix.yml` is provision only and says so in its own
  header (plan 01-07). Everything below was produced locally, by running the commands shown. Nothing
  here should be read as a CI result, a release, a publication, a merge, or a statement about
  production readiness.
- **This is evidence about the installed MLflow, and about nothing else.** It proves how MLflow
  `3.16.0` orders span creation against `mlflow.spanType` on the three span-creation paths named
  below. It is not evidence about the Revenium backend — this project makes no call to Revenium, to
  a customer environment, or to any hosted endpoint — and it is not a claim about any MLflow release
  other than the one in the captured version line.
- No command reads or prints an environment variable's value, and no credential is set or referenced.
  `MLFLOW_TRACKING_URI` is *written* to a throwaway `sqlite:` file under a temporary directory,
  because MLflow logs a finished trace to whatever tracking URI it can resolve and the default file
  store is in maintenance mode as of 3.16.0. Nothing is read from an existing tracking store and
  nothing leaves the machine.
- Both commands import MLflow. `tests/conftest.py` disables MLflow's own outbound telemetry for the
  whole session before any test imports it, and every MLflow import in
  `tests/unit/test_stamp_time_evidence.py` lives inside a function body so that guard wins the race
  against pytest's collection pass. The standalone reproducer in section 2 sets the same two
  variables itself, in its first two statements, before importing anything.
- Both commands run under `.venv/bin/python`, the same interpreter `scripts/check.sh` resolves as
  `PY`. The system `python3` on this machine is 3.9.6, below this project's 3.10 floor, so a bare
  PATH lookup would make these transcripts unattributable.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`. The MLflow and
OpenTelemetry SDK releases the claim is made against are printed by the run itself, read from the
installed packages — not typed here.

---

## 1. The three paths, and why all three are driven

MLflow's autolog integrations do not all create spans the same way, so a measurement of one path is
not a measurement of MLflow. All three are driven:

| Path | Entry point | Who reaches it |
|------|-------------|----------------|
| A | `mlflow.start_span(span_type=...)` | Application code instrumenting by hand |
| B | `@mlflow.trace(span_type=...)` | The decorator most user code uses |
| C | `mlflow.start_span_no_context(...)` | Autolog's child LLM spans |

---

## 2. The measurement

The probe is a read-only `SpanProcessor` attached to `mlflow.tracing.get_bridged_tracer_provider()`
— the public attachment point, so no private MLflow API and no `_compat` exemption is involved. It
records `mlflow.spanType` exactly as it sits on the wire, and `eligibility.classify_span`'s verdict,
at `on_start` and again at `on_end`.

```
.venv/bin/python - <<'PY' 2>&1 | grep -v "INFO mlflow"
import os, tempfile

os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{tempfile.mkdtemp()}/tracking.db"

from opentelemetry.sdk.trace import SpanProcessor

from revenium_mlflow.tracing._spanattrs import MLFLOW_SPAN_TYPE
from revenium_mlflow.tracing.eligibility import classify_span

rows = []


class Probe(SpanProcessor):
    def on_start(self, span, parent_context=None):
        rows.append(("on_start", span.name, span.attributes.get(MLFLOW_SPAN_TYPE), classify_span(span)))

    def on_end(self, span):
        rows.append(("on_end", span.name, span.attributes.get(MLFLOW_SPAN_TYPE), classify_span(span)))


import mlflow

mlflow.tracing.get_bridged_tracer_provider().add_span_processor(Probe())
USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

with mlflow.start_span(name="path-a-start-span", span_type="CHAT_MODEL") as s:
    s.set_attribute("mlflow.chat.tokenUsage", USAGE)


@mlflow.trace(name="path-b-trace-decorator", span_type="CHAT_MODEL")
def traced():
    mlflow.get_current_active_span().set_attribute("mlflow.chat.tokenUsage", USAGE)


traced()

s = mlflow.start_span_no_context(name="path-c-start-span-no-context", span_type="CHAT_MODEL")
s.set_attribute("mlflow.chat.tokenUsage", USAGE)
s.end()

import opentelemetry.sdk.version as otel

print(f"mlflow          {mlflow.__version__}")
print(f"opentelemetry   {otel.__version__}")
print()
print(f"{'when':9s} {'path':30s} {'mlflow.spanType':22s} classify_span")
for when, name, span_type, verdict in rows:
    print(f"{when:9s} {name:30s} {span_type!r:22s} {verdict.value}")
PY
```

```
mlflow          3.16.0
opentelemetry   1.44.0

when      path                           mlflow.spanType        classify_span
on_start  path-a-start-span              'null'                 WRONG_TYPE
on_end    path-a-start-span              '"CHAT_MODEL"'         ADMITTED
on_start  path-b-trace-decorator         'null'                 WRONG_TYPE
on_end    path-b-trace-decorator         '"CHAT_MODEL"'         ADMITTED
on_start  path-c-start-span-no-context   'null'                 WRONG_TYPE
on_end    path-c-start-span-no-context   '"CHAT_MODEL"'         ADMITTED
```

`'null'` is the JSON literal for absent, on the wire — MLflow serializes every span attribute to a
JSON string before it reaches OpenTelemetry, so the SDK's shared decoder reads it back as `None`.
The type arrives between the two moments, and the token counts arrive later still. At `on_start`
**both** halves of the eligibility gate are therefore undecidable, on every path.

---

## 3. The same measurement, as assertions that fail the build

Section 2 is a transcript, and a transcript rots the moment someone upgrades MLflow.
`tests/unit/test_stamp_time_evidence.py` pins it: three assertions, each a distinct way the decision
can rot, against all three paths, plus a non-vacuity control that the probe saw anything at all, plus
one test asserting that *this file* still records what the probe just measured.

```
.venv/bin/python -m pytest tests/unit/test_stamp_time_evidence.py -q
```

```
...........                                                              [100%]
11 passed in 0.97s
```

The `on_start` assertion is derived from `eligibility.KNOWN_MLFLOW_SPAN_TYPES` rather than compared
against the observed `'null'`, deliberately. A future MLflow that starts typing spans at creation
time goes red and names the type it set; a future MLflow that merely changes how it spells absence
does not raise a false alarm. Going red is the wanted outcome, not a nuisance: `declared-only` would
stop being the only workable rule, and the checkpoint decision should be reopened by whoever is here
then.

---

## 4. The other half of ATTR-02 — that the write must happen at `on_start`

Section 2 says a span's *eligibility* is not knowable at `on_start`. ATTR-02 says the *attribution*
must nevertheless be written there. The second claim has its own evidence, and it needs it, because
a test asserting "we stamp in `on_start`" is worthless if it cannot fail against an implementation
that stamps in `on_end`.

`tests/fixtures/processors.py::OnEndWritingAttributionProcessor` is that implementation, built on
purpose: it retains the live span handed to `on_start` together with the attribution captured at that
moment, and attempts the write from `on_end` through the retained reference. Substituting it into the
shared tracer assertion that `tests/unit/test_attribution_scope.py` passes with produces:

```
E       AssertionError
tests/fixtures/processors.py:215: AssertionError
------------------------------ Captured log call -------------------------------
WARNING  opentelemetry.sdk.trace:__init__.py:902 Setting attribute on ended span.
=========================== short test summary info ============================
FAILED tests/unit/test_attribution_scope.py::test_a_span_created_inside_the_scope_is_collected_carrying_the_subscriber_id
1 failed in 0.04s
```

Three things in that transcript, and the third is the point:

1. The assertion **is** able to fail. It is the same function object the passing test calls, not a
   copy of it.
2. The write **did not raise**. `Span.end()` has frozen the attribute store, but the retained object
   still has `set_attribute` on it, so the call returns normally. Writing through `on_end`'s own
   argument would have raised `AttributeError` — that argument is a `ReadableSpan` with no such
   method — which is the loud version nobody ships.
3. The only signal is one `WARNING` on the `opentelemetry.sdk.trace` logger. No exception, no return
   value, no metric, and nothing at all on the exported span. `ReveniumAttributionSpanProcessor`'s
   class docstring records that MLflow suppresses even that.

`tests/unit/test_on_start_not_on_end.py` asserts all three, in one process, and runs the inverted
substitution inside `pytest.raises(AssertionError)` so the demonstration is part of the suite rather
than a claim in a document.
