"""The process-global OTLP slot belongs to the customer, and this SDK never takes it (CFG-03).

``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` and ``OTEL_EXPORTER_OTLP_TRACES_HEADERS``
are single-valued variables read by every OTLP-aware library in the process.
Two things go wrong if this SDK writes them, and only one of them is the one
CFG-03's requirement text names.

*The credential leak.* The headers variable is where an OTLP exporter finds its
authentication. Writing the Revenium key into it would ship that key to every
OTLP destination the customer has configured — their own collector, their APM
vendor, anything else in the process. The demo this phase exists for points at a
live endpoint with a real key, so the shortcut has to be closed before it can be
reached for, not after.

*The silent loss of the product.* Measured during planning and re-measured by
:func:`test_mlflow_replaces_rather_than_adds_when_the_endpoint_variable_is_set`
below: setting the endpoint variable changes *which processors MLflow builds*.
The provider's list goes from ``['MlflowV3SpanProcessor']`` to
``['OtelSpanProcessor']`` — MLflow **replaces** its Tracking Server export with
an OTLP one rather than adding to it, because
``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`` is not set. An SDK that wrote that
variable would not merely leak a credential; it would switch off the customer's
Tracking Server export, which is the entire product. That measurement is pinned
here as a drift anchor: a future MLflow that starts adding rather than replacing
fails this test and hands the reasoning back to whoever is here then.

**What makes this proof rather than intent.** Three separate instruments, and
each is written to be capable of failing:

1. A before/after snapshot of the whole OTEL namespace, tagging every name as
   present-with-a-value or absent. ``absent stays absent`` is asserted
   *separately* from ``set stays equal``, because a dict comparison over a
   mapping the SDK never populated is satisfied either way.
2. Three destinations in one process and one run — the customer's own collector,
   the sqlite Tracking Server store, and the Revenium collector — each asserted
   on what it actually holds. The customer's copy is MLflow's own untranslated
   export and Revenium's is the filtered, translated one, and the *difference*
   between them is asserted too, because that difference is the reason this SDK
   owns an exporter at all.
3. A header scan over every captured request on both collectors. It asserts the
   Revenium credential is absent from the customer's traffic **and present on
   Revenium's** — a leak scan that has never located the thing it searches for
   is a scan that would report clean against a real leak.

**Why this is a ``unit`` test.** It stands up its own two collector sockets and
its own sqlite store in-process and depends on no running service.
``pyproject.toml`` sets ``addopts = -m 'not e2e and not integration'``, so this
module wearing the ``integration`` marker would be excluded from
``scripts/check.sh`` — the phase's own gate would prove nothing on every run
that matters.

**The environment fixture is the part most likely to make this file pass for the
wrong reason.** MLflow reads the OTLP variables once, at provider
initialisation; ``disable()`` followed by ``enable()`` rebuilds the provider and
re-reads them, and returns a different provider object (measured). So every
phase below forces that rebuild, and the fixture restores the entire namespace on
teardown whether the tests passed or failed — a leaked endpoint would silently
configure every test module that sorts after this one.

**No network.** Both collectors bind ``127.0.0.1`` on ephemeral ports, the store
is sqlite under ``tmp_path``, and the only credential is the
``rev_mk_SLOT_SENTINEL`` sentinel (T-04-03).
"""

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider

from revenium_mlflow import ReveniumExportHandle, attribution, configure_tracing
from tests.fixtures.collector import CapturedRequest, ExportedSpan, FakeOTLPCollector

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _REPO_ROOT / "src" / "revenium_mlflow"

#: The transcript this run is pinned against, resolved from this file rather
#: than from the working directory so the test means the same thing run from
#: anywhere.
_EVIDENCE_DOCUMENT = _REPO_ROOT / "docs" / "verification" / "cfg-03-env-untouched.md"

#: The guarded namespace, defined once. Everything below derives from this
#: constant — nothing re-spells the prefix, so widening or narrowing the guard is
#: a one-line, visible edit rather than a change that has to be made in five
#: places and might be made in four.
_OTEL_PREFIX = "OTEL_"

#: The two variables CFG-03 names, tracked explicitly so they appear in every
#: snapshot even when absent. Without this the "previously unset" case would
#: compare two mappings that never mentioned them.
_TRACKED_OTEL_VARIABLES = (
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
)

#: MLflow's own dual-export flag. Not in the OTEL namespace, but the fixture sets
#: it and therefore has to restore it.
_MLFLOW_DUAL_EXPORT = "MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT"

#: The sentinel Revenium credential. Never a live key (T-04-03). Distinctive
#: enough that the header scan below is searching for something that could only
#: have come from this SDK.
_FAKE_API_KEY = "rev_mk_SLOT_SENTINEL"

#: A token standing in for whatever the customer authenticates their own
#: collector with. The scan asserts it reaches their collector and not Revenium's,
#: which is the mirror image of the credential claim and fails if this SDK ever
#: starts forwarding the environment's headers to its own exporter.
_CUSTOMER_TOKEN = "customer-only-token"
_CUSTOMER_HEADER = "x-customer-token"

_SPAN_NAME = "slot-chat"

#: ``cache_read_input_tokens`` is here because MLflow's own native dual export
#: drops it. Its presence in the Revenium payload and its absence from the
#: translated shape of the customer's payload is what distinguishes the two
#: destinations.
_USAGE: Mapping[str, int] = {
    "input_tokens": 1000,
    "output_tokens": 50,
    "total_tokens": 1050,
    "cache_read_input_tokens": 900,
}

# --------------------------------------------------------------------------
# Snapshotting the namespace, present/absent-tagged.
# --------------------------------------------------------------------------


def _otel_snapshot() -> dict[str, str | None]:
    """Every guarded variable, with ``None`` meaning "not set at all".

    The key set is the union of what is currently exported and the tracked
    names, recomputed on each call. That union is what makes both failure
    directions visible: a name the SDK *added* appears in the later snapshot and
    not the earlier one, and a name it *removed* appears in the earlier and not
    the later. Comparing the two dicts catches either.
    """
    names = {name for name in os.environ if name.startswith(_OTEL_PREFIX)}
    names.update(_TRACKED_OTEL_VARIABLES)
    return {name: os.environ.get(name) for name in sorted(names)}


def _absent(snapshot: Mapping[str, str | None]) -> set[str]:
    """The names that were not set. Compared separately from the values."""
    return {name for name, value in snapshot.items() if value is None}


def _present(snapshot: Mapping[str, str | None]) -> dict[str, str]:
    """The names that were set, with their values. Compared separately from absence."""
    return {name: value for name, value in snapshot.items() if value is not None}


def _processor_names(provider: TracerProvider) -> tuple[str, ...]:
    """The class name of every processor attached to ``provider``.

    Reads OpenTelemetry's private ``_active_span_processor._span_processors``,
    which is sanctioned in tests and nowhere else: ``pyproject.toml`` exempts
    ``tests/**`` from ``SLF``, and ``tests/unit/test_private_access_wall.py``
    walks the shipped package precisely so this convenience cannot leak into it.
    There is no public accessor.
    """
    return tuple(
        type(processor).__name__ for processor in provider._active_span_processor._span_processors
    )


def _set_environment(values: Mapping[str, str | None]) -> None:
    """Apply a mapping to the process environment, ``None`` meaning delete.

    Lives in the test module, never in the package. This is the operation CFG-03
    forbids the SDK from performing, and
    :func:`test_no_module_in_the_package_writes_an_otel_variable` proves no
    shipped module performs it.
    """
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# --------------------------------------------------------------------------
# The fixture: three phases, one process.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Phase:
    """One configure call, with the namespace captured on either side of it."""

    #: The snapshot taken immediately before ``configure_tracing``.
    before: Mapping[str, str | None]

    #: The snapshot taken immediately after it returned.
    after: Mapping[str, str | None]

    #: Processor class names on the bridged provider, before and after.
    processors_before: tuple[str, ...]
    processors_after: tuple[str, ...]


@dataclass(frozen=True)
class _Slot:
    """Everything the three phases observed, captured once and asserted many times."""

    #: Configure with the two OTEL variables *unset* beforehand.
    unset: _Phase

    #: Configure with them already carrying the customer's own values.
    preset: _Phase

    #: Configure in the coexistence run, with MLflow dual export enabled.
    coexistence: _Phase

    #: The drift anchor: the processor list MLflow built with an OTLP endpoint
    #: set and ``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`` *not* set.
    processors_without_dual_export: tuple[str, ...]

    #: The processor list with the flag set, for the contrast.
    processors_with_dual_export: tuple[str, ...]

    #: What the customer's own collector received, decoded.
    customer_spans: tuple[ExportedSpan, ...]

    #: Every request the customer's collector captured, for the header scan.
    customer_requests: tuple[CapturedRequest, ...]

    #: What the Revenium collector received, decoded.
    revenium_spans: tuple[ExportedSpan, ...]

    #: Every request the Revenium collector captured, for the header scan.
    revenium_requests: tuple[CapturedRequest, ...]

    #: How many spans the Tracking Server store holds for the coexistence trace.
    store_span_count: int

    #: What ``handle.flush(5.0)`` returned for the coexistence run. Captured
    #: rather than asserted in the fixture so a drained-queue failure fails one
    #: named test instead of erroring every test in this module.
    flush_result: bool

    #: The customer's endpoint and the Revenium endpoint, for the transcript.
    customer_endpoint: str
    revenium_endpoint: str


def _rebuild_provider(mlflow: Any) -> TracerProvider:
    """Force MLflow to re-read the OTLP variables, and hand back the new provider.

    ``disable()`` then ``enable()`` rebuilds the tracer provider — measured, and
    it returns a different object each time. Any test that varies these
    variables needs this, because MLflow reads them once at initialisation and
    would otherwise answer from the provider it built before the variable
    existed.
    """
    mlflow.tracing.disable()
    mlflow.tracing.enable()
    provider: TracerProvider = mlflow.tracing.get_bridged_tracer_provider()
    return provider


def _configure_phase(mlflow: Any, endpoint: str) -> tuple[_Phase, ReveniumExportHandle]:
    """Snapshot, configure, snapshot. The unit of evidence in this module."""
    provider = mlflow.tracing.get_bridged_tracer_provider()
    processors_before = _processor_names(provider)
    before = _otel_snapshot()

    handle = configure_tracing(otlp_traces_endpoint=endpoint, api_key=_FAKE_API_KEY)

    after = _otel_snapshot()
    return (
        _Phase(
            before=before,
            after=after,
            processors_before=processors_before,
            processors_after=_processor_names(provider),
        ),
        handle,
    )


@pytest.fixture(scope="module")
def slot(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Slot]:
    """Three configure calls and one traced span, with the namespace restored after.

    Module-scoped because ``TracerProvider.add_span_processor`` appends and there
    is no public way to detach; per-test attachment would leave a growing stack
    of exporters pointed at collectors that had already closed. Every handle's
    batch processor *is* shut down on teardown, which is what stops later test
    modules' spans from queueing against a socket that is no longer listening.
    """
    database = tmp_path_factory.mktemp("otel-slot") / "tracking.db"
    restore: dict[str, str | None] = {
        name: os.environ.get(name)
        for name in (
            *{name for name in os.environ if name.startswith(_OTEL_PREFIX)},
            *_TRACKED_OTEL_VARIABLES,
            _MLFLOW_DUAL_EXPORT,
            "MLFLOW_TRACKING_URI",
        )
    }
    handles: list[ReveniumExportHandle] = []

    try:
        os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{database}"
        with FakeOTLPCollector() as customer, FakeOTLPCollector() as revenium:
            import mlflow

            # Phase 1 — the variables are unset, and must stay unset.
            _set_environment(dict.fromkeys(_TRACKED_OTEL_VARIABLES))
            _set_environment({_MLFLOW_DUAL_EXPORT: None})
            _rebuild_provider(mlflow)
            unset, handle = _configure_phase(mlflow, revenium.endpoint)
            handles.append(handle)

            # Phase 2 — the customer has already configured their own collector,
            # and the dual-export flag is deliberately *not* set. This is the
            # drift anchor: MLflow replaces its Tracking Server processor here.
            _set_environment(
                {
                    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": customer.endpoint,
                    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
                    "OTEL_EXPORTER_OTLP_TRACES_HEADERS": (f"{_CUSTOMER_HEADER}={_CUSTOMER_TOKEN}"),
                }
            )
            provider = _rebuild_provider(mlflow)
            processors_without_dual_export = _processor_names(provider)
            preset, handle = _configure_phase(mlflow, revenium.endpoint)
            handles.append(handle)

            # Phase 3 — the coexistence run. Same customer configuration plus
            # MLflow's dual-export flag, which is what a customer sets to keep
            # their Tracking Server export alongside their OTLP one.
            _set_environment({_MLFLOW_DUAL_EXPORT: "true"})
            provider = _rebuild_provider(mlflow)
            processors_with_dual_export = _processor_names(provider)
            customer.reset()
            revenium.reset()
            coexistence, handle = _configure_phase(mlflow, revenium.endpoint)
            handles.append(handle)

            with (
                attribution(subscriber_id="sub-slot", organization_name="org-slot"),
                mlflow.start_span(name=_SPAN_NAME, span_type="CHAT_MODEL") as span,
            ):
                span.set_attribute("mlflow.llm.model", "gpt-4o")
                span.set_attribute("mlflow.llm.provider", "openai")
                span.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))
                trace_id: str = span.trace_id

            # Both flushes, and they are not interchangeable. ``handle.flush``
            # drains this SDK's own BatchSpanProcessor; the provider-level flush
            # is what drains MLflow's OtelSpanProcessor to the customer's
            # collector; and ``flush_trace_async_logging`` drains MLflow's own
            # background thread to the Tracking Server. Three destinations, three
            # flushes — conflating any two is how an assertion ends up running
            # before the POST it is asserting about.
            flush_result = handle.flush(5.0)
            provider.force_flush(20000)
            mlflow.flush_trace_async_logging()

            trace = mlflow.get_trace(trace_id)
            yield _Slot(
                unset=unset,
                preset=preset,
                coexistence=coexistence,
                processors_without_dual_export=processors_without_dual_export,
                processors_with_dual_export=processors_with_dual_export,
                customer_spans=tuple(customer.exported_spans()),
                customer_requests=customer.requests,
                revenium_spans=tuple(revenium.exported_spans()),
                revenium_requests=revenium.requests,
                store_span_count=0 if trace is None else len(trace.data.spans),
                flush_result=flush_result,
                customer_endpoint=customer.endpoint,
                revenium_endpoint=revenium.endpoint,
            )
    finally:
        # Reached through the private attribute deliberately: handle lifecycle is
        # plan 04-04's decision, and inventing a public ``shutdown()`` here as
        # test scaffolding would pre-empt it with a convenience.
        for installed in handles:
            installed._batch_processor.shutdown()
        _set_environment(restore)
        # The provider is process-global and outlives this module. Rebuilding it
        # after the variables are restored is what stops a later module from
        # inheriting an OTLP endpoint pointed at a collector that has closed.
        import mlflow

        _rebuild_provider(mlflow)


# --------------------------------------------------------------------------
# CFG-03: the namespace is byte-identical across configure_tracing().
# --------------------------------------------------------------------------


def test_the_namespace_is_byte_identical_when_it_was_unset(slot: _Slot) -> None:
    """Nothing was set, and nothing is set afterwards.

    The full-mapping comparison is the claim; the two assertions after it are
    what stop it from passing vacuously. A mapping that never mentioned the two
    variables would compare equal to itself while telling you nothing.
    """
    assert slot.unset.before == slot.unset.after
    assert set(_TRACKED_OTEL_VARIABLES) <= _absent(slot.unset.before)
    assert _absent(slot.unset.before) == _absent(slot.unset.after)


def test_absence_is_asserted_separately_from_equality(slot: _Slot) -> None:
    """Absent-stays-absent, as its own statement about the two named variables.

    Separate from the dict comparison above on purpose. ``before == after`` is
    satisfied by an implementation that set nothing *and* by one that set
    something and unset it again; this is satisfied only by the first.
    """
    for name in _TRACKED_OTEL_VARIABLES:
        assert slot.unset.before[name] is None, name
        assert slot.unset.after[name] is None, name

    # And the same snapshot machinery reports two of those names as *present* in
    # the coexistence phase, so "absent" above is a measurement rather than a
    # mapping that simply never mentioned them.
    assert _absent(slot.coexistence.before).isdisjoint(
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS"}
    )


def test_the_namespace_is_byte_identical_when_the_customer_had_already_set_it(
    slot: _Slot,
) -> None:
    """The customer's values survive configuration character for character.

    This is the case that matters in production: a customer with their own OTLP
    collector already configured. An SDK that "helpfully" pointed the endpoint
    at Revenium would redirect their traffic and leak its credential into their
    headers variable in the same move.
    """
    assert slot.preset.before == slot.preset.after
    present = _present(slot.preset.before)
    assert present["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] == slot.customer_endpoint
    assert present["OTEL_EXPORTER_OTLP_TRACES_HEADERS"] == (f"{_CUSTOMER_HEADER}={_CUSTOMER_TOKEN}")
    assert _present(slot.preset.after) == present


def test_the_endpoint_variable_never_becomes_the_revenium_endpoint(slot: _Slot) -> None:
    """The specific substitution, asserted directly rather than inferred.

    ``before == after`` would also hold for an SDK that wrote the Revenium
    endpoint into a variable that already happened to contain it. Naming the
    value makes the claim independent of the comparison.
    """
    for phase in (slot.unset, slot.preset, slot.coexistence):
        for snapshot in (phase.before, phase.after):
            for name, value in _present(snapshot).items():
                assert slot.revenium_endpoint not in value, (name, value)


def test_the_credential_never_reaches_the_headers_variable(slot: _Slot) -> None:
    """T-04-09, asserted over every guarded variable in all three phases.

    The headers variable is the one whose contents an OTLP exporter sends as
    authentication to whatever endpoint it is pointed at. This is the assertion
    that the Revenium key is never in it.
    """
    for phase in (slot.unset, slot.preset, slot.coexistence):
        for snapshot in (phase.before, phase.after):
            for name, value in _present(snapshot).items():
                assert _FAKE_API_KEY.lower() not in value.lower(), (name, value)


def test_configuring_added_this_sdks_two_processors_and_removed_none(slot: _Slot) -> None:
    """The SDK adds; it does not replace. The contrast with MLflow's own behaviour.

    Asserted as a delta rather than a presence, because MLflow already attaches
    processors of its own and a test that only checked "a BatchSpanProcessor is
    attached" would pass against an MLflow that had attached one itself.
    """
    for phase in (slot.unset, slot.preset, slot.coexistence):
        added = [name for name in phase.processors_after if name not in phase.processors_before]
        assert "ReveniumAttributionSpanProcessor" in added
        assert "BatchSpanProcessor" in added
        for name in phase.processors_before:
            assert name in phase.processors_after, name


def test_mlflow_replaces_rather_than_adds_when_the_endpoint_variable_is_set(
    slot: _Slot,
) -> None:
    """The drift anchor, and the reason CFG-03 is a demo-critical requirement.

    With an OTLP endpoint set and ``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT``
    unset, MLflow's Tracking Server processor is **absent** from the provider —
    it was replaced, not supplemented. An SDK that wrote that variable would
    silently switch off the customer's Tracking Server export.

    Pinned so that a future MLflow which starts adding rather than replacing
    fails the build. That failure is the intended outcome: the reasoning that
    made this requirement urgent would otherwise be invisible to whoever is here
    then, and this test names it.
    """
    assert "MlflowV3SpanProcessor" not in slot.processors_without_dual_export
    assert "OtelSpanProcessor" in slot.processors_without_dual_export
    # And with the flag set, both are there — which is what makes the sentence
    # above about *replacement* rather than about OTLP support in general.
    assert "MlflowV3SpanProcessor" in slot.processors_with_dual_export
    assert "OtelSpanProcessor" in slot.processors_with_dual_export


# --------------------------------------------------------------------------
# Three destinations, one run.
# --------------------------------------------------------------------------


def test_all_three_destinations_received_something(slot: _Slot) -> None:
    """The non-vacuity control, asserted before anything reads a payload.

    Every content assertion below is a comprehension over one of these
    collections, and a comprehension over an empty list satisfies all of them at
    once. This test is what fails when a destination stopped receiving.
    """
    assert slot.flush_result is True, "this SDK's own batch processor did not drain in time"
    assert slot.customer_spans, "the customer's own collector received nothing"
    assert slot.revenium_spans, "the Revenium collector received nothing"
    assert slot.store_span_count == 1, slot.store_span_count


def test_the_customers_own_collector_received_the_span(slot: _Slot) -> None:
    """A customer who configured their own OTLP endpoint keeps receiving at it."""
    assert [span.name for span in slot.customer_spans] == [_SPAN_NAME]


def test_the_revenium_collector_received_its_own_copy(slot: _Slot) -> None:
    """And Revenium receives the same span, in the same run, at its own endpoint."""
    assert [span.name for span in slot.revenium_spans] == [_SPAN_NAME]


def test_the_two_copies_differ_in_exactly_the_way_that_justifies_this_exporter(
    slot: _Slot,
) -> None:
    """The customer's copy is untranslated; Revenium's is filtered and translated.

    This difference is the whole reason this SDK owns an exporter rather than
    setting ``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`` and pointing MLflow at
    Revenium. The customer's payload carries MLflow's own ``mlflow.*`` vocabulary
    and no ``gen_ai.*`` at all; Revenium's carries normalised ``gen_ai.*``
    including the cache-token key MLflow's own native dual export drops.
    """
    customer = slot.customer_spans[0]
    revenium = slot.revenium_spans[0]

    assert "mlflow.chat.tokenUsage" in customer.attributes
    assert not [key for key in customer.attributes if key.startswith("gen_ai.")]

    assert revenium.attributes["gen_ai.usage.input_tokens"] == _USAGE["input_tokens"]
    assert (
        revenium.attributes["gen_ai.usage.cache_read_input_tokens"]
        == _USAGE["cache_read_input_tokens"]
    )
    assert "mlflow.chat.tokenUsage" not in revenium.attributes

    # The resource claim, which is the second of the two losses in MLflow's own
    # native dual export. Its value is ``revenium-mlflow-sdk`` rather than the
    # model provider: plan 04-01 established that the resource-level claim names
    # the emitting SDK, while the *span*-level ``gen_ai.provider.name`` carries
    # the provider. Asserted as the measured value rather than the intuitive one,
    # and asserted absent from the customer's copy, which is what makes this a
    # statement about the two destinations differing.
    assert revenium.resource_attributes["gen_ai.provider.name"] == "revenium-mlflow-sdk"
    assert revenium.attributes["gen_ai.provider.name"] == "openai"
    assert "gen_ai.provider.name" not in customer.resource_attributes


def test_every_export_from_either_destination_was_addressed_to_loopback(slot: _Slot) -> None:
    """T-04-02, asserted off the captured requests rather than off the fixture source.

    A collector edited to bind a routable address fails here instead of
    exfiltrating, and reading the ``Host`` header means this is about where the
    client sent the bytes rather than where a server intended to listen.
    """
    hosts = {request.host for request in (*slot.customer_requests, *slot.revenium_requests)}

    assert hosts == {"127.0.0.1"}, hosts


# --------------------------------------------------------------------------
# The header scan, in both directions.
# --------------------------------------------------------------------------


def _header_hits(requests: tuple[CapturedRequest, ...], needle: str) -> list[tuple[str, str]]:
    """Every header whose name or value contains ``needle``, case-insensitively.

    Both name and value, because a credential smuggled into a header *name*
    would be just as exposed, and case-insensitively because HTTP header names
    are case-insensitive on the wire and a value's casing is not something this
    assertion should depend on.
    """
    lowered = needle.lower()
    return [
        (name, value)
        for request in requests
        for name, value in request.headers.items()
        if lowered in name.lower() or lowered in value.lower()
    ]


def test_the_scan_finds_the_credential_on_reveniums_requests(slot: _Slot) -> None:
    """The capability proof, and it comes first for a reason.

    A leak scan that has never located the thing it searches for is a scan that
    would report clean against a real leak. This asserts the instrument works
    before the next test uses it to assert an absence.
    """
    hits = _header_hits(slot.revenium_requests, _FAKE_API_KEY)

    assert hits, "the scan found the credential nowhere, so its clean result below means nothing"
    assert [name for name, _ in hits] == ["x-api-key"], hits


def test_the_credential_appears_in_no_request_the_customer_received(slot: _Slot) -> None:
    """T-04-09 on captured traffic: the Revenium key never reaches the customer's collector."""
    assert slot.customer_requests, "no customer request captured, so this asserts nothing"
    assert _header_hits(slot.customer_requests, _FAKE_API_KEY) == []


def test_the_customers_own_token_reaches_only_their_collector(slot: _Slot) -> None:
    """The mirror image, which fails if this SDK ever forwards the environment's headers.

    The customer's token lives in ``OTEL_EXPORTER_OTLP_TRACES_HEADERS``. An SDK
    that read that variable and passed it to its own exporter — a plausible
    convenience — would send the customer's credential to Revenium. Asserting
    both directions means neither leak can land silently.
    """
    assert _header_hits(slot.customer_requests, _CUSTOMER_TOKEN)
    assert _header_hits(slot.revenium_requests, _CUSTOMER_TOKEN) == []


# --------------------------------------------------------------------------
# The transcript, pinned to a live run.
# --------------------------------------------------------------------------


def test_the_verification_document_records_what_this_run_measured(slot: _Slot) -> None:
    """The transcript and the live measurement stay one fact.

    A checked-in transcript rots the moment someone upgrades MLflow, and a
    rotted transcript is worse than none: it reads as current evidence for a
    measurement nobody re-ran. The same circularity is handled the same way in
    ``tests/unit/test_stamp_time_evidence.py`` and
    ``docs/verification/attr-02-stamp-time.md``.

    Whitespace is collapsed on both sides. The document's tables are
    column-aligned for a human reader and the alignment is not the fact.
    """
    import mlflow

    assert _EVIDENCE_DOCUMENT.is_file(), f"{_EVIDENCE_DOCUMENT} is missing"
    document = _EVIDENCE_DOCUMENT.read_text(encoding="utf-8")
    collapsed = " ".join(document.split())

    assert mlflow.__version__ in document, (
        f"{_EVIDENCE_DOCUMENT.name} does not name the installed MLflow "
        f"({mlflow.__version__}); the transcript in it was produced against something else."
    )

    required = (
        " ".join(str(name) for name in slot.processors_without_dual_export),
        " ".join(str(name) for name in slot.processors_with_dual_export),
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        f"{_CUSTOMER_HEADER}={_CUSTOMER_TOKEN}",
        _FAKE_API_KEY,
    )
    missing = [line for line in required if line not in collapsed]

    assert missing == [], (
        f"{_EVIDENCE_DOCUMENT.name} no longer records what this run measured. "
        f"Absent from it: {missing}. Re-run the reproducer in its section 2 and paste "
        "the new output, rather than editing the tables by hand."
    )
