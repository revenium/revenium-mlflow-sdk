"""Each of ``map_span``'s four derivations, asserted in isolation on a shape built for it.

This file and ``tests/unit/test_semconv_golden.py`` do different jobs and neither
substitutes for the other. The golden record asserts one representative span's
whole output at once, which is what makes the mapping checkable against a single
literal — but a representative span exercises exactly one branch of each
derivation. A wrong finish-reason table, a wrong error fallback, an
``mlflow.spanStartTimeNs`` leaking into the timings or a single-model span
filling only one of the two model keys all pass a golden test built on a span
that never reaches them. A collected count is a count, not a coverage statement.

The five cases with no other home anywhere in this phase are here: the
OpenTelemetry ``_OTHER`` fallback on an ERROR span carrying no exception event,
the finish-reason key omitted rather than emitted as an empty tuple, the two
single-element tuple shapes (OpenAI Responses and Anthropic), a deliberately
wrong ``mlflow.spanStartTimeNs`` changing none of the three timing fields, and a
``mlflow.llm.model``-only span filling both model keys.

**Expected values are literals here, never imported from the module under test.**
That is the rule ``tests/unit/test_attributes.py`` states in its own docstring: a
test asserting the module against the module agrees with every future edit to it,
and the module is exactly what must not change unnoticed. ``_OTHER`` in
particular is spelled out rather than read from ``ERROR_TYPE_UNKNOWN``.

**Narrow one-off shapes are built here, not added to the fixture builder.**
``tests/fixtures/spans.py`` belongs to plan 02-01 whole, and a builder four plans
extend independently is how two fixtures come to disagree about what an MLflow
span looks like. ``build_readable_span`` stores its attributes verbatim and
encodes nothing, so every MLflow-namespaced value below is ``json.dumps``-ed at
the call site — which is also the wire shape MLflow really produces.
"""

import json
from collections.abc import Mapping, Sequence

import pytest
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.util.types import AttributeValue

from revenium_mlflow.tracing.semconv import map_span
from tests.fixtures.spans import build_readable_span, error_span, mlflow_chat_model_span

pytestmark = pytest.mark.unit

#: The captured span's timings, restated here rather than imported from the
#: fixture module's private constants. Their difference is 45_980_000 ns, which
#: is what makes a derived-duration assertion compare two different numbers.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000
_DURATION_NS = 45980000

#: A usage dict, so a span built here is shaped like one the predicate admits.
#: The derivations under test do not read it; a span without it would still be
#: mapped, but it would not be a span this SDK would ever see.
_USAGE: Mapping[str, int] = {"input_tokens": 11, "output_tokens": 7}


def _mlflow_span(
    values: Mapping[str, object],
    *,
    status: Status | None = None,
    events: Sequence[Event] = (),
    start_time_ns: int = _START_NS,
    end_time_ns: int = _END_NS,
) -> ReadableSpan:
    """One span carrying exactly the MLflow attributes a test names, JSON-encoded.

    The encoding is done here because ``build_readable_span`` deliberately does
    none: it must stay able to carry the bare values a bridged non-MLflow
    instrumentor writes. A caller on the MLflow side of that line encodes its
    own values, which this helper does once for every test in the file.
    """
    encoded: dict[str, AttributeValue] = {key: json.dumps(value) for key, value in values.items()}
    return build_readable_span(
        attributes=encoded,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
        status=status,
        events=events,
    )


# --- Model provenance (SEM-03) ---------------------------------------------


def test_the_request_model_comes_from_the_span_inputs_not_the_model_attribute() -> None:
    """``mlflow.llm.model`` is the *response* model on the OpenAI path.

    MLflow's own translator maps it unconditionally to the request key, which is
    wrong there — on Azure OpenAI the request carries a deployment name and the
    response carries the real model, and the two genuinely differ. Inheriting
    that conflation would put a response model in a request field and leave the
    response field to be filled by the same value, so both keys would agree and
    both would be half wrong.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o-2024-08-06-0718",
            "mlflow.spanInputs": {"model": "gpt-4o-2024-08-06"},
            "mlflow.spanOutputs": {"model": "gpt-4o-2024-08-06-0718"},
            "mlflow.chat.tokenUsage": dict(_USAGE),
        }
    )
    assert map_span(span).attributes["gen_ai.request.model"] == "gpt-4o-2024-08-06"


def test_the_response_model_comes_from_the_span_outputs() -> None:
    """The two keys are read from two sources, so they can carry two values.

    If the response model were derived from the same attribute as the request
    model, criterion 3's two golden keys would always agree and the Azure case
    the split exists for would be invisible.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o-2024-08-06-0718",
            "mlflow.spanInputs": {"model": "gpt-4o-2024-08-06"},
            "mlflow.spanOutputs": {"model": "gpt-4o-2024-08-06-0718"},
            "mlflow.chat.tokenUsage": dict(_USAGE),
        }
    )
    assert map_span(span).attributes["gen_ai.response.model"] == "gpt-4o-2024-08-06-0718"


def test_a_single_model_span_fills_the_request_model_key() -> None:
    """With no inputs and no outputs, both keys degrade to MLflow's own behaviour.

    That degradation is a decision, not an accident: the alternative is emitting
    one model key and leaving the other absent, which reads downstream as a
    provider that reported no model rather than as a span MLflow recorded once.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "claude-sonnet-4-5",
            "mlflow.chat.tokenUsage": dict(_USAGE),
        }
    )
    assert map_span(span).attributes["gen_ai.request.model"] == "claude-sonnet-4-5"


def test_a_single_model_span_fills_the_response_model_key() -> None:
    """The other half of the same degradation, asserted separately.

    One test covering both keys would pass while only one of them was filled if
    it asserted a tuple built from the mapping, and would report one failure
    where there are two.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "claude-sonnet-4-5",
            "mlflow.chat.tokenUsage": dict(_USAGE),
        }
    )
    assert map_span(span).attributes["gen_ai.response.model"] == "claude-sonnet-4-5"


# --- Finish reason and response id (SEM-06) --------------------------------


def test_openai_chat_choices_become_a_finish_reason_tuple_in_order() -> None:
    """Order is part of the value: choice *n*'s reason must stay at position *n*.

    A set or a sorted list would silently reassociate reasons with choices, and
    a two-choice response whose first choice hit the token limit would read as
    one that stopped cleanly.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {
                "choices": [{"finish_reason": "stop"}, {"finish_reason": "length"}],
            },
        }
    )
    assert map_span(span).attributes["gen_ai.response.finish_reasons"] == ("stop", "length")


def test_an_openai_responses_status_becomes_a_single_element_tuple() -> None:
    """The OpenAI Responses shape carries no ``choices`` at all.

    It reports a top-level ``status``. Recognising only the chat shape would
    emit no finish reason for every Responses-API call, which is silent: the key
    would simply be absent and nothing downstream distinguishes that from a
    provider that does not report one.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"status": "completed"},
        }
    )
    assert map_span(span).attributes["gen_ai.response.finish_reasons"] == ("completed",)


def test_an_anthropic_stop_reason_becomes_a_single_element_tuple() -> None:
    """Anthropic's shape is a third one, and MLflow normalizes none of the three.

    ``extract_response_attrs`` exists on the OpenAI converter alone, so there is
    no MLflow-provided finish reason to inherit here — the alternative to this
    table row is emitting nothing for every Anthropic call.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "claude-sonnet-4-5",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"stop_reason": "end_turn"},
        }
    )
    assert map_span(span).attributes["gen_ai.response.finish_reasons"] == ("end_turn",)


def test_an_unrecognised_output_shape_leaves_the_finish_reason_absent() -> None:
    """Absent, not an empty tuple. The two are different things on the wire.

    An empty tuple ships as an array with no elements — a present key carrying
    no answer, which reads downstream as "the provider reported no reason"
    rather than as "this SDK did not recognise the shape". Conditional insertion
    exists to keep that distinction, and this is the assertion that holds it.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"ok": True},
        }
    )
    assert "gen_ai.response.finish_reasons" not in map_span(span).attributes


def test_the_response_id_is_read_from_the_outputs_id() -> None:
    """The provider's own id for the response, which is how a charge is traced back.

    Without it a disputed line item can be matched only by timestamp and model,
    and the customer cannot point at the call in their provider's own console.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"id": "chatcmpl-9x7Qk1"},
        }
    )
    assert map_span(span).attributes["gen_ai.response.id"] == "chatcmpl-9x7Qk1"


# --- Error information (SEM-06, D-C7) --------------------------------------


def test_an_error_span_carries_the_exception_class_name() -> None:
    """The class of failure is the whole useful signal that carries no payload.

    Losing it would make every failure indistinguishable at the backend, so the
    security control is "emit only the type", not "emit nothing".
    """
    span = error_span(marker="sk-SECRET-should-not-leak")
    assert map_span(span).attributes["error.type"] == "ValueError"


def test_an_error_span_carries_no_other_error_derived_key() -> None:
    """``error.type`` is the only error information emitted, by construction.

    The status description and the exception event's message and stacktrace were
    measured carrying a planted marker verbatim alongside absolute filesystem
    paths. A second error key added later — a status description, a message, a
    "reason" — is how that reaches Revenium, and it would look like an
    improvement in the diff.
    """
    attributes = map_span(error_span(marker="sk-SECRET-should-not-leak")).attributes
    assert [key for key in attributes if "error" in key or "exception" in key] == ["error.type"]


def test_an_error_status_with_no_exception_event_falls_back_to_the_other_sentinel() -> None:
    """``_OTHER`` is OpenTelemetry's value for an error whose type is unknown.

    Omitting the key instead would lose the fact that the call failed at all,
    and the span would rate as a successful completion. Parsing the status
    description for a type would read free text written by customer code — the
    exact surface the whole error derivation exists to avoid.

    The literal is spelled here rather than imported from ``ERROR_TYPE_UNKNOWN``:
    an assertion against the constant would agree with any future edit to it.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
        },
        status=Status(StatusCode.ERROR, description="RuntimeError: sk-SECRET-should-not-leak"),
    )
    assert map_span(span).attributes["error.type"] == "_OTHER"


def test_an_ok_status_span_carries_no_error_type() -> None:
    """A successful call must not carry an error key at all.

    ``_OTHER`` on every OK span would make the error rate 100% and the signal
    worthless, and it is the shape an unconditional insertion produces.
    """
    assert "error.type" not in map_span(mlflow_chat_model_span()).attributes


# --- Environment and region (SEM-09, D-C6) ---------------------------------


def test_the_environment_is_emitted_when_supplied() -> None:
    """Phase 4 supplies it from configuration; this module takes it as an argument.

    Without the key a customer cannot separate staging spend from production
    spend, which is one of the two dimensions SEM-09 exists for.
    """
    mapped = map_span(mlflow_chat_model_span(), environment="prod", region="us-east-1")
    assert mapped.attributes["deployment.environment.name"] == "prod"


def test_the_region_is_emitted_when_supplied() -> None:
    """The other SEM-09 dimension, asserted separately from the first.

    One test covering both would pass with one key filled and report a single
    failure where there are two independent spellings that can each be wrong.
    """
    mapped = map_span(mlflow_chat_model_span(), environment="prod", region="us-east-1")
    assert mapped.attributes["cloud.region"] == "us-east-1"


def test_the_environment_key_is_absent_when_it_is_not_supplied() -> None:
    """A ``None`` must omit the key, never ship an attribute with no value set.

    The OTLP encoder does not reject ``None`` — it emits an ``AnyValue`` with no
    field set, and the backend receives a present key with an empty value, which
    reads as an answer rather than as an absence (T-02-08).
    """
    assert "deployment.environment.name" not in map_span(mlflow_chat_model_span()).attributes


def test_the_region_key_is_absent_when_it_is_not_supplied() -> None:
    """The same guarantee for the second key, which has its own insertion site."""
    assert "cloud.region" not in map_span(mlflow_chat_model_span()).attributes


# --- Timings (SEM-08) ------------------------------------------------------
#
# The three tests below all carry a deliberately wrong ``mlflow.spanStartTimeNs``.
# The attribute looks like the right source and is not: it has exactly one setter
# in MLflow and a real captured CHAT_MODEL span does not carry it, so a mapper
# reading it would produce correct timings against a fixture that sets it and no
# timings at all in production.


def test_a_wrong_mlflow_span_start_time_ns_does_not_change_the_start_time() -> None:
    """The span's own ``start_time`` field is the source, and it is nanoseconds already."""
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanStartTimeNs": 1,
        }
    )
    assert map_span(span).start_time_ns == _START_NS


def test_a_wrong_mlflow_span_start_time_ns_does_not_change_the_end_time() -> None:
    """``end_time`` comes off the span too, so a wrong attribute cannot move it."""
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanStartTimeNs": 1,
        }
    )
    assert map_span(span).end_time_ns == _END_NS


def test_a_wrong_mlflow_span_start_time_ns_does_not_change_the_duration() -> None:
    """Duration is derived from the two span fields, so it inherits their source.

    A duration computed against the attribute would be roughly the whole Unix
    epoch, which is not a value anyone reviewing a bill would read as a bug in
    the SDK rather than as a runaway call.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanStartTimeNs": 1,
        }
    )
    assert map_span(span).duration_ns == _DURATION_NS
