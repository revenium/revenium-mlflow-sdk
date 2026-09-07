# EXP-03 — One MLflow trace, two destinations, asserted on decoded protobuf

**Plan:** 04-01 (Revenium-Owned OTLP Export and the Install Gate, wave 1)
**Requirements:** CFG-01, CFG-02, CFG-07, CFG-09, EXP-01, EXP-02, EXP-03, VER-01, VER-03
**Captured:** 2026-09-07

This file is a capture of runs, not a document describing them. Every block below
is command output. `tests/unit/test_dual_export_gate.py::test_the_verification_document_records_what_this_run_measured`
re-derives the key lines from a live run on every `pytest` invocation and fails if
this file no longer contains them, so the transcript cannot rot into false
evidence while the suite stays green.

---

## 1. What is claimed

One `configure_dual_export()` call, one simulated MLflow LLM trace, one process,
one run — and that trace is readable from the MLflow Tracking Server store **and**
present in a fake Revenium OTLP collector's decoded `ExportTraceServiceRequest`,
carrying `gen_ai.*` attributes with integer token counts, the `revenium.*`
attribution the phase-3 processor stamped, span kind `CLIENT`, and
`gen_ai.provider.name` in the resource block. An orchestration span from the same
trace is absent from that payload.

**No call reaches Revenium, any customer environment, or any hosted endpoint.**
The collector binds `127.0.0.1` on an ephemeral port; the Tracking Server is a
sqlite file under a temporary directory; the only credential any run supplies is
the `rev_mk_FAKE` sentinel. `request Host = 127.0.0.1` below is that constraint
read back off the captured request rather than asserted about the fixture.

---

## 2. Environment

```
$ .venv/bin/python -c "import mlflow, opentelemetry.sdk.version as v; print(mlflow.__version__, v.__version__)"
3.16.0 1.44.0
```

```
mlflow.__version__ = 3.16.0
opentelemetry-sdk = 1.44.0
```

`opentelemetry-exporter-otlp-proto-http` 1.44.0, `protobuf` 6.33.6, Python 3.10.
No distribution was added to `pyproject.toml` for this plan: the protobuf types
the collector decodes with come through the already-declared
`opentelemetry-exporter-otlp-proto-http` runtime dependency.

---

## 3. Reproducer

The transcript in §4 is the output of `/tmp/exp03_dump.py`, which is the `gate`
fixture of `tests/unit/test_dual_export_gate.py` reduced to one trace and made to
print rather than assert:

```python
os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{tempfile.mkdtemp()}/tracking.db"

with FakeOTLPCollector() as collector:
    import mlflow

    handle = configure_dual_export(otlp_traces_endpoint=collector.endpoint, api_key="rev_mk_FAKE")
    with attribution(subscriber_id="sub-gate-01", organization_name="org-gate-01"):
        with mlflow.start_span(name="gate-chat", span_type="CHAT_MODEL") as span:
            span.set_attribute("mlflow.llm.model", "gpt-4o")
            span.set_attribute("mlflow.llm.provider", "openai")
            span.set_attribute("mlflow.chat.tokenUsage", dict(USAGE))
            trace_id = span.trace_id
    handle.flush(5.0)
    mlflow.flush_trace_async_logging()
    trace = mlflow.get_trace(trace_id)  # destination 1: the Tracking Server store
    request = collector.assert_received_export()  # destination 2: the decoded protobuf
```

`USAGE` is `{"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050,
"cache_read_input_tokens": 900}`.

Two flushes, and they are not interchangeable. `mlflow.flush_trace_async_logging()`
drains MLflow's own background logging queue and does **not** touch the
OpenTelemetry batch processor; `handle.flush(5.0)` drains this SDK's processor and
does not touch MLflow's. Asserting after only one of them measures the wrong
destination.

---

## 4. Transcript — both destinations, one run

```
$ .venv/bin/python /tmp/exp03_dump.py

flush = True
MLflow trace id = tr-0c579b28cc9223ae6ef2ab9d413e61fb
MLflow store span count = 1
MLflow store span names = ['gate-chat']
POST path = /v1/traces
request Host = 127.0.0.1
request content-type = application/x-protobuf
request x-api-key = rev_mk_FAKE
request authorization = None
request content-encoding = None
request body bytes = 713
resource_spans = 1

decoded span name = gate-chat
decoded span kind = 3 (3 == SPAN_KIND_CLIENT)
decoded instrumentation scope = mlflow.tracing.provider
decoded parent_span_id = None
decoded duration ns = 18383000

resource attributes:
  gen_ai.provider.name = 'revenium-mlflow-sdk'
  gen_ai.system = 'revenium-mlflow-sdk'
  telemetry.sdk.language = 'python'
  telemetry.sdk.name = 'revenium-mlflow-sdk'
  telemetry.sdk.version = '3.16.0'

span attributes (value, AnyValue oneof):
  gen_ai.operation.name = 'chat'  [string_value]
  gen_ai.provider.name = 'openai'  [string_value]
  gen_ai.request.model = 'gpt-4o'  [string_value]
  gen_ai.response.model = 'gpt-4o'  [string_value]
  gen_ai.system = 'openai'  [string_value]
  gen_ai.usage.cache_read_input_tokens = 900  [int_value]
  gen_ai.usage.input_tokens = 1000  [int_value]
  gen_ai.usage.output_tokens = 50  [int_value]
  revenium.middleware.source = 'mlflow'  [string_value]
  revenium.organization.name = 'org-gate-01'  [string_value]
  revenium.subscriber.id = 'sub-gate-01'  [string_value]
```

### The same facts, as the pinned lines

These are what the suite regenerates and checks this file against.

```
mlflow.__version__ = 3.16.0
opentelemetry-sdk = 1.44.0
store spans without configure_dual_export = 1
store spans for the gate trace = 1
store spans for the mixed trace = 2
exported spans for the gate trace = 1
exported spans for the mixed trace = 1
content-type = application/x-protobuf
x-api-key = rev_mk_FAKE
authorization = None
host = 127.0.0.1
span kind = 3
instrumentation scope = mlflow.tracing.provider
resource telemetry.sdk.name = revenium-mlflow-sdk
resource gen_ai.provider.name = revenium-mlflow-sdk
resource gen_ai.system = revenium-mlflow-sdk
span gen_ai.operation.name = chat (string_value)
span gen_ai.provider.name = openai (string_value)
span gen_ai.request.model = gpt-4o (string_value)
span gen_ai.usage.input_tokens = 1000 (int_value)
span gen_ai.usage.output_tokens = 50 (int_value)
span gen_ai.usage.cache_read_input_tokens = 900 (int_value)
span revenium.subscriber.id = sub-gate-01 (string_value)
span revenium.organization.name = org-gate-01 (string_value)
span revenium.middleware.source = mlflow (string_value)
mixed trace exported span names = ['mixed-chat']
```

### What is worth reading twice in that dump

- **`cache_read_input_tokens = 900 [int_value]`.** MLflow's own native dual export
  path was measured dropping this key: 900 sent, only input and output delivered.
  A cached read is priced differently from a fresh one, so the drop is a wrong
  invoice, not a missing metric. Carrying it is a large part of why this SDK owns
  an exporter instead of setting `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT=true`.
- **`gen_ai.provider.name` appears twice with different values, and that is
  correct.** In the resource it is `revenium-mlflow-sdk` — a claim about which
  SDK produced the payload, which is what the backend's mapper selection keys on.
  On the span it is `openai` — a claim about the traffic. Conflating them would
  report every model call as coming from Revenium.
- **`span kind = 3`.** A raw MLflow `CHAT_MODEL` span arrives `INTERNAL` (1); the
  GenAI conventions require `CLIENT` for inference (SEM-12).
- **No `mlflow.*` attribute survived.** An untranslated MLflow span carries
  `mlflow.traceRequestId`, `mlflow.spanType`, `mlflow.chat.tokenUsage` and
  `mlflow.spanLogLevel`. The absence is as much the claim as the presence.
- **`request authorization = None`.** Plan 04-01 Task 1 Q1, answered
  `recommended`: the credential rides on lowercase `x-api-key` and on nothing
  else. Read back off the captured request, so `both-headers` creeping back in
  later fails a test.
- **`instrumentation scope = mlflow.tracing.provider`.** Half the provenance path
  that pays for the `telemetry.sdk.name` override; `revenium.middleware.source =
  mlflow` is the other half. Both are asserted, because after the override they
  are the only two places the payload still says these spans came from MLflow.

---

## 5. Open finding — `telemetry.sdk.version` was not overridden

The dump above reads:

```
  telemetry.sdk.name = 'revenium-mlflow-sdk'
  telemetry.sdk.version = '3.16.0'
```

`3.16.0` is MLflow's version, now sitting under this SDK's name. The pair is
false: `revenium-mlflow` has never shipped a 3.16.0.

It is left as measured rather than quietly corrected. `telemetry.sdk.version` is a
second wire-facing value that reaches a live Revenium endpoint during a customer
demo, and plan 04-01 Task 1 made exactly that class of choice a
`gate="blocking-human"` checkpoint precisely because this repository cannot check
the far side. Changing it here would be the unreviewed wire change the checkpoint
exists to prevent. The obvious fix is `revenium_mlflow.__version__`; a later plan
in this phase should put it to a human alongside whatever else it asks.

---

## 6. Control A — the eligibility filter removed

`src/revenium_mlflow/tracing/exporter.py`, one line in `ReveniumSpanExporter.export`:

```diff
-        admitted = [span for span in spans if _is_billable_llm_span(span)]
+        admitted = list(spans)  # SABOTAGE: eligibility filter removed
```

```
$ .venv/bin/python -m pytest tests/unit/test_exporter_pipeline.py tests/unit/test_dual_export_gate.py -q

        operations = [span.attributes.get("gen_ai.operation.name") for span in gate.mixed_exported]
>       assert operations == ["chat"], (
            f"expected exactly the billable span to reach Revenium, got operations {operations} "
            f"from span names {[span.name for span in gate.mixed_exported]}"
        )
E       AssertionError: expected exactly the billable span to reach Revenium, got operations ['chat', None] from span names ['mixed-chat', 'mixed-chain']
E       assert ['chat', None] == ['chat']

FAILED tests/unit/test_exporter_pipeline.py::test_a_mixed_batch_exports_only_its_billable_span
FAILED tests/unit/test_exporter_pipeline.py::test_a_batch_of_only_orchestration_spans_produces_no_request_at_all[CHAIN]
FAILED tests/unit/test_exporter_pipeline.py::test_a_batch_of_only_orchestration_spans_produces_no_request_at_all[AGENT]
FAILED tests/unit/test_exporter_pipeline.py::test_a_batch_of_only_orchestration_spans_produces_no_request_at_all[TOOL]
FAILED tests/unit/test_exporter_pipeline.py::test_a_batch_of_only_orchestration_spans_produces_no_request_at_all[RETRIEVER]
FAILED tests/unit/test_exporter_pipeline.py::test_an_orchestration_span_carrying_tokens_is_still_rejected
FAILED tests/unit/test_dual_export_gate.py::test_the_orchestration_span_reached_mlflow_but_not_revenium
7 failed, 25 passed in 11.48s
```

The failure message is the point: `mixed-chain` — a `CHAIN` span carrying the
aggregate token counts of the model span nested inside it — reached the
collector. That is a double-count, and it is what SEM-11 exists to prevent.
Phase 3's `declared-only` decision means that span **is** stamped with
`revenium.*` at `on_start`, so this filter is the only thing between it and a
Revenium invoice.

Reverted, and green again:

```
$ .venv/bin/python -m pytest tests/unit/test_exporter_pipeline.py tests/unit/test_dual_export_gate.py -q
................................                                         [100%]
32 passed in 12.13s
```

---

## 7. Control B — the exporter's delegate call removed

```diff
-        return self._delegate.export([self._rebuild(span) for span in admitted])
+        [self._rebuild(span) for span in admitted]  # SABOTAGE: delegate call removed
+        return _SpanExportResult.SUCCESS
```

The sabotage keeps the reconstruction — every span is still built — and only
stops the bytes leaving. That is the shape a mock-based suite cannot see, and the
reason it is worth a control: 14 of the 20 gate assertions go red, and the first
one to go names the cause.

```
$ .venv/bin/python -m pytest tests/unit/test_dual_export_gate.py::test_the_collector_received_a_decodable_export -q

>       assert gate.receipt_error is None, gate.receipt_error
E       AssertionError: the collector at http://127.0.0.1:51677/v1/traces received no request at all. Nothing below this line is a claim about an export — assertions over an empty payload pass vacuously. Check that flush() was called and that the exporter was pointed at this endpoint.

FAILED tests/unit/test_dual_export_gate.py::test_the_collector_received_a_decodable_export
1 failed in 5.56s
```

```
$ .venv/bin/python -m pytest tests/unit/test_dual_export_gate.py -q
FAILED tests/unit/test_dual_export_gate.py::test_the_collector_received_a_decodable_export
FAILED tests/unit/test_dual_export_gate.py::test_the_export_was_protobuf_over_http
FAILED tests/unit/test_dual_export_gate.py::test_the_credential_rode_on_x_api_key_and_nowhere_else
FAILED tests/unit/test_dual_export_gate.py::test_every_export_was_addressed_to_loopback
FAILED tests/unit/test_dual_export_gate.py::test_exactly_one_span_reached_revenium_for_the_billable_trace
FAILED tests/unit/test_dual_export_gate.py::test_the_exported_span_is_client_kind
FAILED tests/unit/test_dual_export_gate.py::test_the_exported_span_is_translated_not_forwarded
FAILED tests/unit/test_dual_export_gate.py::test_token_counts_arrived_as_integers_not_strings
FAILED tests/unit/test_dual_export_gate.py::test_cache_read_tokens_survived_the_pipeline
FAILED tests/unit/test_dual_export_gate.py::test_the_phase_three_attribution_survived_the_export_boundary
FAILED tests/unit/test_dual_export_gate.py::test_the_resource_claims_the_provider
FAILED tests/unit/test_dual_export_gate.py::test_the_resource_sdk_name_was_overridden
FAILED tests/unit/test_dual_export_gate.py::test_the_instrumentation_scope_still_says_mlflow
FAILED tests/unit/test_dual_export_gate.py::test_the_orchestration_span_reached_mlflow_but_not_revenium
14 failed, 6 passed in 5.06s
```

The six that still pass are the six that are not claims about the wire: the handle
is typed, the flush returned, both processors attached in the right order, the
trace is in the store, and MLflow's export is unchanged. That split is itself
evidence — it is exactly the set of things a Revenium-blind install would still
get right, which is why `assert_received_export()` has to run before any of them
is read as proof of an export.

Reverted, and green again:

```
$ .venv/bin/python -m pytest tests/unit/test_exporter_pipeline.py tests/unit/test_dual_export_gate.py -q
................................                                         [100%]
32 passed in 11.36s
```

---

## 8. The gate

```
$ bash scripts/check.sh
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
72 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 18 source files
### .venv/bin/python -m pytest -q
477 passed in 11.69s
### all checks passed
```

Baseline before this plan was 442. No `# noqa` was added anywhere, and
`[tool.ruff.lint.per-file-ignores]` still holds exactly its two entries.

---

## 9. What this does **not** prove

Recorded because a demo-ready slice is not a verified phase, and this document
will be read later by someone deciding what has already been checked.

- **Session-wide `(trace_id, span_id)` uniqueness is not enforced.** The collector
  captures duplicates without complaint. VER-04, plan 04-07.
- **Nothing about the real Revenium endpoint.** The credential header and the
  resource SDK name are recorded human decisions made on source evidence, not
  round-trip measurements; PROJECT.md forbids the call that would settle them.
- **`telemetry.sdk.version` is knowingly wrong.** §5.
- **No idempotency, no eviction, no reinstall.** Calling
  `configure_dual_export()` twice attaches two pipelines and double-exports every
  span. `handle.is_active()` and `handle.reinstall()` raise. Plan 04-04.
- **No failure visibility.** `BatchSpanProcessor` discards
  `SpanExportResult.FAILURE` silently, so a 401 or a 500 from a real endpoint
  reaches no caller. EXP-04, plans 04-05 through 04-07.
- **No cap enforcement and no redaction.** Both are named, pass-through call
  sites in `exporter.py`. Plan 04-05.
- **No endpoint normalisation and no double-suffix detection.** The endpoint is
  used as supplied. Plans 04-02 and 04-05.
- **The env-var byte-identity guard is not written.** This plan passes the
  endpoint and headers as constructor arguments and never touches
  `OTEL_EXPORTER_OTLP_TRACES_*`, but nothing asserts that yet. CFG-03, plan 04-02.
