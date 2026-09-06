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
cache added later for speed would break that silently, which is what the
``ThreadPoolExecutor`` comparison is for.

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


def test_concurrent_mapping_equals_serial_mapping() -> None:
    """Phase 3 calls ``map_span`` from a ``SpanProcessor`` callback, concurrently.

    ``map_span`` is a pure function over its arguments, and this test is what
    keeps it one. A module-level cache added later for speed would break it
    silently — two spans mapped at once would exchange values, and the result is
    a customer billed for another customer's model. Comparing against serial
    results rather than merely asserting no exception was raised is the point:
    a race that corrupts values raises nothing.
    """
    spans: Sequence[ReadableSpan] = [
        mlflow_chat_model_span(
            model=f"gpt-4o-{index}",
            usage={"input_tokens": index, "output_tokens": index * 2},
            outputs={"id": f"chatcmpl-{index}", "choices": [{"finish_reason": "stop"}]},
        )
        for index in range(1, 33)
    ]
    serial = [map_span(span, environment=_ENVIRONMENT, region=_REGION) for span in spans]
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent = list(
            pool.map(lambda span: map_span(span, environment=_ENVIRONMENT, region=_REGION), spans)
        )
    assert concurrent == serial
