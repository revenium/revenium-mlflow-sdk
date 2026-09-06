"""The gate and the mapper name the same operation, on every span, in both directions.

**Why this file exists (GAP-1).** ``eligibility.classify_span`` admitted a span on
``gen_ai.operation.name`` exclusively while ``semconv._operation`` emitted an
operation derived from ``mlflow.spanType`` first — opposite precedence on the
same two signals, each defended by a docstring asserting it was the correct one.
A span carrying ``gen_ai.operation.name="chat"`` and ``mlflow.spanType="EMBEDDING"``
was therefore admitted as a chat completion and invoiced as an embeddings call.
Chat and embeddings rate differently, so the divergence was a billing
misattribution and not a cosmetic inconsistency. It shipped green because no test
in the phase mapped a span carrying **both** signals — every existing case
supplies exactly one, which is the shape on which the two rules happen to agree.

The structural fix is one shared resolver, ``semconv.operation_for_span``,
consulted by both modules. These tests are what stops it being re-split: each one
asserts *agreement between the two functions*, never the behaviour of one of them
alone. A test of ``map_span`` by itself would have passed against the defect, and
so would a test of ``classify_span`` by itself.

**The sweep derives its own subject list.** ``tests/unit/test_semconv_allowlist.py``
established that pattern for the emit allowlist and the *shape* is copied here,
not the module. Building the subject list from every public helper
``tests/fixtures/spans.py`` exports means a helper added by a later plan joins the
sweep without anyone remembering to add it, and
:func:`test_the_agreement_sweep_reaches_every_helper_the_fixture_module_exports`
is the non-vacuity control that makes the sweep's silence mean something — a sweep
that reached nothing would pass every assertion in it.

**Cross-function agreement alone cannot fail, so the sweep also holds an
independent copy of the rule.** Once ``map_span`` and ``classify_span`` both
delegate to ``operation_for_span``, "the three agree" is true by construction and
would stay true under any precedence planted inside the shared resolver. The third
assertion in the sweep is therefore a statement this file makes on its own: when a
span declares a ``str`` ``gen_ai.operation.name``, the resolved operation **is**
that value. That is what reds if span-type-first precedence is ever put back, and
it is why :data:`_REQUIRED_ARGUMENTS` builds a swept span that carries both signals
with deliberately disagreeing values — without such a subject the assertion would
be vacuously true. ``tests/unit/test_eligibility.py`` records the same reasoning
for the fifteen-row verdict table: a test that imports its expectation from the
module under test agrees with every future edit to it.

**:data:`_REQUIRED_ARGUMENTS` below is this module's own copy, deliberately.** It
is not imported from ``test_semconv_allowlist``: this repository's house style
keeps each expectation independent of the thing it checks, and a shared copy would
let one edit satisfy two guards at once — which is how two guards become one.
"""

import inspect
import json
from collections.abc import Callable, Mapping
from typing import NamedTuple

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from revenium_mlflow.tracing.eligibility import (
    BILLABLE_GENAI_OPERATIONS,
    EligibilityReason,
    classify_span,
)
from revenium_mlflow.tracing.semconv import map_span, operation_for_span
from tests.fixtures import spans as span_fixtures
from tests.fixtures.spans import build_readable_span

pytestmark = pytest.mark.unit

#: Integer nanoseconds for the one-off shapes built directly from
#: :func:`build_readable_span`. ``tests/fixtures/spans.py`` is plan 02-01's and is
#: imported unmodified here; its docstring says a shape too narrow to earn a named
#: helper is built at the call site, and "a span carrying both signals" is that
#: shape — it exists to be wrong in one specific way and nothing else needs it.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000

#: The emitted key both halves of every assertion below read.
_OPERATION_KEY = "gen_ai.operation.name"


def _both_signals_span(*, operation: str, span_type: str, input_tokens: int = 10) -> ReadableSpan:
    """A span stating its own operation **and** carrying an MLflow span type.

    ``gen_ai.*`` values are bare and ``mlflow.*`` values are JSON-encoded, which
    is the division of labour ``tests/fixtures/spans.py`` documents: MLflow
    serializes every attribute it writes, a bridged OpenTelemetry instrumentor
    does not, and this span is exactly the collision of the two.
    """
    return build_readable_span(
        attributes={
            _OPERATION_KEY: operation,
            "mlflow.spanType": json.dumps(span_type),
            "gen_ai.usage.input_tokens": input_tokens,
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


# --- The two directions GAP-1 names ----------------------------------------


def test_a_both_signals_span_is_emitted_under_the_operation_it_was_admitted_on() -> None:
    """The reproduced defect, asserted as one statement about agreement.

    Both halves live in one test on purpose. Split across two, each half would
    pass on the defective code — ``classify_span`` genuinely returned
    ``ADMITTED`` and ``map_span`` genuinely returned an operation. What was
    wrong was the relationship between them, so that is what is asserted.
    """
    span = _both_signals_span(operation="chat", span_type="EMBEDDING")

    assert classify_span(span) is EligibilityReason.ADMITTED
    assert map_span(span).attributes[_OPERATION_KEY] == "chat"


def test_a_tool_operation_on_an_allowlisted_type_is_rejected_and_never_relabelled_chat() -> None:
    """The reverse direction: the span type must not rescue a non-billable operation.

    Mapping a span the gate rejected is deliberate here, and it is the only place
    in this suite that happens. ``map_span``'s contract is that it is called on
    admitted spans, so this is not a supported call — it is the probe that proves
    the mapper carries no *second opinion* about the operation. If it emitted
    ``chat`` for a span admitted-as-nothing on ``execute_tool``, the two functions
    would still hold two rules, and the next edit that admitted such a span for
    any reason would invoice it as a chat completion.
    """
    span = _both_signals_span(operation="execute_tool", span_type="CHAT_MODEL")

    assert classify_span(span) is EligibilityReason.WRONG_TYPE
    assert map_span(span).attributes[_OPERATION_KEY] == "execute_tool"


# --- The swept subject list, derived rather than listed ---------------------

#: Arguments for the fixture helpers that have required parameters, so every
#: exported helper can be called by the sweep. Explicit and asserted complete: a
#: helper that grows a required parameter fails
#: :func:`test_the_agreement_sweep_reaches_every_helper_the_fixture_module_exports`
#: until someone decides what to pass it, rather than dropping out unnoticed.
#:
#: The ``build_readable_span`` entry is the sweep's one **both-signals** subject
#: and it is deliberately self-contradictory: a bare ``gen_ai.operation.name`` of
#: ``embeddings`` against a JSON-encoded ``mlflow.spanType`` of ``CHAT_MODEL``,
#: whose table value is ``chat``. The two signals therefore name different
#: operations, which is what gives the precedence assertion something to be wrong
#: about. A subject on which both rules agree would make it vacuous.
_REQUIRED_ARGUMENTS: Mapping[str, Mapping[str, object]] = {
    "build_readable_span": {
        "attributes": {
            _OPERATION_KEY: "embeddings",
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "gen_ai.usage.input_tokens": 12,
        },
        "start_time_ns": _START_NS,
        "end_time_ns": _END_NS,
    },
    "mlflow_typed_span": {"span_type": "CHAT_MODEL"},
    "error_span": {"marker": "sweep-marker"},
}

#: The four usage fields that count as evidence, and their flat ``gen_ai``
#: spelling. Written out here rather than imported from ``eligibility``: the
#: sweep's expectation about *which spans the gate should admit* has to be
#: independent of the module computing the answer, or it agrees with every
#: future edit to that module.
_TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
_FLAT_TOKEN_KEYS: tuple[str, ...] = tuple(f"gen_ai.usage.{field}" for field in _TOKEN_FIELDS)


def _exported_helpers() -> dict[str, Callable[..., ReadableSpan]]:
    """Every public span helper the shared fixture module defines.

    Derived rather than listed, and filtered on ``__module__`` so a name the
    fixture module merely imported could never be mistaken for a helper.
    """
    return {
        name: value
        for name, value in vars(span_fixtures).items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        and value.__module__ == span_fixtures.__name__
    }


def _helper_spans() -> dict[str, ReadableSpan]:
    """One span per exported helper, with required parameters supplied."""
    return {
        name: helper(**_REQUIRED_ARGUMENTS.get(name, {}))
        for name, helper in _exported_helpers().items()
    }


def _is_positive_count(value: object) -> bool:
    """A genuine positive integer count. ``bool`` is excluded before ``int``."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _carries_token_evidence(attributes: Mapping[str, object]) -> bool:
    """Whether this span shows at least one positive count, in either spelling.

    An independent re-implementation, not a call into ``eligibility``. It reads
    the JSON-encoded MLflow usage mapping and the four bare ``gen_ai.usage.*``
    attributes, which is the whole vocabulary; anything else is not evidence.
    """
    serialized = attributes.get("mlflow.chat.tokenUsage")
    if isinstance(serialized, str):
        try:
            usage = json.loads(serialized)
        except ValueError:
            usage = None
        if isinstance(usage, dict) and any(
            _is_positive_count(usage.get(field)) for field in _TOKEN_FIELDS
        ):
            return True
    return any(_is_positive_count(attributes.get(key)) for key in _FLAT_TOKEN_KEYS)


# --- The sweep -------------------------------------------------------------


def test_every_fixture_agrees_on_the_operation_between_the_gate_and_the_mapper() -> None:
    """Every helper the shared builder exports, checked in all three directions.

    Offenders are collected and reported by name rather than asserted one at a
    time, so a failure says *which* fixture disagreed and how, instead of
    reporting a bare ``False`` about a span nobody can identify from the output.
    """
    offenders: list[str] = []

    for name, span in _helper_spans().items():
        attributes: Mapping[str, object] = span.attributes or {}
        resolved = operation_for_span(attributes)
        emitted = map_span(span).attributes.get(_OPERATION_KEY)

        # The mapper labels the span with the resolved operation, and omits the
        # key entirely when there is nothing to say.
        expected_emitted = resolved if resolved else None
        if emitted != expected_emitted:
            offenders.append(f"{name}: mapper emitted {emitted!r}, resolver said {resolved!r}")

        # The gate admits on that same resolution plus token evidence, and on
        # nothing else.
        admitted = classify_span(span) is EligibilityReason.ADMITTED
        should_admit = resolved in BILLABLE_GENAI_OPERATIONS and _carries_token_evidence(attributes)
        if admitted is not should_admit:
            offenders.append(
                f"{name}: gate admitted={admitted}, resolver said {resolved!r} "
                f"with token evidence={_carries_token_evidence(attributes)}"
            )

        # The independent copy of the rule: a declared operation wins outright.
        declared = attributes.get(_OPERATION_KEY)
        if isinstance(declared, str) and resolved != declared:
            offenders.append(
                f"{name}: span declared {declared!r} but the resolver said {resolved!r} — "
                "the declared GenAI operation must win over mlflow.spanType (UD-1)"
            )

    assert sorted(offenders) == [], sorted(offenders)


def test_the_agreement_sweep_reaches_every_helper_the_fixture_module_exports() -> None:
    """Non-vacuity. A sweep that silently reached nothing passes everything above."""
    missing = {
        name
        for name, helper in _exported_helpers().items()
        if {
            parameter.name
            for parameter in inspect.signature(helper).parameters.values()
            if parameter.default is inspect.Parameter.empty
        }
        - set(_REQUIRED_ARGUMENTS.get(name, {}))
    }
    assert missing == set(), (
        f"{sorted(missing)} have required parameters with no entry in _REQUIRED_ARGUMENTS, "
        "so they would drop out of the sweep. Add the arguments rather than the exclusion."
    )
    assert len(_helper_spans()) != 0


# --- The two SEM-10 edges ---------------------------------------------------


def test_an_empty_attribute_mapping_is_wrong_type() -> None:
    """A span saying nothing is rejected, and is never admitted by default.

    The empty input is the case a predicate written as a denylist gets wrong, and
    the reason the gate is membership of a positive set: there is no operation to
    resolve, so there is nothing for the allowlist to contain.
    """
    span = build_readable_span(attributes={}, start_time_ns=_START_NS, end_time_ns=_END_NS)

    assert classify_span(span) is EligibilityReason.WRONG_TYPE
    assert operation_for_span({}) is None


@pytest.mark.parametrize("span_type", ["chat_model", "CHAT_MODEL "])
def test_operation_and_type_comparison_is_exact_over_the_decoded_string(span_type: str) -> None:
    """Wrong case and one trailing space are both rejected, and that is a decision.

    Membership is exact-match over the decoded string: no case folding, no
    whitespace stripping, no Unicode normalization, in either the resolver or the
    gate. A "helpful" ``.strip().upper()`` would make a one-way-door billing
    allowlist match strings nobody put on it — admitting traffic on a typo. This
    is not an oversight left for a later tidy-up.
    """
    span = span_fixtures.mlflow_typed_span(span_type=span_type)

    assert classify_span(span) is EligibilityReason.WRONG_TYPE
    assert operation_for_span(span.attributes or {}) is None


# --- The recorded admission decision, made mechanical (plan 02-07) -----------
#
# Plan 02-07's `checkpoint:decision` carried `gate="blocking-human"` and was
# answered `decode-everywhere`: every `gen_ai.*` attribute the SDK reads now goes
# through `_spanattrs`, and the admission surface widens as a consequence. The
# two tables below are that answer written down as data. `_spanattrs.decode_int`
# carries the same decision in prose; this file is where it is executable.


class _VerdictChange(NamedTuple):
    """One span shape the decoder change moved, and where it moved it.

    ``encodings`` holds every attribute mapping that expresses this one shape.
    Shape 3 is a single shape — "the declared operation holds valid JSON that is
    not a JSON string" — with three encodings, and each is named so a run that
    goes red names the encoding rather than the group.
    """

    encodings: Mapping[str, Mapping[str, object]]
    before: EligibilityReason
    after: EligibilityReason


class _VerdictControl(NamedTuple):
    """One span shape the decision left alone, and the verdict it must still carry."""

    attributes: Mapping[str, object]
    verdict: EligibilityReason


#: The five span shapes whose verdict moved, each with the verdict it carried
#: before the change and the verdict it carries now. Nothing outside this table
#: was permitted to move.
_VERDICT_CHANGES: Mapping[str, _VerdictChange] = {
    "shape1_json_string_billable_op": _VerdictChange(
        encodings={
            "shape1_json_string_billable_op": {
                _OPERATION_KEY: json.dumps("chat"),
                "gen_ai.usage.input_tokens": 10,
            }
        },
        before=EligibilityReason.WRONG_TYPE,
        after=EligibilityReason.ADMITTED,
    ),
    "shape2_empty_op_billable_type": _VerdictChange(
        encodings={
            "shape2_empty_op_billable_type": {
                _OPERATION_KEY: "",
                "mlflow.spanType": json.dumps("CHAT_MODEL"),
                "gen_ai.usage.input_tokens": 10,
            }
        },
        before=EligibilityReason.WRONG_TYPE,
        after=EligibilityReason.ADMITTED,
    ),
    "shape3_non_string_json_op": _VerdictChange(
        encodings={
            "shape3_json_number_op": {
                _OPERATION_KEY: "123",
                "mlflow.spanType": json.dumps("CHAT_MODEL"),
                "gen_ai.usage.input_tokens": 10,
            },
            "shape3_json_true_op": {
                _OPERATION_KEY: "true",
                "mlflow.spanType": json.dumps("CHAT_MODEL"),
                "gen_ai.usage.input_tokens": 10,
            },
            "shape3_json_list_op": {
                _OPERATION_KEY: "[1]",
                "mlflow.spanType": json.dumps("CHAT_MODEL"),
                "gen_ai.usage.input_tokens": 10,
            },
        },
        before=EligibilityReason.WRONG_TYPE,
        after=EligibilityReason.ADMITTED,
    ),
    "shape4_json_encoded_count": _VerdictChange(
        encodings={
            "shape4_json_encoded_count": {
                _OPERATION_KEY: "chat",
                "gen_ai.usage.input_tokens": json.dumps(10),
            }
        },
        before=EligibilityReason.NO_TOKEN_EVIDENCE,
        after=EligibilityReason.ADMITTED,
    ),
    # The fifth entry is the half of shape 1 that carries no token evidence. It
    # is still rejected, so it is not part of the widening the decision accepted
    # — but its *reason code* moves, and D-10 exists because that code is the one
    # number a mis-tuned gate is visible in. A reason change nobody recorded is a
    # reason change nobody can attribute later.
    "shape5_json_string_op_without_tokens": _VerdictChange(
        encodings={"shape5_json_string_op_without_tokens": {_OPERATION_KEY: json.dumps("chat")}},
        before=EligibilityReason.WRONG_TYPE,
        after=EligibilityReason.NO_TOKEN_EVIDENCE,
    ),
}

#: The four controls. Each is a near neighbour of a shape above that must **not**
#: have moved, which is what makes the change bounded rather than a blanket
#: widening: a decoder that simply admitted more would take these with it.
_VERDICT_UNCHANGED: Mapping[str, _VerdictControl] = {
    "control_json_encoded_non_billable_op": _VerdictControl(
        attributes={
            _OPERATION_KEY: json.dumps("execute_tool"),
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "gen_ai.usage.input_tokens": 10,
        },
        verdict=EligibilityReason.WRONG_TYPE,
    ),
    "control_bare_non_string_op": _VerdictControl(
        attributes={
            _OPERATION_KEY: 123,
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "gen_ai.usage.input_tokens": 10,
        },
        verdict=EligibilityReason.ADMITTED,
    ),
    "control_json_encoded_true_count": _VerdictControl(
        attributes={
            _OPERATION_KEY: "chat",
            "gen_ai.usage.input_tokens": json.dumps(True),
        },
        verdict=EligibilityReason.NO_TOKEN_EVIDENCE,
    ),
    "control_bare_integer_count": _VerdictControl(
        attributes={
            _OPERATION_KEY: "chat",
            "gen_ai.usage.input_tokens": 10,
        },
        verdict=EligibilityReason.ADMITTED,
    ),
}


def _verdict_cases() -> list[tuple[str, Mapping[str, object], EligibilityReason]]:
    """Both tables flattened to (name, attributes, the verdict that must hold now)."""
    cases: list[tuple[str, Mapping[str, object], EligibilityReason]] = [
        (name, attributes, change.after)
        for change in _VERDICT_CHANGES.values()
        for name, attributes in change.encodings.items()
    ]
    cases.extend(
        (name, control.attributes, control.verdict) for name, control in _VERDICT_UNCHANGED.items()
    )
    return cases


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        pytest.param(attributes, expected, id=name)
        for name, attributes, expected in _verdict_cases()
    ],
)
def test_every_enumerated_shape_carries_the_verdict_the_decision_recorded(
    attributes: Mapping[str, object], expected: EligibilityReason
) -> None:
    """The tables above are the recorded decision made mechanical.

    Routing the ``gen_ai.*`` reads through the shared decoder changes which spans
    are billed, and ``ROADMAP.md``'s Phase 2 note fences that off as a one-way
    door. The decision naming the shapes that move is therefore only worth as
    much as its closure: a *sixth* shape quietly changing verdict is completely
    invisible to a suite that asserts only the five that were decided. That is
    what :data:`_VERDICT_UNCHANGED` is for — the controls are near neighbours of
    the shapes that moved, so a decoder that had simply admitted more would take
    them with it and fail here. Together the two tables make the change bounded
    rather than merely intended.

    The expectations are literals in this file, never imported from
    ``eligibility``. A table read out of the module under test agrees with every
    future edit to it, including the edit that widens a billing predicate.
    """
    span = build_readable_span(attributes=attributes, start_time_ns=_START_NS, end_time_ns=_END_NS)

    assert classify_span(span) is expected


def test_every_recorded_change_moved_and_no_shape_is_named_twice() -> None:
    """``before`` is load-bearing, not decoration, and the tables do not overlap.

    An entry whose recorded ``before`` equals its ``after`` is a shape that did
    not actually move, and it would pad the change set with a case that proves
    nothing while making the enumeration look more thorough than it is. A name
    appearing in both tables would claim the same shape both moved and held.
    """
    stationary = [
        name for name, change in _VERDICT_CHANGES.items() if change.before is change.after
    ]
    assert stationary == [], stationary

    changed_names = {name for change in _VERDICT_CHANGES.values() for name in change.encodings}
    assert changed_names.isdisjoint(_VERDICT_UNCHANGED)


def test_a_json_encoded_operation_reaches_the_wire_without_literal_quotes() -> None:
    """T-02-07-02: the form this project's constraints record as backend-dropping.

    Before the decoder change this span emitted ``'"chat"'`` — the operation with
    its JSON quotes still attached, which is the exact shape CLAUDE.md names for
    ``mlflow.tracing.configure`` ("emits ``'"org-A"'`` with literal quotes;
    backend drops/mis-stores"). Equality against ``"chat"`` alone would pass on a
    value that had been stripped by some other means, so the absence of the
    quote character is asserted as well.
    """
    span = build_readable_span(
        attributes={_OPERATION_KEY: json.dumps("chat"), "gen_ai.usage.input_tokens": 10},
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )

    emitted = map_span(span).attributes[_OPERATION_KEY]

    assert emitted == "chat"
    assert '"' not in str(emitted)
