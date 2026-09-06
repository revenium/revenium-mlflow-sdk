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
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.trace.status import Status, StatusCode
from opentelemetry.util.types import AttributeValue

from revenium_mlflow.tracing import semconv
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

#: The finish reasons this file expects ``semconv`` to accept, as a literal.
#: Compared set-equal to ``semconv._KNOWN_FINISH_REASONS`` below, and never
#: imported from it: a test that read the module's own set would agree with every
#: future edit to the set, and the set is exactly what must not change unnoticed.
#: Grouped by the provider vocabulary each member came from, so a drift failure
#: names a vocabulary rather than a bare string.
_EXPECTED_FINISH_REASONS = frozenset(
    {
        # OpenAI chat completions.
        "stop",
        "length",
        "tool_calls",
        "content_filter",
        "function_call",
        # OpenAI Responses.
        "completed",
        "incomplete",
        "failed",
        "cancelled",
        "in_progress",
        # Anthropic.
        "end_turn",
        "max_tokens",
        "stop_sequence",
        "pause_turn",
        "refusal",
    }
)

#: The character cap this file expects, held as a literal for the same reason.
#: It is used to *build* the boundary values below, so if the module's figure
#: ever moves in either direction the boundary tests red: raise the module cap
#: and the 65-character value stops being omitted; lower it and the 64-character
#: value stops being emitted.
_MAX_EMITTED_VALUE_CHARS = 64

#: The GAP-2 reproductions, transcribed from 02-VERIFICATION.md so the tests
#: below run against the recorded evidence rather than a paraphrase of it. The
#: credential is synthetic and always was — no live key appears in this file.
_CREDENTIAL_STATUS = "https://user:rev_sk_SUPERSECRET@api.internal.example.com/v1 failed: 401"
_CREDENTIAL_SUBSTRING = "rev_sk_SUPERSECRET"
_CLINICAL_STATUS = "The patient's diagnosis is terminal cancer."


def _rendered(value: Any) -> str:
    """One attribute value as text, so a tuple's elements are searched too.

    ``gen_ai.response.finish_reasons`` is a tuple of strings. A substring test
    against the tuple object would still work through ``repr``, but saying so
    explicitly keeps the guard from depending on a repr detail — the same
    reasoning ``tests/unit/test_semconv_allowlist.py`` records for its own copy.
    """
    if isinstance(value, (tuple, list)):
        return "\n".join(str(item) for item in value)
    return str(value)


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


# --- Class A: the finish-reason value constraint (plan 02-08, GAP-2) --------
#
# Three reproductions from 02-VERIFICATION.md, each of which reached
# ``gen_ai.response.finish_reasons`` verbatim against the shipped tree: a
# credential embedded in a URL, a 50,000-character string, and a sentence of
# clinical content. All three are non-members of ``_KNOWN_FINISH_REASONS``, so
# one membership test closes all three — which is why the human answering the
# plan's checkpoint chose an enum over a shape rule.


def test_the_finish_reason_allowlist_matches_this_files_independent_copy() -> None:
    """The literal comparison — the assertion a silent widening cannot agree with.

    Widening ``_KNOWN_FINISH_REASONS`` changes what reaches the billing wire, and
    the change is not recoverable: a reason dropped at emit time was never sent,
    so spans before and after carry different value populations for one rated
    key. A test that imported the set would agree with any such edit.
    """
    ours = set(semconv._KNOWN_FINISH_REASONS)
    theirs = set(_EXPECTED_FINISH_REASONS)
    assert ours == theirs, (
        "_KNOWN_FINISH_REASONS no longer matches this file's independent copy. "
        f"Present in the module and not here: {sorted(ours - theirs)}. "
        f"Present here and not in the module: {sorted(theirs - ours)}."
    )


def test_a_free_text_status_is_not_a_finish_reason() -> None:
    """A sentence at ``outputs["status"]`` is response-body text, not a reason.

    ``mlflow.spanOutputs`` on a ``@mlflow.trace``-decorated function is that
    function's serialized return value — an arbitrary application dict, not an
    OpenAI Responses enum — so the ``("status", None)`` row was reading free text
    one function away from ``_error_type``, which refuses to read the status
    description precisely *because* it is free text.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"status": _CLINICAL_STATUS},
        }
    )
    assert "gen_ai.response.finish_reasons" not in map_span(span).attributes


def test_a_credential_bearing_status_reaches_no_emitted_value() -> None:
    """T-02-08-01, asserted across every emitted value rather than one key.

    Naming ``gen_ai.response.finish_reasons`` alone would pass just as well if
    the constraint moved the credential to some other key. The sweep is over the
    whole mapping, tuple elements included, because the requirement is that the
    credential leaves the process nowhere — CLAUDE.md's redaction rule is about
    the value, not about a key.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"status": _CREDENTIAL_STATUS},
        }
    )
    offenders = sorted(
        f"{key}={value!r}"
        for key, value in map_span(span).attributes.items()
        if _CREDENTIAL_SUBSTRING in _rendered(value)
    )
    assert offenders == [], offenders


def test_a_fifty_thousand_character_status_emits_no_finish_reason_key() -> None:
    """The unbounded-length reproduction, and it is absent rather than truncated.

    Absent, not an empty tuple and not a shortened string: an empty tuple ships
    as a present key carrying no answer, and a truncated one would ship a reason
    the provider never reported.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"status": "A" * 50000},
        }
    )
    assert "gen_ai.response.finish_reasons" not in map_span(span).attributes


# --- Class B: the character cap, asserted from both sides (SEM-06 encoding) -
#
# Every case below asserts the boundary twice: a value at exactly the cap is
# emitted *and* carries its full value, and a value one code point longer is
# absent. Without the at-cap half a blanket drop would satisfy every one of them,
# which is the same failure mode the recorded-zero token test exists to close.


def _inputs_model_span(value: str) -> ReadableSpan:
    """A span whose only model name is ``inputs["model"]``.

    No ``mlflow.llm.model``, deliberately: with the shared fallback present, an
    over-cap inputs model would fall through to it and the request-model key
    would be filled from another source — a correct behaviour that would make
    this test assert nothing about the cap.
    """
    return _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanInputs": {"model": value},
        }
    )


def _outputs_model_span(value: str) -> ReadableSpan:
    """The same shape one field over, for the response model."""
    return _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"model": value},
        }
    )


def _recorded_model_span(value: str) -> ReadableSpan:
    """A span whose only model name is the shared ``mlflow.llm.model`` fallback.

    This source never passes through ``_mapping_model``, so it is the one Class B
    path a cap applied only inside that helper would miss entirely. It fills both
    model keys, which is why it appears twice in the parametrization.
    """
    return _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.llm.model": value,
        }
    )


def _declared_operation_span(value: str) -> ReadableSpan:
    """A Path A span declaring its own operation, with bare attributes.

    Bare rather than JSON-encoded because these are real OpenTelemetry attributes
    written by a bridged instrumentor that never heard of MLflow. It carries no
    ``mlflow.spanType``, so nothing rescues the key when the cap rejects the
    declared value.
    """
    return build_readable_span(
        attributes={"gen_ai.operation.name": value, "gen_ai.usage.input_tokens": 5},
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


#: Every Class B key, paired with a span factory that makes the named field the
#: *only* source for it. ``gen_ai.response.id`` has its own test above, which
#: additionally asserts the at-cap value is emitted whole rather than shortened.
_CLASS_B_CASES: tuple[tuple[str, Callable[[str], ReadableSpan]], ...] = (
    ("gen_ai.request.model", _inputs_model_span),
    ("gen_ai.response.model", _outputs_model_span),
    ("gen_ai.request.model", _recorded_model_span),
    ("gen_ai.response.model", _recorded_model_span),
    ("gen_ai.operation.name", _declared_operation_span),
)


def test_an_over_length_response_id_is_omitted_rather_than_truncated() -> None:
    """A truncated response id is a *wrong* response id, which is the worse failure.

    The id is how a disputed charge is traced back to a call in the provider's own
    console. An absent id costs the customer that trace; a plausible-but-wrong one
    costs them the trace *and* sends them looking for a call that does not exist.
    So the over-cap value is rejected outright — and the at-cap assertion in the
    same test is what proves the rejection is a boundary rather than a blanket
    drop, and that the value that survives survives whole.
    """
    over = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"id": "x" * (_MAX_EMITTED_VALUE_CHARS + 1)},
        }
    )
    at_cap = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": dict(_USAGE),
            "mlflow.spanOutputs": {"id": "x" * _MAX_EMITTED_VALUE_CHARS},
        }
    )
    assert "gen_ai.response.id" not in map_span(over).attributes
    assert map_span(at_cap).attributes["gen_ai.response.id"] == "x" * _MAX_EMITTED_VALUE_CHARS


@pytest.mark.parametrize(("key", "build"), _CLASS_B_CASES)
def test_every_class_b_key_is_omitted_one_character_over_the_cap(
    key: str, build: Callable[[str], ReadableSpan]
) -> None:
    """The remaining three Class B keys, each bounded at its own source.

    Class B keys carry the provider's or the span's own identifier and are
    constrained by length and by nothing else — an allowlist would drop every
    model this SDK has not heard of, which is every new model. Length is
    therefore the whole control on these keys, so the boundary is asserted rather
    than assumed, on both sides and at every source that can fill the key.
    """
    at_cap_value = "c" * _MAX_EMITTED_VALUE_CHARS
    over_value = "c" * (_MAX_EMITTED_VALUE_CHARS + 1)

    assert map_span(build(at_cap_value)).attributes.get(key) == at_cap_value
    assert key not in map_span(build(over_value)).attributes


# --- Token counts on the emit path (WR-02, T-02-08-03) ---------------------


def test_a_negative_token_count_reaches_no_emitted_attribute() -> None:
    """``-7`` is not a measurement; it is a broken integration.

    ``_spanattrs.is_positive_int`` already rejects negatives for the gate, and
    ``tests/unit/test_spanattrs.py`` asserts it does. The emit path applied no
    equivalent rule, so a span admitted on a positive ``input_tokens`` carried a
    negative ``output_tokens`` to the wire — landing as a silent credit or a
    corrupted total depending on backend arithmetic.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": {"input_tokens": 5, "output_tokens": -7},
        }
    )
    attributes = map_span(span).attributes
    assert "gen_ai.usage.output_tokens" not in attributes
    # Non-vacuity: the span really was mapped, and the sibling count survived.
    assert attributes["gen_ai.usage.input_tokens"] == 5


def test_a_recorded_zero_token_count_still_reaches_the_wire() -> None:
    """The other half of the same rule, so neither can be satisfied by a blanket drop.

    A recorded zero is a measurable fact: the provider reported no tokens for
    that field, and this SDK emits what MLflow recorded and computes nothing.
    Dropping it would be the easy over-reach that makes the negative-count test
    above pass for the wrong reason.
    """
    span = _mlflow_span(
        {
            "mlflow.spanType": "CHAT_MODEL",
            "mlflow.llm.model": "gpt-4o",
            "mlflow.chat.tokenUsage": {"input_tokens": 0, "output_tokens": 0},
        }
    )
    emitted = map_span(span).attributes["gen_ai.usage.input_tokens"]
    assert emitted == 0
    # ``isinstance(True, int)`` is true, so the zero must be proven a real int.
    assert type(emitted) is int


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
