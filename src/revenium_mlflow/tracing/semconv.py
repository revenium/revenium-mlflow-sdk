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

**Correction C2 — the instrumentation-scope step is refuted, and the reason is
recorded so it is not re-added.** D-14 ordered provider inference
``mlflow.llm.provider`` → instrumentation-scope name → model-name prefix, citing
scope names ``mlflow.openai`` and ``mlflow.anthropic``. A span captured off
MLflow's own bridged tracer provider carries scope name
``mlflow.tracing.provider``, and the cause is structural: ``_get_tracer`` is
called with ``__name__`` from inside ``mlflow/tracing/provider.py`` itself for
the fluent and no-context span paths, which is where the OpenAI, Anthropic,
Gemini and Bedrock autologs all enter. Only four peripheral integrations
(``haystack``, ``strands``, ``semantic_kernel``, ``agno``) pass their own module
name. The step never fires, so leaving it in would be worse than removing it: it
would read as a working fallback while the model-prefix heuristic silently
carried the whole load. :data:`MESSAGE_FORMAT_PROVIDERS` replaces it — written
per integration, it is the structural fact about *which integration emitted the
span* that D-14 wanted from the scope name.

**Base URL is declined (D-C4), with the reason, so the question is not
re-opened.** D-14 left it open for lowest precedence "if it is reachable from
span attributes alone". It is not. The OpenAI autolog writes exactly
``mlflow.message.format`` and ``mlflow.chat.tokenUsage`` directly plus the model
through ``set_span_chat_attributes``; the client's ``base_url`` lives on the
client *instance* and would only reach the span through ``mlflow.spanInputs``,
which holds request kwargs, not client configuration. Reaching it would mean
touching the client object, breaking the dict-in/dict-out purity that makes this
module testable without MLflow — for a signal that is not on the span.

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
    "MESSAGE_FORMAT_PROVIDERS",
    "MODEL_PREFIX_PROVIDERS",
    "PROVIDER_SENTINEL",
    "SPAN_TYPE_TO_OPERATION",
    "MappedSpan",
    "infer_provider",
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
#: bucket would partly defeat the point. A configurable ``default_provider`` was
#: considered and rejected: it is a new public configuration field in a phase
#: scoped to two pure functions, and it would let a customer set a *real*
#: provider name as the value for spans nobody could attribute — turning a
#: visible unknown back into an invisible wrong answer. Deferred to Phase 4 as an
#: idea, not as a commitment.
PROVIDER_SENTINEL: _Final[str] = "revenium-unknown-provider"

#: ``mlflow.message.format`` to provider, as a **positive allowlist** of the six
#: values that genuinely name a provider. A denylist of framework values was
#: rejected: roughly a third of the thirty-plus observed format values name a
#: framework (``langchain``, ``llamaindex``, ``dspy``, ``crewai``, ``ag2``,
#: ``autogen``, ``smolagents``, ``pydantic_ai``, ``openai-agent``, ``vercel_ai``,
#: ``voltagent``, ``livekit``), and a denylist would let the *next* MLflow
#: framework integration invent a provider name by accident. This is the same
#: allowlist-not-denylist discipline SEM-10 applies to span types.
#:
#: **``gemini`` is the one entry whose key and value differ, and that is
#: deliberate — do not "correct" it.** The ``gemini-`` prefix in
#: :data:`MODEL_PREFIX_PROVIDERS` also yields ``google``, and one provider must
#: have exactly one spelling across every step of the chain. Mapping ``gemini``
#: to itself would not surface as a conflict anywhere; it would surface as one
#: customer's Gemini history split across two provider labels, each of which then
#: reads as correct forever.
#:
#: A proxy rather than a plain dict, for the reason ``attributes.py`` records for
#: ``ATTRIBUTE_CAPS``: a caller who could widen this table in their own process
#: would be changing what a customer is attributed to.
MESSAGE_FORMAT_PROVIDERS: _Final[_Mapping[str, str]] = _types.MappingProxyType(
    {
        "openai": "openai",
        "anthropic": "anthropic",
        #: The one key/value mismatch, and it is load-bearing. See above.
        "gemini": "google",
        "bedrock": "bedrock",
        "groq": "groq",
        "mistral": "mistral",
    }
)

#: Model-name prefix to provider, **longest prefix first** (D-C5). An ordered
#: tuple rather than a mapping because iteration order carries meaning here:
#: matching is first-hit, so the order decides the answer, and a tuple declares
#: that where a dict would leave it implicit. A diff on this table then reads as
#: an addition or a removal rather than as a reshuffle.
#:
#: This step is **deliberately last** before the sentinel. A proxied or aliased
#: model name — a gateway that renames models, an internal alias, a fine-tune
#: with a house prefix — defeats it, and a wrong-but-plausible provider label is
#: worse than a visible unknown because the customer cannot discover it. A miss
#: here therefore costs a sentinel, never a wrong label.
MODEL_PREFIX_PROVIDERS: _Final[tuple[tuple[str, str], ...]] = (
    ("chatgpt-", "openai"),
    ("command-", "cohere"),
    ("mistral-", "mistral"),
    ("claude-", "anthropic"),
    # Lowercase ``google``, not the capitalised vendor name (D-C8), and the same
    # literal ``MESSAGE_FORMAT_PROVIDERS["gemini"]`` yields.
    ("gemini-", "google"),
    ("llama-", "meta"),
    ("gpt-", "openai"),
    ("o1-", "openai"),
    ("o3-", "openai"),
)

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


def _model_name(attributes: _Mapping[str, object], /) -> str | None:
    """The model this span asked for, from either place MLflow records it.

    ``mlflow.llm.model`` first, then ``mlflow.spanInputs["model"]``. The second
    is not redundant: the model attribute is written by
    ``set_span_model_attribute``, which is guarded and can decline, while the
    request kwargs carry the name regardless. Reading only the attribute would
    send those spans to the sentinel with the answer sitting one key away.
    """
    model = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_LLM_MODEL)
    if model:
        return model
    inputs = _spanattrs.decode_mapping(attributes, _spanattrs.MLFLOW_SPAN_INPUTS)
    if inputs is None:
        return None
    candidate = inputs.get("model")
    return candidate if isinstance(candidate, str) and candidate else None


def infer_provider(span: _ReadableSpan, /) -> str:
    """The provider for one span, in five ordered steps, never empty.

    Args:
        span: Any span. Nothing is assumed about its attributes — an empty
            mapping is a legal input and returns :data:`PROVIDER_SENTINEL`.

    Returns:
        A non-empty provider name. This function has no ``raise`` path: it runs
        inside a ``SpanProcessor`` callback for every span in the host process,
        and raising there would fail an export batch over one malformed span.

    The order is the whole design, so it is written out rather than left to be
    read off the body:

    1. ``mlflow.llm.provider`` — **authoritative**, MLflow asserted it. Thirteen
       or more integrations set it, Anthropic among them
       (``mlflow/anthropic/autolog.py:140``).
    2. A ``gen_ai.provider.name`` or ``gen_ai.system`` already on the span —
       **authoritative**, a bridged non-MLflow OTel instrumentor asserted it, and
       a heuristic must not overwrite an assertion made closer to the call. This
       step is the addition beyond D-14, and it is free.
    3. ``mlflow.message.format`` through :data:`MESSAGE_FORMAT_PROVIDERS` —
       **structural**, and the step that makes SEM-01's criterion 4 hold: MLflow's
       OpenAI autolog never writes a provider, but it does write
       ``mlflow.message.format = "openai"``.
    4. A model-name prefix through :data:`MODEL_PREFIX_PROVIDERS` —
       **heuristic**, and last for that reason.
    5. :data:`PROVIDER_SENTINEL`.

    Comparison at steps 3 and 4 is **exact over the decoded value**: no case
    folding and no Unicode normalization. ``"OpenAI"`` does not match
    ``"openai"`` and falls through. Folding would be a second, undeclared rule
    about what counts as the same provider, and it would admit values MLflow
    never writes.
    """
    attributes: _Mapping[str, object] = span.attributes or {}

    asserted = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_LLM_PROVIDER)
    if asserted:
        return asserted

    for key in (GEN_AI_PROVIDER_NAME, GEN_AI_SYSTEM):
        # Through the same decoder as everything else (D-C1): a bridged
        # instrumentor writes these bare, MLflow would write them JSON-encoded,
        # and the lenient reader accepts both without a second code path.
        declared = _spanattrs.decode_str(attributes, key)
        if declared:
            return declared

    message_format = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_MESSAGE_FORMAT)
    if message_format is not None and message_format in MESSAGE_FORMAT_PROVIDERS:
        return MESSAGE_FORMAT_PROVIDERS[message_format]

    model = _model_name(attributes)
    if model is not None:
        for prefix, provider in MODEL_PREFIX_PROVIDERS:
            if model.startswith(prefix):
                return provider

    return PROVIDER_SENTINEL


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

    # D-02: each token count gets **exactly one** spelling, which is the opposite
    # call to the provider's two spellings below, and the asymmetry is deliberate
    # and must not be harmonized. The reason is arithmetic: a backend that sums
    # rather than dedupes duplicate keys would double the count, and these are
    # the numbers the invoice is computed from. A duplicate *string* key cannot
    # be summed, so it costs nothing; a duplicate *numeric* key can be, so it
    # costs the customer money. Same evidence, opposite answers, because the
    # failure modes are not symmetric.
    usage = _spanattrs.decode_mapping(source, _spanattrs.MLFLOW_CHAT_USAGE) or {}
    for field, key in _TOKEN_FIELD_TO_KEY:
        count = _token_int(usage.get(field))
        if count is None:
            count = _token_int(source.get(key))
        if count is not None:
            attributes[key] = count

    # D-16: one inferred value, written under **both** spellings — the current
    # semantic-convention key and the older one the backend still accepts. This
    # is the opposite call to the single cache-token spelling above, and the
    # asymmetry is deliberate and must not be harmonized. The reason is again
    # arithmetic: duplicate *string* keys carry no summing risk at all, so
    # carrying both costs nothing and buys compatibility, while duplicate
    # *numeric* keys risk a backend that sums rather than dedupes. The deployed
    # backend build is still unverified, which is why the compatibility spelling
    # is carried at all rather than dropped as redundant.
    provider = infer_provider(span)
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
