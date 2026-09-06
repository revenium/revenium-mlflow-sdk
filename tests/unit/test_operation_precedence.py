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
"""

import json

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from revenium_mlflow.tracing.eligibility import EligibilityReason, classify_span
from revenium_mlflow.tracing.semconv import map_span
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
