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
from opentelemetry.trace import StatusCode as _StatusCode
from opentelemetry.util.types import AttributeValue as _AttributeValue

from . import _spanattrs

__all__ = [
    "CLOUD_REGION",
    "DEPLOYMENT_ENVIRONMENT_NAME",
    "EMITTED_ATTRIBUTE_KEYS",
    "ERROR_TYPE",
    "ERROR_TYPE_UNKNOWN",
    "FINISH_REASON_SOURCES",
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
    "RESOURCE_PROVIDER_CLAIM",
    "SPAN_TYPE_TO_OPERATION",
    "MappedSpan",
    "infer_provider",
    "map_span",
    "operation_for_span",
    "resource_claim_attributes",
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

#: OpenTelemetry's own value for an error whose type could not be determined.
#: Carried when the span's status is ``ERROR`` but no exception event names a
#: class. The alternative — omitting :data:`ERROR_TYPE` — would lose the fact
#: that the call failed at all, and the span would rate as a clean completion.
#: The remaining alternative, parsing the status description for a type, reads
#: free text written by customer code, which is the exact surface the whole
#: error derivation exists to avoid. Whether the Revenium backend prefers
#: ``_OTHER`` or an absent key for this case is unresolved (SEM-06 probe edge);
#: this is the OpenTelemetry-defined answer, which is the defensible default.
ERROR_TYPE_UNKNOWN: _Final[str] = "_OTHER"

#: The deployment environment, supplied by the caller (D-C6). Phase 4 sources it
#: from configuration; this module takes it as an argument.
#:
#: **Assumption A1, stated plainly: no document in this repository names the key
#: the Revenium backend reads for deployment environment.**
#: ``BACKEND-CONTRACT.md`` enumerates the thirty recognized ``revenium.*`` keys
#: and the ``gen_ai.*`` token and provider spellings, and neither list contains
#: this dimension. This is therefore the OpenTelemetry semantic-convention
#: spelling, chosen as the defensible default, with confirmation carried to the
#: end-of-phase check with the backend owner. A wrong spelling is not loud: the
#: backend drops an unrecognized attribute silently, so environment would simply
#: be missing from every report with no error on either side.
DEPLOYMENT_ENVIRONMENT_NAME: _Final[str] = "deployment.environment.name"

#: The cloud region, supplied by the caller (D-C6). Assumption A1 applies to this
#: key exactly as it does to :data:`DEPLOYMENT_ENVIRONMENT_NAME` above — an
#: OpenTelemetry spelling chosen in the absence of any Revenium source, pending
#: the same end-of-phase confirmation.
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

#: Where a finish reason lives in a decoded ``mlflow.spanOutputs``, in order,
#: first match wins. Each row is a top-level field and, when that field holds a
#: list of entries, the per-entry field to read from it:
#:
#: 1. ``choices[].finish_reason`` — the OpenAI chat shape.
#: 2. ``status`` — the OpenAI Responses shape, which carries no ``choices``.
#: 3. ``stop_reason`` — the Anthropic shape.
#:
#: **This table is the deliberate, narrow exception recorded in plan 02-04's
#: scope-reading section, and the reason it is not D-01's prohibition.** D-01
#: forbids per-provider knowledge of raw response shapes for *cache tokens*,
#: because that knowledge would drift independently of MLflow's own
#: normalization. There is no normalization to drift against here:
#: ``_translate_universal_attributes`` produces no finish reason at all, and
#: MLflow emits ``gen_ai.response.finish_reasons`` through the OpenAI converter
#: alone — ``extract_response_attrs`` is absent from the Anthropic, Gemini and
#: Bedrock converters. The alternative to this table is not emitting SEM-06's
#: finish reason for anyone. It therefore stays small: three known shapes and
#: nothing more.
#:
#: A consequence worth stating, because it looks like a bug the first time it is
#: seen: an A/B of this mapper against MLflow's translator on an *Anthropic*
#: fixture shows a finish reason here and none there. That difference is
#: MLflow's behaviour, not a defect in either.
FINISH_REASON_SOURCES: _Final[tuple[tuple[str, str | None], ...]] = (
    ("choices", "finish_reason"),
    ("status", None),
    ("stop_reason", None),
)

#: The finish reasons a provider is permitted to report, lowercased. A value
#: outside this set is a string from a response body, not a reason, and is
#: dropped rather than forwarded (plan 02-08, 02-REVIEW.md CR-02).
#:
#: **Class A: the emitted value is constrained by membership, not by shape.**
#: This is the same allowlist-not-denylist discipline the module docstring
#: applies to keys, applied one level down to values — a value cannot escape a
#: set it is not a member of. It is what closes all three GAP-2 reproductions at
#: once: a credential-bearing URL, a 50,000-character string and a clinical
#: sentence are non-members, so none of them is a finish reason.
#:
#: The three groups, recorded by provider vocabulary so a future addition can be
#: argued about rather than guessed at:
#:
#: 1. OpenAI chat completions ``finish_reason`` — ``stop``, ``length``,
#:    ``tool_calls``, ``content_filter``, ``function_call``.
#: 2. OpenAI Responses ``status`` — ``completed``, ``incomplete``, ``failed``,
#:    ``cancelled``, ``in_progress``.
#: 3. Anthropic ``stop_reason`` — ``end_turn``, ``max_tokens``,
#:    ``stop_sequence``, ``pause_turn``, ``refusal``.
#:
#: **The accepted cost, recorded rather than hidden.** A legitimate finish reason
#: from a provider whose vocabulary is not in the set is dropped, and the absence
#: is silent — the key is simply missing. There is also no drift test that can
#: catch an addition, because there is no upstream table to anchor one on, unlike
#: ``eligibility.KNOWN_MLFLOW_SPAN_TYPES``, which
#: ``tests/unit/test_mlflow_vocabulary_drift.py`` anchors on MLflow's own. The
#: set is CR-02's list verbatim; whether it is complete for any provider's
#: current vocabulary is **unestablished in this repository** — no measurement
#: here establishes it, and CLAUDE.md forbids the live calls that would.
#:
#: A ``frozenset`` for the reason :data:`EMITTED_ATTRIBUTE_KEYS` and
#: ``attributes.ATTRIBUTE_CAPS`` are: a caller who could widen it in their own
#: process would be changing what leaves the customer's machine.
_KNOWN_FINISH_REASONS: _Final[frozenset[str]] = frozenset(
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

#: Nothing read out of a response body, and nothing carrying an identifier the
#: span declared, reaches the wire longer than this.
#:
#: **The count is Python ``str`` code points — not bytes, not grapheme
#: clusters.** That is written down because "whose definition of length applies"
#: is otherwise a question with three defensible answers and no recorded one
#: (SEM-06 encoding edge). A four-byte emoji is one code point here, and a
#: combining sequence is as many code points as it has scalars.
#:
#: **It is a hard reject, never a truncation**, and the boundary is asserted from
#: both sides in ``tests/unit/test_semconv_derivations.py``: a value at exactly
#: the cap is emitted, a value one code point over is omitted. A truncated
#: response id is a *wrong* response id, and a wrong id is worse than an absent
#: one when a charge is disputed. ``attributes.ATTRIBUTE_CAPS`` records the same
#: shape from the other side: Revenium's ingest silently drops an oversized value
#: rather than truncating it, so it vanishes with no error on either side. That
#: module publishes the ``revenium.*`` caps as data; this constant is the
#: enforcement half for the ``gen_ai.*`` namespace, where no document in this
#: repository names a backend cap at all — so this figure is an SDK-side rule,
#: not a mirrored backend one.
#:
#: **The figure, and the reasoning that sized it, recorded verbatim as the human
#: answering plan 02-08's ``gate="blocking-human"`` checkpoint gave it** — so the
#: residual T-02-08-07 stays traceable to the number that sized it:
#:
#:     64 halves the T-02-08-07 residual and matches the `ATTRIBUTE_CAPS` floor
#:     for `revenium.*`, and is consistent with D-09's asymmetry that close calls
#:     are decided towards rejection. The figure does NOT close T-02-08-07: a
#:     `rev_sk_`-prefixed credential fits comfortably under 64, and would also
#:     have fit under the 128 alternative, so the choice traded silent metering
#:     loss against credential-window width rather than closing the leak. The
#:     known and accepted risk is that `gen_ai.request.model` is silently dropped
#:     for a Bedrock inference-profile ARN (~101 code points) or a Vertex
#:     publisher path (~92) IF MLflow records the long form in the model field.
#:     Whether it does is UNESTABLISHED in this repository: the identifier
#:     lengths that informed this figure were computed from published identifier
#:     *formats*, not measured from MLflow output, no fixture here carries a model
#:     string longer than 22 characters, and CLAUDE.md forbids the live calls that
#:     would settle it. That loss would be a metering loss, not a rating failure —
#:     the span still rates under the unknown-model path — and it would be silent.
_MAX_EMITTED_VALUE_CHARS: _Final[int] = 64

#: The value the SDK claims at **resource** level (D-15, SEM-02).
#:
#: Its only job is to satisfy ``GenAISemanticConventionMapper.canHandle``, which
#: checks resource attributes before it looks at any span. Without a resource
#: claim the decision rests on a span in the batch carrying a provider key, and
#: on the MLflow OpenAI path none does — so the whole batch falls to
#: ``GenericFallbackMapper`` and rates under ``"Unknown"`` with no error on
#: either side. Real per-provider attribution still comes from each span's own
#: ``gen_ai.provider.name``, which is where the backend reads it for rating
#: anyway; this claim decides *which mapper* reads it, not *what it says*.
#:
#: **The value is deliberately not a real provider name.** It is emitted from
#: every process using the SDK, so it must assert nothing true-sounding and false
#: about that process. D-15 rejected the two alternatives for the same reason:
#: first-eligible-span-wins is nondeterministic under concurrency and actively
#: mislabels a process calling two providers by whichever span arrived first, and
#: a configured resource claim silently mislabels every payload from a process
#: nobody configured.
#:
#: **Non-collision, checked rather than assumed.** ``canHandle`` returns ``false``
#: outright when ``service.name`` or the scope name is in ``KNOWN_CUSTOM_SDK_NAMES``
#: (``claude-code``, ``gemini-cli``, ``codex_exec``, ``codex_cli_rs``).
#: ``BACKEND-CONTRACT.md`` §4 left "verify MLflow's resource does not collide" as
#: an open item; it is closed — a captured MLflow resource carries
#: ``telemetry.sdk.{language,name,version}`` and **no** ``service.name`` at all,
#: and its scope name is ``mlflow.tracing.provider``. Neither collides, and this
#: literal does not either. ``tests/unit/test_semconv_provider.py`` pins that
#: against its own literal copy of the set.
#:
#: This phase produces the claim **set**. Merging it into an OTel ``Resource`` is
#: an exporter concern and belongs to Phase 4 — the boundary ``02-CONTEXT.md``
#: draws explicitly.
RESOURCE_PROVIDER_CLAIM: _Final[str] = "revenium-mlflow-sdk"

#: Built once. Handing the same read-only mapping to every caller is what makes
#: :func:`resource_claim_attributes` deterministic by construction rather than by
#: convention.
_RESOURCE_CLAIM_ATTRIBUTES: _Final[_Mapping[str, str]] = _types.MappingProxyType(
    {
        GEN_AI_PROVIDER_NAME: RESOURCE_PROVIDER_CLAIM,
        GEN_AI_SYSTEM: RESOURCE_PROVIDER_CLAIM,
    }
)

#: The MLflow usage field to emit each token key from. One tuple rather than four
#: hand-written lookups, so a key cannot be read from the wrong field.
_TOKEN_FIELD_TO_KEY: _Final[tuple[tuple[str, str], ...]] = (
    ("input_tokens", GEN_AI_USAGE_INPUT_TOKENS),
    ("output_tokens", GEN_AI_USAGE_OUTPUT_TOKENS),
    ("cache_read_input_tokens", GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS),
    ("cache_creation_input_tokens", GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS),
)

#: The model field, spelled once. It is read out of the decoded MLflow inputs
#: mapping and out of the decoded outputs mapping, and those two reads are what
#: make :data:`GEN_AI_REQUEST_MODEL` and :data:`GEN_AI_RESPONSE_MODEL` two
#: different answers rather than one value written twice (SEM-03).
_MODEL_FIELD: _Final[str] = "model"

#: The provider's response id, in the decoded outputs mapping.
_RESPONSE_ID_FIELD: _Final[str] = "id"

#: The OpenTelemetry exception event, and the **only** attribute of it this
#: module ever reads. Both spelled once, because the value of the control is
#: that the read is narrow — a second read added later would be one line and
#: would not look like a disclosure.
_EXCEPTION_EVENT_NAME: _Final[str] = "exception"
_EXCEPTION_TYPE_ATTRIBUTE: _Final[str] = "exception.type"

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

    **A negative count is dropped (WR-02, T-02-08-03), and that is not the same
    call as accepting zero.** A recorded zero is a measurable fact: the provider
    reported no tokens for that field. ``-7`` is not a measurement at all — it is
    a broken integration — and depending on backend arithmetic it lands as a
    silent credit or as a corrupted total. ``_spanattrs.is_positive_int`` already
    rejects negatives for the gate; this brings the emit path into line, so the
    two do not disagree about the same number on the same span. The two halves
    are asserted separately in ``tests/unit/test_semconv_derivations.py`` — a
    blanket drop that took the recorded zero with it would satisfy one and red
    the other.

    ``decode_int`` upstream deliberately does *not* apply this rule: it reports
    what was recorded, and the policy lives here so it lives in exactly one
    place, on both the usage-dict source and the flat ``gen_ai.usage.*`` fallback.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def resource_claim_attributes() -> _Mapping[str, str]:
    """The resource-level attributes the Phase 4 exporter merges (SEM-02).

    Returns:
        A read-only two-key mapping, both keys carrying
        :data:`RESOURCE_PROVIDER_CLAIM`. Both spellings for the same D-16 reason
        they appear per span: a duplicate *string* key carries no summing risk,
        so the compatibility spelling costs nothing.

    **It takes no arguments and consults no span, deliberately.** The claim is a
    fact about the SDK, not about the traffic, so it is the same in a process
    calling one provider and in a process calling four. Deriving it from a span
    would reintroduce exactly what D-15 rejected — see
    :data:`RESOURCE_PROVIDER_CLAIM` for why both alternatives are worse.
    """
    return _RESOURCE_CLAIM_ATTRIBUTES


def _clean_reason(value: object, /) -> str | None:
    """One finish reason that is safe to emit, or ``None`` to fall through.

    Args:
        value: Whatever was read out of a :data:`FINISH_REASON_SOURCES` field. It
            is arbitrary application data — ``mlflow.spanOutputs`` on a
            ``@mlflow.trace``-decorated function is that function's serialized
            return value, not a provider enum.

    Returns:
        The candidate, stripped and with its original casing, when its lowercased
        form is a member of :data:`_KNOWN_FINISH_REASONS`; ``None`` otherwise.

    **This is the Class A value constraint, and membership is the whole control.**
    Before it, :data:`FINISH_REASON_SOURCES`' ``("status", None)`` row accepted
    *any* non-empty string at a top-level key — reproduced forwarding a URL with
    an embedded credential, a 50,000-character string and a clinical sentence
    verbatim to the billing wire (GAP-2, T-02-08-01). A shape rule would have
    stopped the leaks someone thought of; a bare bearer token with no whitespace
    in it would have passed one.

    Every row runs through here, the per-entry ``choices[].finish_reason`` row
    included, so no row is a weaker gate than another. Comparison is over Python
    ``str`` code points, lowercased with ``str.lower`` and stripped with
    ``str.strip`` — the same unit :data:`_MAX_EMITTED_VALUE_CHARS` counts in.
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if candidate.lower() in _KNOWN_FINISH_REASONS else None


def _bounded(value: str | None, /) -> str | None:
    """One emitted value, or ``None`` when it is longer than the cap.

    Args:
        value: A candidate emitted value, or ``None``.

    Returns:
        ``value`` unchanged when it is at most :data:`_MAX_EMITTED_VALUE_CHARS`
        code points long; ``None`` otherwise. **Never a truncation** — see the
        constant for why a truncated response id is worse than an absent one.

    **This is the Class B value constraint.** ``gen_ai.request.model``,
    ``gen_ai.response.model``, ``gen_ai.response.id`` and
    ``gen_ai.operation.name`` carry the provider's or the span's own identifier,
    which SEM-03 and SEM-06 *require* — an allowlist there would drop every model
    this SDK has not heard of, which is every new model. So they are bounded by
    length and by nothing else, and the residual that leaves is T-02-08-07, named
    in plan 02-08's threat register rather than papered over.

    It is applied to a cleaned finish reason too, so the cap holds on every
    emitted string without exception even where a closed set already constrains
    it. That is redundant today — no member of :data:`_KNOWN_FINISH_REASONS` is
    close to the cap — and it is kept so "no emitted value exceeds the cap" is
    true by construction rather than by the current contents of a set.

    **One consequence worth stating, because it is not an emit rule.**
    :func:`_model_candidates` reads :func:`_mapping_model`, so an over-cap model
    name also stops being a provider-inference candidate. That narrowing cannot
    produce a *wrong* provider label — it can only cost a
    :data:`PROVIDER_SENTINEL` — which is the direction :data:`MODEL_PREFIX_PROVIDERS`
    already declares safe for its own heuristic.
    """
    if value is None:
        return None
    return value if len(value) <= _MAX_EMITTED_VALUE_CHARS else None


def _mapping_model(mapping: _Mapping[str, object] | None, /) -> str | None:
    """The model name inside a decoded MLflow inputs or outputs mapping, if any.

    Bounded by :func:`_bounded`: an over-cap model name in the mapping is
    reported absent, so ``map_span`` falls through to the shared
    ``mlflow.llm.model`` fallback rather than carrying it to the wire.
    """
    if mapping is None:
        return None
    candidate = mapping.get(_MODEL_FIELD)
    if not isinstance(candidate, str) or not candidate:
        return None
    return _bounded(candidate)


def _model_candidates(attributes: _Mapping[str, object], /) -> tuple[str, ...]:
    """Every model name this span records, in the order :func:`map_span` emits them.

    Args:
        attributes: A span's raw attribute mapping.

    Returns:
        The usable model names, de-duplicated with first occurrence winning, in
        the order ``gen_ai.request.model``, ``gen_ai.response.model``, then the
        shared fallback. Empty and non-string values are skipped rather than
        returned, so every element is a name the prefix table can be asked about.

    **Both emitted model keys are candidates because the attribute's provenance
    differs by integration.** ``mlflow.llm.model`` is the *response* model on the
    OpenAI path and the *request* model on Anthropic's — ``map_span``'s own SEM-03
    comment sets that out — while the request kwargs in ``mlflow.spanInputs``
    carry the requested name regardless, on paths where
    ``set_span_model_attribute`` declined to write the attribute at all.
    Inferring from one of them sends a span to :data:`PROVIDER_SENTINEL` while
    the answer sits in the span's own other emitted attribute: a span with
    ``mlflow.llm.model = "house-alias-v3"`` and an inputs model of
    ``claude-sonnet-4-5`` went out labelled with the unknown-provider sentinel
    while emitting ``gen_ai.request.model = "claude-sonnet-4-5"`` (WR-04).

    **The accepted cost, stated rather than left to be discovered.** Step 4 of
    :func:`infer_provider` is a heuristic, and a second candidate is a second
    chance for a plausible-but-wrong prefix match. The mitigation is unchanged
    and it is structural: steps 1 to 3 are authoritative and run first, so a span
    whose provider is actually asserted — by MLflow, by a bridged instrumentor,
    or by the message format — never reaches step 4 at all.
    """
    inputs = _spanattrs.decode_mapping(attributes, _spanattrs.MLFLOW_SPAN_INPUTS)
    outputs = _spanattrs.decode_mapping(attributes, _spanattrs.MLFLOW_SPAN_OUTPUTS)
    recorded = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_LLM_MODEL)

    candidates: list[str] = []
    for candidate in (_mapping_model(inputs), _mapping_model(outputs), recorded):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def _finish_reasons(outputs: _Mapping[str, object] | None, /) -> tuple[str, ...] | None:
    """Why generation stopped, as a tuple of strings, or ``None`` to omit the key.

    ``None`` and ``()`` are different answers and the distinction is the point.
    An empty tuple ships as an array with no elements — a present key carrying no
    value, which reads downstream as "the provider reported no reason" rather
    than as "this SDK did not recognise the shape". Only a row that yields at
    least one non-empty string counts as a match; anything else falls through to
    the next row and then to ``None``.

    Nothing but named string fields is read out of ``outputs``, and the mapping
    itself is never copied forward. That matters because ``outputs`` holds the
    full serialized provider response with completion text in it (T-02-15); the
    closed emit allowlist is the second, independent guard.

    **Every row runs through :func:`_clean_reason` and :func:`_bounded` (plan
    02-08).** Reading a named field was never the constraint the module docstring
    claimed: the ``("status", None)`` row accepted any non-empty string at a
    top-level key, and forwarded a credential-bearing URL verbatim (GAP-2). A row
    yielding no *clean* reason now falls through to the next exactly as a row
    yielding no string always did, and the key is omitted when none matches — so
    the ``None``-versus-``()`` distinction above is unchanged by the constraint.
    """
    if not outputs:
        return None
    for field, item_field in FINISH_REASON_SOURCES:
        value = outputs.get(field)
        if item_field is None:
            cleaned = _bounded(_clean_reason(value))
            if cleaned:
                return (cleaned,)
            continue
        if not isinstance(value, list):
            continue
        reasons: list[str] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            reason = _bounded(_clean_reason(entry.get(item_field)))
            if reason:
                reasons.append(reason)
        if reasons:
            # Order is part of the value: choice *n*'s reason stays at position
            # *n*, so a two-choice response whose first choice hit the token
            # limit cannot read as one that stopped cleanly.
            return tuple(reasons)
    return None


def _response_id(outputs: _Mapping[str, object] | None, /) -> str | None:
    """The provider's own id for the response — how a disputed charge is traced back.

    Class B, so :func:`_bounded` is the whole constraint: the id is opaque by
    definition and has no vocabulary to check membership against. Rejected rather
    than truncated, because a truncated id is a wrong id and a wrong id is worse
    than an absent one at exactly the moment the id is wanted.
    """
    if outputs is None:
        return None
    candidate = outputs.get(_RESPONSE_ID_FIELD)
    if not isinstance(candidate, str) or not candidate:
        return None
    return _bounded(candidate)


def _error_type(span: _ReadableSpan, /) -> str | None:
    """The class of a failure, and nothing else about it (SEM-06, D-C7).

    **This function is a security control, and the narrowness is the control.**
    An exception raised inside an MLflow span was measured carrying a planted
    marker verbatim in *both* the span's status description and the exception
    event's ``exception.message`` attribute, alongside an ``exception.stacktrace``
    attribute holding absolute filesystem paths — usernames and directory layout
    included. All of it would reach Revenium if it were forwarded (T-02-01,
    T-02-02). The exception *type* is a class name from the application's own
    code and carries no payload, which is why SEM-06's "error information" is
    read here as the class of failure and never the text of it.

    So: exactly one field is read, ``exception.type`` off the ``exception``
    event. The status description is never read — it is free text — and neither
    is the event's message or stacktrace. An ERROR span whose event names no
    type gets :data:`ERROR_TYPE_UNKNOWN` rather than losing the failure.

    Returns ``None`` for any status other than ``ERROR``, which omits the key:
    ``_OTHER`` on every successful span would put the error rate at 100%.

    **Both reads are guarded, and both guards are ``try``/``except`` because the
    span's own accessors are what raise (WR-01, T-02-09-01).** Every other access
    in :func:`map_span` is guarded by a value test — ``span.attributes or {}``,
    ``span.context is not None`` — and these two cannot be, which is why they
    were the two that survived to the verifier. Measured against the shipped
    tree, not imagined:

    * a span whose status was never set stores ``None``, and
      ``ReadableSpan.status`` hands it back unchanged, so ``.status_code`` raised
      ``AttributeError: 'NoneType' object has no attribute 'status_code'``. An
      unset status is not an error status, so the key is omitted — the same
      answer an ``OK`` span gets.
    * a span whose events were never set raises **inside the property**:
      ``ReadableSpan.events`` returns ``tuple(self._events)``, so
      ``span.events or ()`` does not guard it, because the ``or`` is never
      reached. That form would have looked like a fix and shipped the same
      ``TypeError: 'NoneType' object is not iterable``. A span with no events
      names no exception type, so an ERROR status still yields
      :data:`ERROR_TYPE_UNKNOWN` rather than losing the failure.

    Neither guard widens what is read. The status *description* is still never
    touched, which ``tests/unit/test_semconv_derivations.py`` asserts against this
    function's own source.
    """
    try:
        status_code = span.status.status_code
    except AttributeError:
        return None
    if status_code is not _StatusCode.ERROR:
        return None
    try:
        events = span.events
    except TypeError:
        events = ()
    for event in events:
        if event.name != _EXCEPTION_EVENT_NAME:
            continue
        attributes = event.attributes or {}
        recorded = attributes.get(_EXCEPTION_TYPE_ATTRIBUTE)
        if isinstance(recorded, str) and recorded:
            return recorded
    return ERROR_TYPE_UNKNOWN


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
    4. A model-name prefix through :data:`MODEL_PREFIX_PROVIDERS`, tried against
       **every** model name the span records rather than one of them
       (:func:`_model_candidates`) — **heuristic**, and last for that reason.
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

    # Every model name the span emits, in the order it emits them, against the
    # table in its declared longest-prefix-first order: the first prefix hit on
    # the first candidate that hits wins (WR-04). One candidate was not enough —
    # see :func:`_model_candidates`.
    for model in _model_candidates(attributes):
        for prefix, provider in MODEL_PREFIX_PROVIDERS:
            if model.startswith(prefix):
                return provider

    return PROVIDER_SENTINEL


def operation_for_span(attributes: _Mapping[str, object], /) -> str | None:
    """What operation this span performed — the one place that question is answered.

    Args:
        attributes: A span's raw attribute mapping. An empty mapping is a legal
            input and returns ``None``.

    Returns:
        The operation, or ``None`` when neither signal names one. A declared
        operation is returned as the shared decoder reads it — bare, never
        carrying the JSON quotes MLflow's serializer would have added.

    **The rule, in this order and no other (UD-1, GAP-1).**

    1. ``gen_ai.operation.name``, decoded through the shared reader, when the
       decoded value is a ``str``. An empty or non-string value is absent — see
       below.
    2. Otherwise ``mlflow.spanType``, decoded through the shared reader, when the
       decoded value is a key of :data:`SPAN_TYPE_TO_OPERATION`.
    3. Otherwise ``None``.

    **Why the declared operation wins.** It is the span's own explicit,
    standards-defined OTel GenAI signal — an instrumentor's assertion about what
    it did — while ``mlflow.spanType`` is a coarse vendor type that reaches an
    operation only through a three-row table. The alternative, bringing
    :func:`eligibility.classify_span` into line with the old span-type-first
    ordering here, was rejected deliberately: it would change what is *admitted*,
    which is what customers are billed for, and ``ROADMAP.md``'s Phase 2 note
    fences that off — the eligibility filter is settled in Phase 2 and cannot be
    loosened later. Changing the emitted label only changes what an
    already-admitted span is rated as.

    **This function exists so that :func:`eligibility.classify_span` and
    :func:`map_span` cannot disagree.** Before it, each module carried its own
    precedence rule and they were opposite: a span carrying
    ``gen_ai.operation.name="chat"`` and ``mlflow.spanType="EMBEDDING"`` was
    admitted as a chat completion and emitted as an embeddings call, and chat and
    embeddings rate differently. It lives here, in ``semconv.py``, and is imported
    by ``eligibility.py`` because that is the direction the existing module edge
    already runs — ``semconv`` imports nothing from ``eligibility``, and inverting
    that would create a cycle.

    **Step 1 reads through the shared decoder, and the empty declared operation
    therefore falls through (plan 02-07).** This read was raw until plan 02-07's
    ``checkpoint:decision`` — ``gate="blocking-human"`` — was answered
    ``decode-everywhere``. Two consequences follow and both were accepted on the
    record. A JSON-encoded operation now resolves to its bare value, so
    ``'"chat"'`` is admitted as ``chat`` and no longer reaches the wire carrying
    literal quotes. And ``gen_ai.operation.name = ""`` is reported absent by
    :func:`_spanattrs.decode`'s truthiness guard, so it stops rejecting the span
    and falls through to ``mlflow.spanType`` — the empty declared operation is no
    longer a rejection trigger. That widens admission, which is the direction a
    one-way-door billing predicate must not move by accident; it moved
    deliberately here, and every span shape whose verdict moved with it is pinned
    by name in ``tests/unit/test_operation_precedence.py``'s ``_VERDICT_CHANGES``
    and in :func:`_spanattrs.decode_int`'s docstring.

    Comparison at step 2 is exact over the decoded string: no case folding, no
    whitespace stripping, no Unicode normalization, matching
    :func:`eligibility.classify_span`'s own equality rule.
    """
    declared = _spanattrs.decode_str(attributes, GEN_AI_OPERATION_NAME)
    if declared is not None:
        return declared
    span_type = _spanattrs.decode_str(attributes, _spanattrs.MLFLOW_SPAN_TYPE)
    if span_type is not None and span_type in SPAN_TYPE_TO_OPERATION:
        return SPAN_TYPE_TO_OPERATION[span_type]
    return None


def _operation(attributes: _Mapping[str, object], /) -> str | None:
    """The operation to *emit*, which is :func:`operation_for_span`, bounded, or omitted.

    The resolution is not repeated here — there is exactly one precedence rule in
    this package and it lives in :func:`operation_for_span`.

    **Why the emitted operation is bounded (plan 02-08, T-02-08-06).** After plan
    02-06 promoted ``gen_ai.operation.name`` to the primary identity, the winning
    branch returns a string the *span* declared, so on any path where
    :func:`map_span` runs without :func:`eligibility.is_billable_llm_span` having
    admitted the span first, an unbounded external string reaches a rating
    dimension. That path is not hypothetical: plan 02-06's own reverse-direction
    test maps a rejected span on purpose, and Phase 8's fallback is a stated risk
    in ``STATE.md``. :func:`_bounded` cannot make a wrong operation right; it
    bounds an unbounded string, which is the disclosure half of the risk.

    **Why a cap and not an allowlist, which would otherwise be the obvious
    answer.** An operation allowlist inside this module would be a second copy of
    ``eligibility.BILLABLE_GENAI_OPERATIONS``, which this module cannot import —
    ``eligibility.py`` imports from here and never the reverse, the one module
    edge ``STATE.md`` records as breakable by a well-meaning edit. Two tables that
    happen to agree is the shape GAP-1 punished, and closing GAP-1 by re-opening
    its cause would be a poor trade. On the intended call path the value is
    already closed anyway: the gate admits only the four members of
    ``BILLABLE_GENAI_OPERATIONS``, and since plan 02-06 the gate and the mapper
    resolve the operation through the same function, so they cannot disagree
    about what it is. Moving ``BILLABLE_GENAI_OPERATIONS`` into this module so the
    operation could be membership-constrained is a coherent design and is
    deliberately not done here — it relocates a published constant that
    ``eligibility.__all__`` exports and ``tests/unit/test_mlflow_vocabulary_drift.py``
    imports, which is more change than a gap-closure run should carry.

    The remaining truthiness guard is now belt and braces rather than the
    asymmetry it once was. Plan 02-07 routed step 1 of the resolver through the
    shared decoder, whose own guard already reports an empty attribute as absent,
    so the resolver no longer hands back an empty string for this line to catch.
    It stays because what it enforces is a rule about the *wire*: T-02-08 forbids
    a present key carrying no value — the OTLP encoder ships an ``AnyValue`` with
    no field set and the backend reads that as an answer rather than as an
    absence — and a guard on the emitted value should not depend on a guard two
    functions away for its correctness.
    """
    return _bounded(operation_for_span(attributes) or None)


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

    # SEM-03, the provenance split. ``mlflow.llm.model`` is one attribute whose
    # *meaning* differs by integration: it is the **response** model on the
    # OpenAI path — MLflow prioritizes it from the response "to ensure accuracy
    # for providers like Azure OpenAI where the request 'model' parameter may
    # contain deployment name instead of the actual model name"
    # (``mlflow/openai/utils/chat_schema.py:35-39``) — and the **request** model
    # on the Anthropic path (``mlflow/anthropic/autolog.py:132``). MLflow's own
    # translator maps it unconditionally to the request key
    # (``translator.py:108-110``), which is therefore wrong for OpenAI, and
    # criterion 3 asks for both keys, so this SDK cannot inherit that
    # conflation (T-02-16). Two sources with a shared fallback is correct on
    # both integrations and degrades to MLflow's own behaviour — the same value
    # under both keys — only when inputs and outputs are both absent.
    inputs = _spanattrs.decode_mapping(source, _spanattrs.MLFLOW_SPAN_INPUTS)
    outputs = _spanattrs.decode_mapping(source, _spanattrs.MLFLOW_SPAN_OUTPUTS)
    recorded_model = _spanattrs.decode_str(source, _spanattrs.MLFLOW_LLM_MODEL)

    # ``_bounded`` is applied twice on each of these two lines, and the second
    # application is not redundant. ``_mapping_model`` bounds the mapping-derived
    # candidate, so an over-cap ``inputs["model"]`` falls through to the shared
    # fallback rather than reaching the wire. The fallback itself —
    # ``mlflow.llm.model``, read through ``decode_str`` — never passes through
    # ``_mapping_model`` at all, so without the outer call a span carrying no
    # ``mlflow.spanInputs`` and a 300-character ``mlflow.llm.model`` would emit a
    # 300-character request model. Class B is bounded at every source, not at
    # most of them.
    request_model = _bounded(_mapping_model(inputs) or recorded_model)
    if request_model:
        attributes[GEN_AI_REQUEST_MODEL] = request_model

    response_model = _bounded(_mapping_model(outputs) or recorded_model)
    if response_model:
        attributes[GEN_AI_RESPONSE_MODEL] = response_model

    response_id = _response_id(outputs)
    if response_id:
        attributes[GEN_AI_RESPONSE_ID] = response_id

    finish_reasons = _finish_reasons(outputs)
    if finish_reasons:
        attributes[GEN_AI_RESPONSE_FINISH_REASONS] = finish_reasons

    error_type = _error_type(span)
    if error_type:
        attributes[ERROR_TYPE] = error_type

    # D-02: each token count gets **exactly one** spelling, which is the opposite
    # call to the provider's two spellings below, and the asymmetry is deliberate
    # and must not be harmonized. The reason is arithmetic: a backend that sums
    # rather than dedupes duplicate keys would double the count, and these are
    # the numbers the invoice is computed from. A duplicate *string* key cannot
    # be summed, so it costs nothing; a duplicate *numeric* key can be, so it
    # costs the customer money. Same evidence, opposite answers, because the
    # failure modes are not symmetric.
    #
    # The flat fallback reads through ``_spanattrs.decode_int`` (plan 02-07), so
    # a count MLflow serialized to ``"10"`` is the same number here that it is at
    # the gate. ``_token_int`` still wraps it: the emit policy — zero is
    # forwarded, ``bool`` never is — belongs in one place, and plan 02-08's
    # negative-count rule has to land somewhere that both sources pass through.
    usage = _spanattrs.decode_mapping(source, _spanattrs.MLFLOW_CHAT_USAGE) or {}
    for field, key in _TOKEN_FIELD_TO_KEY:
        count = _token_int(usage.get(field))
        if count is None:
            count = _token_int(_spanattrs.decode_int(source, key))
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
    # SEM-08: read off the span's own fields, which are already integer
    # nanoseconds. ``mlflow.spanStartTimeNs`` is **never** consulted, and the
    # reason is that it looks like the right source and is not: it has exactly
    # one setter in MLflow (``mlflow/tracing/provider.py:345``, one code path)
    # and a real captured ``CHAT_MODEL`` span does not carry it. A mapper
    # depending on it would produce correct timings against a fixture that sets
    # it and no timings at all in production — the failure that only appears
    # after the tests are green.
    start_time_ns = span.start_time if span.start_time is not None else 0
    # SEM-08 has **two** degradations, and both are defined here rather than left
    # to arithmetic. Whether any MLflow path produces either is unestablished,
    # which is the reason to define them rather than a reason to skip them.
    #
    # 1. An unset end time is measured as the start time, so the call reads as
    #    zero-duration rather than as one that ended at the Unix epoch.
    # 2. An end time that *precedes* the start time is clamped to a zero
    #    duration. Until plan 02-09 the comment above claimed the degradation was
    #    defined while covering only case 1, and a backwards clock produced a
    #    negative duration verbatim (reproduced: start 200, end 100, duration
    #    -100). Zero is the right answer because a negative duration reads
    #    downstream as a corrupt record rather than as a short call, and because
    #    the OTel SDK's ``time_ns()`` timestamps carry no monotonicity guarantee
    #    across a wall-clock step — so the backwards case is a clock artefact,
    #    not a measurement to forward.
    end_time_ns = span.end_time if span.end_time is not None else start_time_ns
    duration_ns = max(end_time_ns - start_time_ns, 0)

    return MappedSpan(
        # D-04 applied rather than merely declared (WR-03, T-02-08-04). Before
        # this filter, ``EMITTED_ATTRIBUTE_KEYS`` was consulted by nothing at
        # runtime: the closed allowlist was a naming convention plus a
        # fixture-driven test, and a fixture-driven test can only say that *the
        # spans in the sweep* emit no stray key. That is a statement about the
        # fixtures. This is a statement about the function — a key no constant
        # sanctions cannot reach the wire even from a code path no fixture
        # exercises, which is the "leaks nobody thought of" case the module
        # docstring already claims the allowlist structurally prevents.
        attributes=_types.MappingProxyType(
            {key: value for key, value in attributes.items() if key in EMITTED_ATTRIBUTE_KEYS}
        ),
        kind=_SpanKind.CLIENT,
        trace_id=format(context.trace_id, "032x") if context is not None else _ABSENT_TRACE_ID,
        span_id=format(context.span_id, "016x") if context is not None else _ABSENT_SPAN_ID,
        parent_span_id=format(parent.span_id, "016x") if parent is not None else None,
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
        duration_ns=duration_ns,
    )
