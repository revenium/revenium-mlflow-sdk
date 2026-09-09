# CFG-03 — the process-global OTLP slot is never touched, and three destinations coexist

**Requirement:** CFG-03. `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and
`OTEL_EXPORTER_OTLP_TRACES_HEADERS` are byte-identical before and after
`configure_tracing()`, including when they were unset before and must still be
unset after.

**Plan:** 04-02, Tasks 2 and 3. **Captured:** 2026-09-09.

Pinned to a live run by
`tests/unit/test_otel_slot_untouched.py::test_the_verification_document_records_what_this_run_measured`,
which fails if this document stops recording what the suite measures. Do not
edit the tables below by hand — re-run the reproducer in section 2 and paste
its output.

---

## 1. Why this requirement is in a demo-critical wave

`OTEL_EXPORTER_OTLP_TRACES_HEADERS` is a **process-global, single-valued**
variable read by every OTLP-aware library in the process. It is where an OTLP
exporter finds its authentication.

Two consequences follow from writing it, and only the first is the one the
requirement text names.

1. **Credential egress (T-04-09).** Writing the Revenium key into the headers
   variable ships that key to every OTLP destination the customer has
   configured — their own collector, their APM vendor, anything else in the
   process. This week's demo points at a live endpoint with a real key.

2. **Silent loss of the product (T-04-10).** Setting
   `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` changes *which processors MLflow
   builds*. Measured in section 4: with the endpoint set and
   `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT` unset, MLflow's Tracking Server
   processor is **absent** — MLflow replaced its Tracking Server export with an
   OTLP one rather than adding to it. An SDK that wrote that variable would not
   merely leak a credential; it would switch off the customer's Tracking Server
   export, which is the entire product.

The SDK therefore carries its endpoint and its credential as constructor
arguments on its own `OTLPSpanExporter` instance
(`src/revenium_mlflow/tracing/install.py`), and reads its configuration from
Revenium-named variables only (`src/revenium_mlflow/config.py`).

## 2. Reproducer

Everything below came from one run of this script. Loopback sockets and a
sqlite store; no hosted endpoint is contacted and the only credential is the
`rev_mk_SLOT_SENTINEL` sentinel.

```python
# Two fake OTLP collectors, one standing in for the customer's own and one for
# Revenium. Both bind 127.0.0.1 on an ephemeral port.
from tests.fixtures.collector import FakeOTLPCollector
from revenium_mlflow import attribution, configure_tracing
import mlflow

TRACKED = (
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
)


def snapshot():
    names = {n for n in os.environ if n.startswith("OTEL_")} | set(TRACKED)
    return {n: os.environ.get(n) for n in sorted(names)}  # None == absent


def rebuild():
    # MLflow reads the OTLP variables once, at provider initialisation.
    # disable() then enable() rebuilds the provider and re-reads them.
    mlflow.tracing.disable()
    mlflow.tracing.enable()
    return mlflow.tracing.get_bridged_tracer_provider()


with FakeOTLPCollector() as customer, FakeOTLPCollector() as revenium:
    ...  # three phases, below
```

The full script is the fixture in `tests/unit/test_otel_slot_untouched.py`,
which is what the suite runs on every `bash scripts/check.sh`.

**Versions:**

```
python 3.10.20 | mlflow 3.16.0 | otel-sdk 1.44.0
```

## 3. The byte-identity snapshots, side by side

`<absent>` means the name was not in the environment at all. Absence is
recorded and compared **separately** from equality, because a dict comparison
over a mapping the SDK never populated is satisfied either way.

### Phase 1 — the two variables were unset, and must still be unset

| Variable | Before | After |
|---|---|---|
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `<absent>` | `<absent>` |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | `<absent>` | `<absent>` |
| `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL` | `<absent>` | `<absent>` |

```
identical: True
```

### Phase 2 — the customer had already set them

| Variable | Before | After |
|---|---|---|
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://127.0.0.1:64533/v1/traces` | `http://127.0.0.1:64533/v1/traces` |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | `x-customer-token=customer-only-token` | `x-customer-token=customer-only-token` |
| `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL` | `http/protobuf` | `http/protobuf` |

```
identical: True
processors after configure: ['OtelSpanProcessor', 'ReveniumAttributionSpanProcessor', 'BatchSpanProcessor']
```

The port is ephemeral and differs per run; the pinning test compares the
variable names and the customer header, not the port.

### Phase 3 — the coexistence run

```
identical: True
```

**In all three phases the SDK added its two processors and removed none.** That
is the contrast with MLflow's own behaviour in section 4.

## 4. The drift anchor: MLflow replaces rather than adds

Measured in one process, varying only `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`,
with `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` set in both cases:

| `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT` | Provider's processor list |
|---|---|
| unset | `OtelSpanProcessor` |
| `"true"` | `OtelSpanProcessor MlflowV3SpanProcessor` |

`MlflowV3SpanProcessor` is MLflow's Tracking Server export. With the endpoint
variable set and the flag unset it is **gone, not supplemented**. This is the
measurement that makes CFG-03 a correctness requirement rather than a hardening
item, and it is pinned as a drift anchor: a future MLflow that starts adding
rather than replacing fails
`test_mlflow_replaces_rather_than_adds_when_the_endpoint_variable_is_set`, and
that failure hands this reasoning back to whoever is here then.

## 5. Three destinations, one process, one run

One `CHAT_MODEL` span inside an `attribution()` scope, with the customer's own
OTLP endpoint set, `http/protobuf` selected, and MLflow's dual-export flag
enabled — which is what a customer sets to keep their Tracking Server export
alongside their own OTLP one. `configure_tracing()` pointed only at the Revenium
collector.

Three destinations, three flushes, and they are not interchangeable:
`handle.flush(5.0)` drains this SDK's own `BatchSpanProcessor`,
`provider.force_flush(20000)` drains MLflow's `OtelSpanProcessor` to the
customer's collector, and `mlflow.flush_trace_async_logging()` drains MLflow's
background thread to the Tracking Server.

```
handle.flush(5.0): True
provider.force_flush(20000): True
Tracking Server store spans for the trace: 1
```

| Destination | Received | Asserted on |
|---|---|---|
| Customer's own OTLP collector | `['slot-chat']` | decoded `ExportTraceServiceRequest` |
| MLflow Tracking Server (sqlite) | 1 span | `mlflow.get_trace(trace_id)` read-back |
| Revenium collector | `['slot-chat']` | decoded `ExportTraceServiceRequest` |

### The two OTLP copies are not the same payload, and the difference is the point

**Customer's copy — MLflow's own, untranslated:**

```
span attribute keys: ['mlflow.chat.tokenUsage', 'mlflow.llm.model', 'mlflow.llm.provider',
                      'mlflow.spanLogLevel', 'mlflow.spanType', 'mlflow.traceRequestId',
                      'revenium.middleware.source', 'revenium.organization.name',
                      'revenium.subscriber.id']
resource keys      : ['telemetry.sdk.language', 'telemetry.sdk.name', 'telemetry.sdk.version']
```

**Revenium's copy — filtered, translated, resource-claimed:**

```
span attribute keys: ['gen_ai.operation.name', 'gen_ai.provider.name', 'gen_ai.request.model',
                      'gen_ai.response.model', 'gen_ai.system',
                      'gen_ai.usage.cache_read_input_tokens', 'gen_ai.usage.input_tokens',
                      'gen_ai.usage.output_tokens', 'revenium.middleware.source',
                      'revenium.organization.name', 'revenium.subscriber.id']
resource keys      : ['gen_ai.provider.name', 'gen_ai.system', 'telemetry.sdk.language',
                      'telemetry.sdk.name', 'telemetry.sdk.version']
span kind          : 3   (SPAN_KIND_CLIENT)
```

`gen_ai.usage.cache_read_input_tokens` reaches Revenium and no `gen_ai.*` key
reaches the customer's collector at all. Those are the two losses measured in
MLflow's own native dual export, and they are the reason this SDK owns an
exporter rather than setting `MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT` and pointing
MLflow at Revenium.

### Observed, and not a leak: `revenium.*` attribution reaches the customer's own collector

The customer's payload above carries `revenium.middleware.source`,
`revenium.organization.name` and `revenium.subscriber.id`. That is inherent to
the design rather than a defect: attribution is stamped in `on_start` on the
span itself (ATTR-02), the span is shared by every processor on the provider, and
MLflow's own exporter therefore sees the stamped attributes. It is **not**
credential egress — the scan in section 6 asserts the Revenium key reaches only
Revenium — and it is not something this SDK could avoid without abandoning
`on_start` stamping, which is the one place attribution can be written at all.

Recorded here so it is a known property rather than a surprise. A customer who
must not see these keys would have to filter them at their own collector.

## 6. The header scan, in both directions

Every captured request on both collectors, walked header name by header name and
value by value, case-insensitively.

| Needle | On Revenium's requests | On the customer's requests |
|---|---|---|
| `rev_mk_SLOT_SENTINEL` (Revenium credential) | `[('x-api-key', 'rev_mk_SLOT_SENTINEL')]` | `[]` |
| `customer-only-token` (customer's own token) | `[]` | `[('x-customer-token', 'customer-only-token')]` |

```
hosts: ['127.0.0.1']
```

**The capability half is asserted first, deliberately.** A leak scan that has
never located the thing it searches for is a scan that would report clean
against a real leak, so
`test_the_scan_finds_the_credential_on_reveniums_requests` runs before the test
that asserts the absence.

**The mirror direction matters too.** The customer's token lives in
`OTEL_EXPORTER_OTLP_TRACES_HEADERS`. An SDK that read that variable and passed
it to its own exporter — a plausible convenience — would send the customer's
credential to Revenium. Asserting both directions means neither leak can land
silently.

## 7. What this does not prove

- **Nothing about the far end.** Both collectors are loopback fakes. That
  Revenium's ingest accepts what was sent, and that `x-api-key` is the header it
  authenticates on, remain source-verified inferences — PROJECT.md forbids the
  call that would settle them.
- **Nothing about `telemetry.sdk.version`.** The exported resource still reads
  `telemetry.sdk.name = revenium-mlflow-sdk` beside MLflow's own
  `telemetry.sdk.version`. Plan 04-01 left that for a human on the record and
  this plan did not reopen it.
- **Nothing about a second `configure_tracing()` call.** Idempotency and
  processor eviction are plan 04-04. Two calls still attach two pipelines.
- **Nothing about a malformed endpoint.** URL well-formedness and the general
  double-suffix diagnosis are EXP-05, plan 04-05.
