"""Which spans are billed, decided by a positive allowlist and nothing else.

**This is a one-way door (D-09).** The predicate decides what a customer is
charged for. Loosening it after ship starts billing traffic that was previously
free; tightening it stops billing traffic already invoiced. Neither is
correctable retroactively, because the invoices are already out. That is why the
gate is an allowlist rather than a denylist: an unknown span type is rejected
*structurally*, by not being a member of a positive set, rather than by having
been thought of in advance.

**Two paths, in order.** Path A is a span that already carries
``gen_ai.operation.name`` — a bridged non-MLflow OpenTelemetry instrumentor, or a
span MLflow has already translated. Path B is MLflow's own ``mlflow.spanType``.
Path A first, because an instrumentor's own assertion about what it did is better
evidence than a type mapping. Both paths then run the same token-evidence gate.

**Phases 3, 4 and 8 all call this same function object.** FB-05's claim that
eligibility is decided exactly once is auditable only because there is exactly
one function to call — so this stays a ``bool``-returning function with this
signature, and the typed rejection reason lives in a sibling rather than
replacing it.

**Nothing here imports MLflow, at runtime, ever (D-05).** MLflow's ``SpanType``
members are themselves plain strings, so there is nothing to gain by importing
them; ``mlflow.entities.span`` pulls roughly 495 submodules in about 0.9 seconds;
and this predicate runs inside a ``SpanProcessor`` callback for every span in the
host process. The vocabulary is declared as string literals, and a test that
*does* import MLflow asserts the literals still agree with it — the drift check
belongs in the suite, not in the shipped import graph.

Everything is imported under a private alias so this module's public surface is
exactly the names in ``__all__``.
"""

from collections.abc import Mapping as _Mapping
from typing import Final as _Final

from opentelemetry.sdk.trace import ReadableSpan as _ReadableSpan

from . import _spanattrs
from .semconv import GEN_AI_OPERATION_NAME as _GEN_AI_OPERATION_NAME
from .semconv import GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS as _GEN_AI_CACHE_CREATION_TOKENS
from .semconv import GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS as _GEN_AI_CACHE_READ_TOKENS
from .semconv import GEN_AI_USAGE_INPUT_TOKENS as _GEN_AI_INPUT_TOKENS
from .semconv import GEN_AI_USAGE_OUTPUT_TOKENS as _GEN_AI_OUTPUT_TOKENS

__all__ = [
    "BILLABLE_GENAI_OPERATIONS",
    "BILLABLE_MLFLOW_SPAN_TYPES",
    "is_billable_llm_span",
]

#: The three MLflow span types that bill. Set-equal to the types MLflow's own
#: table maps to an operation it declares ``CLIENT`` — which is what makes
#: "every admitted span is emitted as ``SpanKind.CLIENT``" a consequence of one
#: table rather than a second rule. The orchestration types — ``CHAIN``,
#: ``RETRIEVER``, ``TOOL``, ``AGENT`` — are absent on purpose: they carry
#: aggregate token counts that duplicate the model spans nested inside them, and
#: admitting one would bill the same tokens twice.
BILLABLE_MLFLOW_SPAN_TYPES: _Final[frozenset[str]] = frozenset(
    {
        "CHAT_MODEL",
        "LLM",
        "EMBEDDING",
    }
)

#: The four GenAI operations that bill, for a span that arrives already carrying
#: one. Set-equal to the operations MLflow declares ``SpanKind.CLIENT``.
#: ``text_completion`` is here and is *not* a value of MLflow's span-type table —
#: it reaches the SDK only from a bridged non-MLflow instrumentor, which is
#: exactly who Path A exists for. ``execute_tool`` and ``invoke_agent`` are the
#: two MLflow declares ``INTERNAL``, and they are absent for the same
#: double-counting reason the orchestration types are.
BILLABLE_GENAI_OPERATIONS: _Final[frozenset[str]] = frozenset(
    {
        "chat",
        "generate_content",
        "text_completion",
        "embeddings",
    }
)

#: The fields inside a decoded ``mlflow.chat.tokenUsage`` that count as evidence.
#: ``total_tokens`` is deliberately excluded: it is derived from the others, and
#: admitting a span on a derived field weakens a one-way-door predicate for
#: nothing at all.
_MLFLOW_TOKEN_FIELDS: _Final[tuple[str, ...]] = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

#: The same four counts in their flat ``gen_ai`` spelling, for a Path A span that
#: never went through MLflow's usage normalization.
_GENAI_TOKEN_ATTRIBUTES: _Final[tuple[str, ...]] = (
    _GEN_AI_INPUT_TOKENS,
    _GEN_AI_OUTPUT_TOKENS,
    _GEN_AI_CACHE_READ_TOKENS,
    _GEN_AI_CACHE_CREATION_TOKENS,
)


def _has_token_evidence(attributes: _Mapping[str, object], /) -> bool:
    """At least one positive integer count, in either spelling (D-09, D-11, D-12).

    A cached-read or cache-creation count is evidence **on its own**, alongside
    input and output. Cached tokens are billed tokens at a different rate, so
    rejecting a heavily-cached call would drop precisely the prompt-caching
    customer this phase exists to protect — converting the overbill it fixes into
    an underbill.
    """
    usage = _spanattrs.decode_mapping(attributes, _spanattrs.MLFLOW_CHAT_USAGE)
    if usage is not None and any(
        _spanattrs.is_positive_int(usage.get(field)) for field in _MLFLOW_TOKEN_FIELDS
    ):
        return True
    return any(_spanattrs.is_positive_int(attributes.get(key)) for key in _GENAI_TOKEN_ATTRIBUTES)


def is_billable_llm_span(span: _ReadableSpan, /) -> bool:
    """Whether this span represents model usage Revenium should bill for.

    Args:
        span: Any span the host process produced.

    Returns:
        ``True`` only for an allowlisted operation or span type that also shows
        positive token evidence.

    This returns a decision on **every** input and raises on none. A malformed
    attribute on one span must not fail the export batch it happens to be in
    (T-02-05).
    """
    attributes: _Mapping[str, object] = span.attributes or {}

    # Path A — the span states its own operation.
    operation = attributes.get(_GEN_AI_OPERATION_NAME)
    if isinstance(operation, str) and operation in BILLABLE_GENAI_OPERATIONS:
        return _has_token_evidence(attributes)

    # Path B — MLflow's span type, decoded through the one shared decoder so this
    # predicate and the mapper cannot disagree about what the span says.
    span_type = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_SPAN_TYPE)
    if span_type is not None and span_type in BILLABLE_MLFLOW_SPAN_TYPES:
        return _has_token_evidence(attributes)

    return False
