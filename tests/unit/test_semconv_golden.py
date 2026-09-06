"""One representative inference span, asserted key by key against a literal golden record.

Criterion 3 names fourteen items — provider, request model, response model,
operation, finish reason, error/status, trace id, span id, parent span id, start,
end, duration, environment and region — and asks for them asserted key by key.
That is what this file does, and the drifts it exists to catch are specific:

*Silent key drift.* A key renamed in ``semconv.py`` — ``gen_ai.response.model``
to ``gen_ai.model.response``, ``deployment.environment.name`` to
``deployment.environment`` — is invisible to a test that imports the constant it
renamed. The expectation below is a **literal**, the rule
``tests/unit/test_attributes.py`` states in its own docstring, and it is the
whole value of the file: a test written against the module agrees with every
future edit to the module.

*Silent key addition.* A thirteenth attribute added to the emitted mapping is
the leak shape D-04's allowlist exists to prevent, and it passes every per-key
assertion because no per-key assertion looks at keys it does not name. The
key-set assertion is what catches it.

*Content leaking through an error.* A marker planted in an exception message is
asserted **present on the span first** and absent from the output second. A
clean result is exactly what a check inspecting nothing also produces, so the
subject is proven known-dirty before the absence means anything — the discipline
``tests/fixtures/planted_private_access.py`` records for the private-access
scanner.

*Purity lost to a cache.* ``map_span`` is called from a ``SpanProcessor``
callback under whatever concurrency the host application has. A module-level
cache added later for speed would break that silently. Four checks cover this,
not one: the ``ThreadPoolExecutor`` comparison, a structural scan of the
module's own bindings, a repeat-mapping check, and a batch-wide distinctness
check. The comparison alone was **proven inert** by 02-VERIFICATION.md's
plant-and-revert — a memoizing cache satisfies it, because the serial pass
populates the cache and the concurrent pass reads it back — so the other three
are what give the set teeth. See :func:`test_concurrent_mapping_equals_serial_mapping`.

The division of labour with ``tests/unit/test_semconv_derivations.py`` is
deliberate: that file asserts each derivation in isolation against a shape built
to exercise it, this one asserts one span's whole output at once. A case
belonging there is not moved here — a golden record built on a representative
span reaches exactly one branch of each derivation.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
from opentelemetry.util.types import AttributeValue

from revenium_mlflow.tracing import semconv
from revenium_mlflow.tracing.semconv import MappedSpan, map_span
from tests.fixtures.spans import build_readable_span, error_span, mlflow_chat_model_span

pytestmark = pytest.mark.unit

#: The captured span's timings, restated as literals. Their difference is the
#: expected duration below, so the duration assertion compares two different
#: numbers rather than zero to zero.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000
_DURATION_NS = 45980000

#: The environment and region the golden span is mapped with. Supplied as
#: arguments (D-C6) rather than read from configuration, which is Phase 4's job.
_ENVIRONMENT = "prod"
_REGION = "us-east-1"

#: The response the golden span carries, shaped like an OpenAI chat completion.
#: ``model`` here differs from ``mlflow.llm.model`` on purpose: on the OpenAI
#: path that attribute holds the *response* model, and the request model lives in
#: the inputs. A fixture where the two agreed would make the SEM-03 split
#: untestable at the golden level.
_OUTPUTS: Mapping[str, object] = {
    "id": "chatcmpl-9x7Qk1",
    "model": "gpt-4o-2024-08-06",
    "choices": [{"finish_reason": "stop"}],
}

#: The usage dict, transcribed from EXP-5's delivered payload — a real observed
#: attribute set from a working end-to-end run, which is why CONTEXT.md names it
#: as the golden seed rather than a hand-written expectation. ``total_tokens`` is
#: present because MLflow records it; its absence from the expectation below is
#: the assertion that the SDK does not forward it.
_USAGE: Mapping[str, int] = {
    "input_tokens": 11,
    "output_tokens": 7,
    "total_tokens": 18,
    "cache_read_input_tokens": 3,
}

#: **The golden record.** An independent copy of the contract, seeded from EXP-5's
#: delivered payload with the two adjustments the research names: the
#: ``revenium.*`` attribution keys are dropped, because Phase 3 stamps them and
#: this phase neither reads nor emits them; and ``revenium.organization.id`` is
#: not carried forward at all, because it is not one of the 21 recognized keys —
#: ``src/revenium_mlflow/attributes.py`` has ``REVENIUM_ORGANIZATION_NAME`` and no
#: ``.id`` variant.
#:
#: Nothing here is imported from ``semconv.py``. Not the keys, not the values,
#: not ``EMITTED_ATTRIBUTE_KEYS``.
_GOLDEN_ATTRIBUTES: Mapping[str, AttributeValue] = {
    "gen_ai.operation.name": "chat",
    "gen_ai.provider.name": "openai",
    "gen_ai.system": "openai",
    "gen_ai.request.model": "gpt-4o",
    "gen_ai.response.model": "gpt-4o-2024-08-06",
    "gen_ai.response.id": "chatcmpl-9x7Qk1",
    "gen_ai.response.finish_reasons": ("stop",),
    "gen_ai.usage.input_tokens": 11,
    "gen_ai.usage.output_tokens": 7,
    "gen_ai.usage.cache_read_input_tokens": 3,
    "deployment.environment.name": _ENVIRONMENT,
    "cloud.region": _REGION,
}

#: The three token keys the golden span carries. Spelled again rather than
#: filtered out of the mapping above, so a key dropped from the golden record
#: does not silently drop its own type assertion with it.
_TOKEN_KEYS = (
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.cache_read_input_tokens",
)

#: Planted in the exception message. Shaped like a real credential so that a
#: reviewer reading a leak report recognises what it would have been.
_MARKER = "sk-SECRET-should-not-leak"

#: The four mutable containers a module-level accumulator would be built out of.
#: ``frozenset`` and ``MappingProxyType`` are **deliberately absent**: ``semconv``
#: already uses both for tables that must not be widened in a caller's process
#: (``EMITTED_ATTRIBUTE_KEYS``, ``SPAN_TYPE_TO_OPERATION``,
#: ``MESSAGE_FORMAT_PROVIDERS``), so a rule that rejected them would be a rule
#: someone deletes the first time it fires — and deleting it would take the real
#: check with it. Neither is a mutable binding anyway: that is the whole reason
#: the module reaches for them.
_MUTABLE_CONTAINER_TYPES: tuple[type, ...] = (dict, list, set, bytearray)


def _golden_span() -> ReadableSpan:
    """The representative inference span: one real MLflow ``CHAT_MODEL`` shape.

    Built from plan 02-01's shared builder with no modification to it. The
    inputs and outputs are supplied through parameters the builder already
    declares, which is what keeps this file a reader of that fixture rather than
    a second author of it.
    """
    return mlflow_chat_model_span(
        model="gpt-4o-2024-08-06",
        usage=dict(_USAGE),
        inputs={"model": "gpt-4o"},
        outputs=dict(_OUTPUTS),
    )


@pytest.fixture
def golden() -> ReadableSpan:
    """The span itself, so a test can reach its context and its own fields."""
    return _golden_span()


@pytest.fixture
def mapped(golden: ReadableSpan) -> MappedSpan:
    """The golden span, mapped once with environment and region supplied."""
    return map_span(golden, environment=_ENVIRONMENT, region=_REGION)


# --- The eight attribute-carried items of criterion 3 -----------------------


@pytest.mark.parametrize(("key", "expected"), sorted(_GOLDEN_ATTRIBUTES.items()))
def test_the_golden_attribute_is_emitted_exactly(
    mapped: MappedSpan, key: str, expected: AttributeValue
) -> None:
    """Each emitted key carries the value the golden record names, asserted per key.

    Per key rather than as one dict comparison: a single equality on a
    twelve-key mapping prints a diff a reader skims and reports one failure
    where there may be four. A red run is only useful if it names the key.
    """
    assert mapped.attributes.get(key) == expected, f"golden attribute {key!r} does not match"


def test_the_emitted_key_set_is_exactly_the_golden_key_set(mapped: MappedSpan) -> None:
    """A thirteenth key would pass every per-key assertion above.

    That is the leak shape the closed allowlist exists to prevent — a value
    reaching the wire because a new insertion was added and nothing compared the
    whole set. This assertion is the one that fails on an addition.
    """
    assert set(mapped.attributes) == set(_GOLDEN_ATTRIBUTES)


def test_the_golden_span_carries_no_error_type(mapped: MappedSpan) -> None:
    """Criterion 3's error/status item, on a successful call.

    ``error.type`` present on an OK span would put the error rate at 100% and
    make the signal worthless — and it is exactly what an unconditional
    insertion produces.
    """
    assert "error.type" not in mapped.attributes


# --- The six protobuf-field items of criterion 3 ----------------------------


def test_an_internal_mlflow_span_maps_to_client_span_kind(mapped: MappedSpan) -> None:
    """Criterion 5, asserted on the mapper's output rather than on the fixture.

    A real captured MLflow ``CHAT_MODEL`` span is ``SpanKind.INTERNAL`` —
    measured, not assumed — and the GenAI conventions require ``CLIENT`` for an
    inference call. The requirement is about what this SDK emits, not about what
    MLflow produced, so asserting the fixture's kind would answer the wrong
    question.
    """
    assert mapped.kind is SpanKind.CLIENT


def test_the_fixture_the_kind_assertion_rests_on_is_internal(golden: ReadableSpan) -> None:
    """The control for the assertion above: if the fixture were already ``CLIENT``…

    …then the mapper could be doing nothing at all and the criterion-5 test
    would still be green. This is what makes it mean something.
    """
    assert golden.kind is SpanKind.INTERNAL


def test_the_trace_id_is_the_spans_own_trace_id_in_lowercase_hex(
    golden: ReadableSpan, mapped: MappedSpan
) -> None:
    """32 lowercase hex characters, formatted independently of the mapper.

    The backend compares these as strings, so an uppercase or ``0x``-prefixed
    rendering would silently fail to join a span to its trace.
    """
    assert golden.context is not None
    assert mapped.trace_id == format(golden.context.trace_id, "032x")


def test_the_span_id_is_the_spans_own_span_id_in_lowercase_hex(
    golden: ReadableSpan, mapped: MappedSpan
) -> None:
    """The backend uses this as the transaction id, so a wrong rendering forges one."""
    assert golden.context is not None
    assert mapped.span_id == format(golden.context.span_id, "016x")


def test_a_root_span_reports_no_parent_span_id(mapped: MappedSpan) -> None:
    """``None``, not a zero id and not an empty string.

    The backend distinguishes a root from a child on the presence of this field.
    An invented value forges a tree the customer never had.
    """
    assert mapped.parent_span_id is None


def test_a_child_span_reports_its_parents_span_id_in_lowercase_hex() -> None:
    """The other half of the parent-id contract, which no other test in the phase reaches.

    Every fixture-built span in this phase is a root, so the non-root path would
    otherwise ship unexercised — and it is the path that carries the trace
    structure for every inference call made inside an agent or a chain.
    """
    parent = SpanContext(
        trace_id=0x0102030405060708090A0B0C0D0E0F10,
        span_id=0x1122334455667788,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    span = build_readable_span(
        attributes={},
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
        parent=parent,
    )
    assert map_span(span).parent_span_id == "1122334455667788"


def test_the_start_time_is_the_spans_own_integer_nanoseconds(mapped: MappedSpan) -> None:
    """Read off ``ReadableSpan.start_time``, never off ``mlflow.spanStartTimeNs``."""
    assert mapped.start_time_ns == _START_NS


def test_the_end_time_is_the_spans_own_integer_nanoseconds(mapped: MappedSpan) -> None:
    """Read off ``ReadableSpan.end_time`` for the same reason."""
    assert mapped.end_time_ns == _END_NS


def test_the_duration_is_the_difference_of_the_two_timestamps(mapped: MappedSpan) -> None:
    """Derived rather than read, so it cannot disagree with the two fields it comes from."""
    assert mapped.duration_ns == _DURATION_NS


# --- Token typing (SEM-04) -------------------------------------------------


@pytest.mark.parametrize("key", _TOKEN_KEYS)
def test_every_emitted_token_count_is_exactly_int(mapped: MappedSpan, key: str) -> None:
    """An exact type check, not ``isinstance`` — and the difference is not pedantry.

    ``isinstance(True, int)`` is ``True`` in Python, and the OTLP protobuf
    encoder ships such a value as ``bool_value: true``. An ``isinstance``
    assertion would pass on a payload that violates SEM-04, and the backend has
    no way to tell a boolean from a real count (T-02-09).
    """
    assert type(mapped.attributes[key]) is int, f"{key} must be exactly int, not a bool"


# --- The planted-marker control (T-02-01, T-02-02) -------------------------


@pytest.fixture
def planted() -> ReadableSpan:
    """An ERROR span carrying the marker everywhere a real failure would."""
    return error_span(marker=_MARKER)


def test_the_marker_is_present_in_the_spans_status_description(planted: ReadableSpan) -> None:
    """The control subject is proven known-dirty before any absence is asserted.

    A clean scan is exactly what a scan that inspects nothing also produces. If
    the fixture stopped carrying the marker, the two absence assertions below
    would pass forever while proving nothing.
    """
    assert _MARKER in (planted.status.description or "")


def test_the_marker_is_present_in_the_spans_exception_event(planted: ReadableSpan) -> None:
    """The second disclosure surface, also proven dirty first.

    Measured, not imagined: an exception raised inside an MLflow span was
    captured carrying a planted marker verbatim in the event's
    ``exception.message`` attribute, alongside a stacktrace holding absolute
    filesystem paths.
    """
    rendered = [str(event.attributes) for event in planted.events]
    assert any(_MARKER in text for text in rendered)


def test_the_marker_reaches_no_emitted_attribute_value(planted: ReadableSpan) -> None:
    """Nothing from the exception text leaves the customer's process.

    A secret embedded in an exception message reaches Revenium the moment the
    status description or the event message is forwarded. What is not emitted
    cannot leak, which is why the control is a closed allowlist rather than a
    scrubber.
    """
    values = [str(value) for value in map_span(planted).attributes.values()]
    assert [text for text in values if _MARKER in text] == []


def test_the_marker_reaches_no_mapped_span_field(planted: ReadableSpan) -> None:
    """The attributes are not the only thing that leaves — the record's fields do too.

    Asserting only over ``attributes`` would miss a future field carrying a
    status description, which is exactly the addition that would look like an
    improvement in a diff.
    """
    mapped_error = map_span(planted)
    rendered = [
        str(getattr(mapped_error, field.name)) for field in dataclasses.fields(mapped_error)
    ]
    assert [text for text in rendered if _MARKER in text] == []


def test_the_useful_half_of_the_error_survives(planted: ReadableSpan) -> None:
    """``error.type`` still carries the exception class name, in the same run.

    Asserted alongside the absences above so the file proves the control is
    selective rather than merely destructive: dropping everything would satisfy
    the leak assertions and lose the signal SEM-06 asks for.
    """
    assert map_span(planted).attributes["error.type"] == "ValueError"


# --- Purity under concurrency ----------------------------------------------
#
# Four checks, because 02-VERIFICATION.md proved that the first one alone does
# not catch what this section is named for. A module-level ``dict`` accumulator
# was planted in ``semconv.py`` and this whole file stayed green; the plant was
# caught only incidentally, by unrelated key-absence assertions, and only in a
# full-suite run where cross-test contamination accumulates. The three checks
# added below each fail on that plant in a single-file run, and the failing
# direction is proven by transcript rather than inferred from a passing one.


def _batch() -> Sequence[ReadableSpan]:
    """Thirty-two spans, each distinct in the fields the mapper forwards verbatim.

    The distinctness is the instrument, not decoration. ``mlflow.llm.model`` and
    the response ``id`` are Class B values ``map_span`` forwards unchanged, so
    an accumulator that leaked one span's value into another collapses the
    distinct-value count. A batch of thirty-two identical spans would be mapped
    "correctly" by a cache that returned the first result for all of them.
    """
    return [
        mlflow_chat_model_span(
            model=f"gpt-4o-{index}",
            usage={"input_tokens": index, "output_tokens": index * 2},
            outputs={"id": f"chatcmpl-{index}", "choices": [{"finish_reason": "stop"}]},
        )
        for index in range(1, 33)
    ]


def _mapped_concurrently(spans: Sequence[ReadableSpan]) -> list[MappedSpan]:
    """The batch mapped across eight threads, in the caller's order."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(
            pool.map(lambda span: map_span(span, environment=_ENVIRONMENT, region=_REGION), spans)
        )


def test_semconv_holds_no_mutable_module_level_binding() -> None:
    """The structural half: an accumulator has to *be* somewhere, so look there.

    ``semconv``'s own module docstring says it "reads nothing global, caches
    nothing, and mutates nothing" and warns that "a module-level cache added
    later for speed would break that silently". This is that sentence made
    checkable. It walks the module's bindings and rejects any that is an
    instance of :data:`_MUTABLE_CONTAINER_TYPES` — which is what a memoizing
    cache, a seen-set or a growing buffer is built out of.

    Dunder names are skipped because ``__builtins__`` is itself a ``dict`` and
    is not the module's own binding. Offenders are collected as a sorted
    ``name: type`` list so a failure names the planted binding, rather than
    reporting a bare ``False`` about a module with thirty-odd names in it.

    Confirmed clean against the shipped tree before it was written, so it passes
    today for the right reason and has something real to catch.
    """
    offenders = sorted(
        f"{name}: {type(value).__name__}"
        for name, value in vars(semconv).items()
        if not name.startswith("__") and isinstance(value, _MUTABLE_CONTAINER_TYPES)
    )
    assert offenders == [], (
        f"semconv holds mutable module-level bindings {offenders} — under the "
        "SpanProcessor concurrency Phase 3 introduces, two spans mapped at once "
        "can exchange values through any one of them"
    )


def test_mapping_the_same_span_twice_returns_two_distinct_mappings() -> None:
    """The memoization half, and the exact gap the verifier's plant exploited.

    A cache keyed by span satisfies
    :func:`test_concurrent_mapping_equals_serial_mapping` perfectly: the serial
    pass populates it and the concurrent pass reads the identical objects back,
    so the comparison is not merely satisfied, it is satisfied *because* the
    cache is there.

    Equality and identity are asserted together and neither alone is enough.
    Equality without identity is the contract — two calls must agree — and
    identity would mean the second call returned the first call's object rather
    than doing the work again.
    """
    span = _golden_span()
    first = map_span(span, environment=_ENVIRONMENT, region=_REGION)
    second = map_span(span, environment=_ENVIRONMENT, region=_REGION)
    assert first.attributes == second.attributes
    assert first.attributes is not second.attributes


@pytest.mark.parametrize(
    "key",
    ["gen_ai.request.model", "gen_ai.response.model", "gen_ai.response.id"],
)
def test_no_two_spans_in_the_batch_share_an_emitted_model_or_response_id(key: str) -> None:
    """The cross-contamination half: the failure this section exists to prevent, priced.

    Two spans exchanging a model name under concurrency is not an abstract
    purity violation — it is one customer billed for another customer's model,
    on a record that looks correct at the backend. So the assertion is made on
    the emitted values rather than on the mapper's internals, in both passes:
    serial, which pins the fixture as genuinely distinct, and concurrent, which
    is where an accumulator actually leaks.

    The keys are the three Class B values ``map_span`` forwards verbatim. They
    are spelled as literals rather than imported from ``semconv`` for the reason
    this file's docstring gives about the golden record: a test written against
    the module agrees with every future edit to the module.
    """
    spans = _batch()
    serial = [map_span(span, environment=_ENVIRONMENT, region=_REGION) for span in spans]
    for label, mapped in (("serial", serial), ("concurrent", _mapped_concurrently(spans))):
        values = [record.attributes[key] for record in mapped]
        assert len(set(values)) == len(spans), (
            f"{label}: {key} carried {len(set(values))} distinct values across "
            f"{len(spans)} distinct spans — a value crossed between spans"
        )


def test_concurrent_mapping_equals_serial_mapping() -> None:
    """Phase 3 calls ``map_span`` from a ``SpanProcessor`` callback, concurrently.

    Comparing concurrent results against serial ones rather than merely
    asserting that no exception was raised is still worth doing: a race that
    corrupts values raises nothing, and this is the check that sees a genuine
    interleaving disagree with a sequential run.

    **What it does not catch, stated because the claim it used to make was
    disproved.** This test previously said it was "what keeps ``map_span``
    pure". 02-VERIFICATION.md planted a module-level ``dict`` accumulator in
    ``semconv.py`` and this test stayed green — a memoizing cache satisfies it
    by construction, because the serial pass populates the cache and the
    concurrent pass reads the same objects back. Purity is kept by the three
    checks above: the structural scan finds the accumulator itself, the
    repeat-mapping check finds the memoization, and the distinctness check finds
    a value that crossed between spans. This one covers the remaining case —
    interleaving that disagrees with sequential execution — and nothing more.
    """
    spans = _batch()
    serial = [map_span(span, environment=_ENVIRONMENT, region=_REGION) for span in spans]
    assert _mapped_concurrently(spans) == serial
