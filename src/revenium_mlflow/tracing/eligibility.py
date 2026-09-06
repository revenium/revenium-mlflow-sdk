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
Path A first, and *exclusively*: a span that states its own operation is
classified on that operation alone, so an ``execute_tool`` span is rejected even
when it also carries an allowlisted ``mlflow.spanType``. An instrumentor's own
assertion about what it did is better evidence than a type mapping, and falling
through to the type after rejecting the operation would let the weaker signal
overturn the stronger one. Both paths then run the same token-evidence gate.

**Phases 3, 4 and 8 all call this same function object.** FB-05's claim that
eligibility is decided exactly once is auditable only because there is exactly
one function to call — so :func:`is_billable_llm_span` stays a ``bool``-returning
function with this signature, and :func:`classify_span` is a second view of the
same decision rather than a replacement for it.

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

import enum as _enum
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
    "KNOWN_MLFLOW_SPAN_TYPES",
    "EligibilityReason",
    "classify_span",
    "is_billable_llm_span",
]

#: Every span type MLflow declares, transcribed as plain string literals with no
#: MLflow reference at runtime (D-05). Nothing in this module's decision consults
#: it — an unrecognized type is rejected structurally by non-membership of
#: :data:`BILLABLE_MLFLOW_SPAN_TYPES`, so runtime behaviour is identical whether
#: or not this set is current.
#:
#: **It exists so that a sixteenth MLflow span type fails the build and names
#: itself (D-06).** ``tests/unit/test_mlflow_vocabulary_drift.py`` compares this
#: literal against the installed MLflow on every leg of the version matrix. A new
#: span type is a billing decision nobody has made yet, and going red is what
#: forces someone to make it; reporting and continuing would leave a possibly
#: billable type sitting rejected indefinitely, which is a silent under-bill. The
#: failure is therefore always a red build and never a wrong invoice.
KNOWN_MLFLOW_SPAN_TYPES: _Final[frozenset[str]] = frozenset(
    {
        "AGENT",
        "CHAIN",
        "CHAT_MODEL",
        "EMBEDDING",
        "EVALUATOR",
        "GUARDRAIL",
        "LLM",
        "MEMORY",
        "PARSER",
        "RERANKER",
        "RETRIEVER",
        "TASK",
        "TOOL",
        "UNKNOWN",
        "WORKFLOW",
    }
)

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
#:
#: **On the two cache fields (D-12), corrected.** MLflow normalizes cache tokens
#: *into* ``input_tokens`` rather than adding to it — the Anthropic and Bedrock
#: paths subtract nothing and report the provider's inclusive count
#: (``mlflow/anthropic/autolog.py:194-200``), and OpenAI and Gemini report them
#: that way natively. A fully-cached call therefore measures as
#: ``input_tokens: 900, cache_read_input_tokens: 900`` and is already admitted on
#: the input count alone. The two cache fields still earn their place here for
#: two narrower reasons: ``mlflow/langchain/utils/chat.py:42-55`` is a flat key
#: rename with no arithmetic, so the subset relation is not guaranteed on that
#: path, and a future integration could report a cache count with no input count
#: at all. Do not restate this as "cache tokens rescue a fully-cached call that
#: would otherwise be dropped" — that claim is checkable and false, and a false
#: comment is how a correct guard comes to be deleted.
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


class EligibilityReason(str, _enum.Enum):
    """Why one span was admitted or dropped — exactly three answers (D-10).

    **The gate's failure mode is otherwise invisible.** A genuinely billable span
    that arrives without token counts is dropped, and a dropped span looks
    exactly like nothing happening: no error, no log, no metric, and an invoice
    quietly smaller than it should be. "N allowlisted spans dropped for missing
    tokens" is the one number that reveals a mis-tuned gate, and it cannot be
    computed from a ``bool``.

    D-10 considered a debug log at the rejection site and rejected it: that would
    put I/O inside a pure module called from a ``SpanProcessor`` hot path, and
    debug logging is off in exactly the deployments where this number matters.
    The reason is returned instead, and Phase 6 counts it.

    ``str``-valued rather than a bare :class:`enum.Enum` so a member is both
    printable and directly usable as a dict key in that counter, with no
    conversion step for a caller to get wrong.
    """

    ADMITTED = "ADMITTED"
    WRONG_TYPE = "WRONG_TYPE"
    NO_TOKEN_EVIDENCE = "NO_TOKEN_EVIDENCE"


def _has_token_evidence(attributes: _Mapping[str, object], /) -> bool:
    """At least one positive integer count, in either spelling (D-09, D-11, D-12).

    Positive, not merely present: a usage mapping reporting zero on every field
    is dropped rather than rated as a zero-cost completion, and ``bool`` is
    excluded before ``int`` so a ``True`` where a count belongs is not evidence.

    The gate runs on **both** paths rather than on Path B only. Two paths with
    different admission rules would need explaining forever, and the gate is the
    second line of defence against a ``CHAT_MODEL``-typed orchestration wrapper
    that the type allowlist alone would wave through.
    """
    usage = _spanattrs.decode_mapping(attributes, _spanattrs.MLFLOW_CHAT_USAGE)
    if usage is not None and any(
        _spanattrs.is_positive_int(usage.get(field)) for field in _MLFLOW_TOKEN_FIELDS
    ):
        return True
    return any(_spanattrs.is_positive_int(attributes.get(key)) for key in _GENAI_TOKEN_ATTRIBUTES)


def _token_verdict(attributes: _Mapping[str, object], /) -> EligibilityReason:
    """The tail both paths share, once the type or operation has been admitted."""
    if _has_token_evidence(attributes):
        return EligibilityReason.ADMITTED
    return EligibilityReason.NO_TOKEN_EVIDENCE


def classify_span(span: _ReadableSpan, /) -> EligibilityReason:
    """Why this span is or is not billable — the whole decision, in one place.

    Args:
        span: Any span the host process produced.

    Returns:
        :attr:`EligibilityReason.ADMITTED`, :attr:`EligibilityReason.WRONG_TYPE`
        or :attr:`EligibilityReason.NO_TOKEN_EVIDENCE`, and nothing else.

    **Type first, then tokens.** The ordering is what makes SEM-11 structural
    rather than incidental: an orchestration span is rejected on its type before
    the token gate is ever consulted, so a ``CHAIN`` span carrying a thousand
    input tokens is still ``WRONG_TYPE`` and can never be admitted by the
    aggregate counts it duplicates from the model spans nested inside it.

    **The asymmetry that sets the gate's strictness (D-09).** A wrongly-rejected
    span can be re-admitted later by loosening this gate, and the customer sees a
    correction. A wrongly-billed one cannot be un-billed — the invoice is out.
    Every close call here is therefore decided towards rejection.

    Comparison is exact-match over the decoded string. There is no case folding,
    no whitespace stripping and no Unicode normalization anywhere in it, so
    ``chat_model`` and ``CHAT_MODEL `` are both rejected. That is a decision
    about equality, not an oversight: a "helpful" ``.strip().upper()`` would make
    the allowlist match strings nobody put on it.

    This returns a decision on **every** input and raises on none. A malformed
    attribute on one span must not fail the export batch it happens to be in
    (T-02-05).
    """
    attributes: _Mapping[str, object] = span.attributes or {}

    # Path A — the span states its own operation, and that statement is final.
    operation = attributes.get(_GEN_AI_OPERATION_NAME)
    if isinstance(operation, str):
        if operation not in BILLABLE_GENAI_OPERATIONS:
            return EligibilityReason.WRONG_TYPE
        return _token_verdict(attributes)

    # Path B — MLflow's span type, decoded through the one shared decoder so this
    # predicate and the mapper cannot disagree about what the span says.
    span_type = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_SPAN_TYPE)
    if span_type is None or span_type not in BILLABLE_MLFLOW_SPAN_TYPES:
        return EligibilityReason.WRONG_TYPE
    return _token_verdict(attributes)


def is_billable_llm_span(span: _ReadableSpan, /) -> bool:
    """Whether this span represents model usage Revenium should bill for.

    Args:
        span: Any span the host process produced.

    Returns:
        ``True`` only for an allowlisted operation or span type that also shows
        positive token evidence.

    The identity comparison against :attr:`EligibilityReason.ADMITTED`, and
    deliberately nothing more. Phase 3's ``on_start``, Phase 4's exporter and
    Phase 8's fallback all call this signature; only diagnostics wants the
    reason. Re-deriving the answer here would be a second predicate to keep in
    sync with :func:`classify_span`, which is the failure this SDK spends a
    shared decoder to prevent one layer down.
    """
    return classify_span(span) is EligibilityReason.ADMITTED
