"""MLflow span attributes to OpenTelemetry GenAI semantic conventions.

This module is one pure function over one ``ReadableSpan`` and a closed set of
keys it is allowed to emit. It reads nothing global, caches nothing, and mutates
nothing — Phase 3 calls it from a ``SpanProcessor`` callback under whatever
concurrency the host application happens to have, and a module-level cache added
later for speed would break that silently.

**The emit set is an allowlist, not a denylist (D-04).** ``mlflow.spanOutputs``
holds the serialized provider response with completion text in it, and a failing
span's status description and exception event carry raw exception text and
absolute filesystem paths. A denylist stops the leaks someone thought of; a
closed allowlist stops the ones nobody did, because a value cannot escape a set
it is not a member of.

**Nothing is emitted with a ``None`` value.** The OTLP encoder does not reject
one — it ships an ``AnyValue`` with no field set, and the backend receives a
present key with an empty value, which reads as an answer rather than as an
absence. The attribute mapping is therefore built by conditional insertion only
(T-02-08).

**Six of the fourteen things this phase must carry are not attributes.** Kind,
the three ids and the two timestamps live in the protobuf's own span fields and
the backend reads them there (``GenAISemanticConventionMapper.kt:146-148``), so
they are fields of :class:`MappedSpan` rather than duplicated into
``attributes``. The record is internal — ``semconv`` is added to no ``__all__``
above this module, and ``tests/unit/test_public_surface.py`` fails if it is ever
re-exported — so its field list is a same-repo edit that ``mypy --strict`` makes
complete by construction. The *wire* format is the emitted keys, not the record.

**This module does not re-check eligibility.** :func:`map_span` is called only on
spans ``eligibility.is_billable_llm_span`` has already admitted. Re-deriving the
decision here would be a second predicate to keep in sync with the first, which
is the failure D-C1's single shared decoder exists to prevent one layer down.

Nothing here imports MLflow (D-05). Importing ``opentelemetry`` at module scope
is expected and permitted for the same reason ``processor.py`` records: these are
the public locations of the span types, they register no global state, and they
open no socket. Everything is imported under a private alias so this module's
public surface is exactly the names in ``__all__``.
"""

import dataclasses as _dataclasses
import types as _types
from collections.abc import Mapping as _Mapping
from typing import Final as _Final

from opentelemetry.sdk.trace import ReadableSpan as _ReadableSpan
from opentelemetry.trace import SpanKind as _SpanKind
from opentelemetry.util.types import AttributeValue as _AttributeValue

from . import _spanattrs

__all__ = [
    "CLOUD_REGION",
    "DEPLOYMENT_ENVIRONMENT_NAME",
    "EMITTED_ATTRIBUTE_KEYS",
    "ERROR_TYPE",
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_PROVIDER_NAME",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_RESPONSE_FINISH_REASONS",
    "GEN_AI_RESPONSE_ID",
    "GEN_AI_RESPONSE_MODEL",
    "GEN_AI_SYSTEM",
    "GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS",
    "GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS",
    "GEN_AI_USAGE_INPUT_TOKENS",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    "PROVIDER_SENTINEL",
    "SPAN_TYPE_TO_OPERATION",
    "MappedSpan",
    "map_span",
]

# --- The emit allowlist, one constant per key ------------------------------
#
# Every key below is either a member of MLflow's own ``GenAiSemconvKey`` or named
# in the backend's recognized inventory. Nothing is emitted that is not one of
# these fourteen.

#: The current OpenTelemetry semantic-convention spelling of the provider.
GEN_AI_PROVIDER_NAME: _Final[str] = "gen_ai.provider.name"

#: The older spelling, carried alongside the current one (D-16). Duplicate
#: *string* keys carry no summing risk, so the provider gets both; duplicate
#: *numeric* keys do, so the cache tokens get exactly one (D-02). **The asymmetry
#: is deliberate and must not be harmonized** — the deployed backend build is
#: still unverified, which is why the compatibility spelling is carried at all.
GEN_AI_SYSTEM: _Final[str] = "gen_ai.system"

#: What the call did — chat, embeddings, generate_content.
GEN_AI_OPERATION_NAME: _Final[str] = "gen_ai.operation.name"

#: The model the request asked for.
GEN_AI_REQUEST_MODEL: _Final[str] = "gen_ai.request.model"

#: The model the response reported. Distinct from the request model on Azure
#: OpenAI, where the request carries a deployment name (SEM-03).
GEN_AI_RESPONSE_MODEL: _Final[str] = "gen_ai.response.model"

#: The provider's own id for the response.
GEN_AI_RESPONSE_ID: _Final[str] = "gen_ai.response.id"

#: Why generation stopped, as a tuple of strings.
GEN_AI_RESPONSE_FINISH_REASONS: _Final[str] = "gen_ai.response.finish_reasons"

#: Prompt tokens. On every normalized MLflow path this count **already includes**
#: the cached portion — see :data:`GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS`.
GEN_AI_USAGE_INPUT_TOKENS: _Final[str] = "gen_ai.usage.input_tokens"

#: Completion tokens.
GEN_AI_USAGE_OUTPUT_TOKENS: _Final[str] = "gen_ai.usage.output_tokens"

#: Tokens served from the provider's prompt cache, billed at a reduced rate.
#: **A subset of :data:`GEN_AI_USAGE_INPUT_TOKENS`, never an addition to it.**
#: MLflow adds cache tokens into the input count on the Anthropic and Bedrock
#: paths (``mlflow/anthropic/autolog.py:194-200``) and inherits them
#: already-included from OpenAI and Gemini, so anything computing
#: ``input_tokens + cache_read_input_tokens`` double-counts the cached portion —
#: the exact overbill this key exists to prevent. This SDK emits what MLflow
#: recorded and computes nothing.
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: _Final[str] = "gen_ai.usage.cache_read_input_tokens"

#: Tokens spent writing the provider's prompt cache. Same subset relation.
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: _Final[str] = "gen_ai.usage.cache_creation_input_tokens"

#: The exception class name, and nothing else from a failure. The status
#: description and the exception event carry raw exception text and absolute
#: filesystem paths; the class name is the whole useful signal without any of it.
ERROR_TYPE: _Final[str] = "error.type"

#: The deployment environment, supplied by the caller (D-C6). Phase 4 sources it
#: from configuration; this module takes it as an argument.
DEPLOYMENT_ENVIRONMENT_NAME: _Final[str] = "deployment.environment.name"

#: The cloud region, supplied by the caller (D-C6).
CLOUD_REGION: _Final[str] = "cloud.region"

#: The closed set (D-04). An allowlist rather than the denylist first proposed,
#: because a cost field cannot escape a set it is not a member of. A
#: ``frozenset`` rather than a ``set`` for the reason ``attributes.py`` records
#: for ``ATTRIBUTE_CAPS``: a caller who could widen it in their own process would
#: be changing what leaves the customer's machine.
EMITTED_ATTRIBUTE_KEYS: _Final[frozenset[str]] = frozenset(
    {
        GEN_AI_PROVIDER_NAME,
        GEN_AI_SYSTEM,
        GEN_AI_OPERATION_NAME,
        GEN_AI_REQUEST_MODEL,
        GEN_AI_RESPONSE_MODEL,
        GEN_AI_RESPONSE_ID,
        GEN_AI_RESPONSE_FINISH_REASONS,
        GEN_AI_USAGE_INPUT_TOKENS,
        GEN_AI_USAGE_OUTPUT_TOKENS,
        GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
        GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
        ERROR_TYPE,
        DEPLOYMENT_ENVIRONMENT_NAME,
        CLOUD_REGION,
    }
)

# ``gen_ai.usage.total_tokens`` is **deliberately absent** from the set above.
# It is not in the backend's recognized inventory, it is derivable from the input
# and output counts, and it is the key most exposed to a backend that sums rather
# than replaces. Omitting it costs nothing and removes a double-count surface.
# Recorded here as a comment rather than as a constant, so the one thing this
# module must never emit is not itself a spelling of that key.

#: MLflow span type to GenAI operation, restricted to the three types whose
#: operation MLflow itself declares ``CLIENT``. Restricting it here is what makes
#: "every admitted span maps to ``SpanKind.CLIENT``" a consequence of one table
#: rather than a second rule to keep in sync. A proxy rather than a plain dict,
#: for the ``ATTRIBUTE_CAPS`` reason above.
SPAN_TYPE_TO_OPERATION: _Final[_Mapping[str, str]] = _types.MappingProxyType(
    {
        "CHAT_MODEL": "chat",
        "LLM": "generate_content",
        "EMBEDDING": "embeddings",
    }
)

#: Carried by ``gen_ai.provider.name`` when inference finds nothing (D-13). The
#: key is never empty and never absent, so SEM-01 holds unconditionally and the
#: backend's ``GenAISemanticConventionMapper`` always claims the payload instead
#: of dropping it to ``GenericFallbackMapper``. The span then rates with a
#: visible, correctable unknown provider rather than vanishing into a silent
#: fallback path — an omitted key would be a billing event with no attributable
#: cause. The literal deliberately does **not** lowercase to ``unknown``: the
#: generic fallback rates under provider id ``"Unknown"``, and merging into that
#: bucket would partly defeat the point.
PROVIDER_SENTINEL: _Final[str] = "revenium-unknown-provider"

#: The MLflow usage field to emit each token key from. One tuple rather than four
#: hand-written lookups, so a key cannot be read from the wrong field.
_TOKEN_FIELD_TO_KEY: _Final[tuple[tuple[str, str], ...]] = (
    ("input_tokens", GEN_AI_USAGE_INPUT_TOKENS),
    ("output_tokens", GEN_AI_USAGE_OUTPUT_TOKENS),
    ("cache_read_input_tokens", GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS),
    ("cache_creation_input_tokens", GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS),
)

#: OpenTelemetry's all-zero invalid ids, used when a span arrives with no
#: context at all. A zero id can never be mistaken for a real one, and the
#: backend mints a replacement transaction id for a blank value — whereas
#: raising here would fail an entire export batch over one malformed span.
_ABSENT_TRACE_ID: _Final[str] = "0" * 32
_ABSENT_SPAN_ID: _Final[str] = "0" * 16


@_dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class MappedSpan:
    """One span, translated: everything the Revenium exporter needs and nothing else.

    Frozen, slotted and keyword-only, following ``ReveniumConfig``: frozen
    because a mapping that can drift after it is produced turns "what did we
    export" into a question with no stable answer, and keyword-only because field
    order would otherwise be a contract that reordering breaks.
    """

    #: The emitted attributes, a subset of :data:`EMITTED_ATTRIBUTE_KEYS`, ready
    #: for the wire. No key is present with a ``None`` value.
    attributes: _Mapping[str, _AttributeValue]

    #: Always ``SpanKind.CLIENT`` for an admitted span (SEM-12), whatever kind
    #: MLflow produced — a real captured MLflow ``CHAT_MODEL`` span is
    #: ``INTERNAL``, and the GenAI conventions require ``CLIENT`` for inference.
    kind: _SpanKind

    #: 32 lowercase hex characters.
    trace_id: str

    #: 16 lowercase hex characters. The backend uses it as the transaction id.
    span_id: str

    #: 16 lowercase hex characters, or ``None`` for a root span — which is how
    #: the backend distinguishes a root from a child.
    parent_span_id: str | None

    #: Integer nanoseconds, read off the span rather than off
    #: ``mlflow.spanStartTimeNs``: that attribute has exactly one setter in
    #: MLflow and a real captured span does not carry it (SEM-08).
    start_time_ns: int

    #: Integer nanoseconds.
    end_time_ns: int

    #: ``end_time_ns - start_time_ns``, derived rather than read.
    duration_ns: int


def _token_int(value: object, /) -> int | None:
    """A token count that is safe to emit, or ``None``.

    Separate from ``_spanattrs.is_positive_int`` because it answers a different
    question. That one asks whether a span shows evidence of work worth billing,
    so it requires a *positive* count. This one asks whether a number MLflow
    recorded can be put on the wire, and a recorded zero is a fact worth
    forwarding. The ``bool`` exclusion is common to both and non-negotiable:
    ``isinstance(True, int)`` is true and the encoder would ship ``bool_value``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _infer_provider(span: _ReadableSpan, /) -> str:
    """The provider, never empty.

    A stub for this slice: MLflow's own assertion, then the sentinel. Plan 02-03
    replaces the middle of the chain — an already-present ``gen_ai.provider.name``,
    ``mlflow.message.format`` through a provider-only allowlist, then a
    model-name prefix — without changing this function's shape.
    """
    attributes = span.attributes or {}
    provider = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_LLM_PROVIDER)
    return provider or PROVIDER_SENTINEL


def _operation(attributes: _Mapping[str, object], /) -> str | None:
    """The GenAI operation for this span.

    The span type is consulted **first**, deliberately. A span carrying both an
    MLflow type and a bridged ``gen_ai.operation.name`` could otherwise be
    admitted on its type and then emitted under an operation the GenAI
    conventions class as ``INTERNAL`` — a tool operation on a ``CLIENT`` span,
    which is incoherent on the wire and reads as a rating error downstream.
    """
    span_type = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_SPAN_TYPE)
    if span_type is not None and span_type in SPAN_TYPE_TO_OPERATION:
        return SPAN_TYPE_TO_OPERATION[span_type]
    declared = attributes.get(GEN_AI_OPERATION_NAME)
    return declared if isinstance(declared, str) and declared else None


def map_span(
    span: _ReadableSpan,
    *,
    environment: str | None = None,
    region: str | None = None,
) -> MappedSpan:
    """Translate one admitted span into the attributes and fields Revenium rates on.

    Args:
        span: A span ``eligibility.is_billable_llm_span`` has admitted.
        environment: The deployment environment, or ``None`` to omit the key.
        region: The cloud region, or ``None`` to omit the key.

    Returns:
        A :class:`MappedSpan`. This function returns a record on **every** input
        and raises on none: a malformed attribute on one span must not fail the
        export batch it happens to be in (T-02-05).

    ``environment`` and ``region`` arrive as keyword-only parameters rather than
    as new ``ReveniumConfig`` fields (D-C6). A new public configuration field is
    outside a phase scoped to two pure functions; Phase 4 supplies the values
    from configuration and this module takes them as arguments.
    """
    source: _Mapping[str, object] = span.attributes or {}
    attributes: dict[str, _AttributeValue] = {}

    operation = _operation(source)
    if operation is not None:
        attributes[GEN_AI_OPERATION_NAME] = operation

    request_model = _spanattrs.decode_str(source, _spanattrs.MLFLOW_LLM_MODEL)
    if request_model:
        attributes[GEN_AI_REQUEST_MODEL] = request_model

    usage = _spanattrs.decode_mapping(source, _spanattrs.MLFLOW_CHAT_USAGE) or {}
    for field, key in _TOKEN_FIELD_TO_KEY:
        count = _token_int(usage.get(field))
        if count is None:
            count = _token_int(source.get(key))
        if count is not None:
            attributes[key] = count

    # D-16: one inferred value, both spellings. See GEN_AI_SYSTEM for why this is
    # the opposite call to the single cache-token spelling, and why the asymmetry
    # must not be tidied away.
    provider = _infer_provider(span)
    attributes[GEN_AI_PROVIDER_NAME] = provider
    attributes[GEN_AI_SYSTEM] = provider

    if environment:
        attributes[DEPLOYMENT_ENVIRONMENT_NAME] = environment
    if region:
        attributes[CLOUD_REGION] = region

    context = span.context
    parent = span.parent
    start_time_ns = span.start_time if span.start_time is not None else 0
    # A span whose end time is unset is measured as zero-duration rather than
    # negative. Whether any MLflow path produces one is unestablished (SEM-08),
    # so the degradation is defined rather than left to arithmetic.
    end_time_ns = span.end_time if span.end_time is not None else start_time_ns

    return MappedSpan(
        attributes=_types.MappingProxyType(attributes),
        kind=_SpanKind.CLIENT,
        trace_id=format(context.trace_id, "032x") if context is not None else _ABSENT_TRACE_ID,
        span_id=format(context.span_id, "016x") if context is not None else _ABSENT_SPAN_ID,
        parent_span_id=format(parent.span_id, "016x") if parent is not None else None,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
        duration_ns=end_time_ns - start_time_ns,
    )
