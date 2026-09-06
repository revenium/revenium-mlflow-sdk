"""Provider inference: the five-step chain, the sentinel, and the resource claim.

``gen_ai.provider.name`` is customer-visible rating data. Every assertion below
exists because a specific way of getting it wrong is silent — the payload still
exports, the request still succeeds, and the number on the invoice is attributed
to the wrong provider or to nobody.

The drifts this file exists to catch, each named so a red run is attributable:

1. **The chain reordered.** A heuristic overwriting an assertion MLflow or a
   bridged instrumentor already made. The five ladder tests each supply exactly
   the signals needed to prove one step wins over the one below it.
2. **A framework value promoted to a provider name.** Roughly a third of the
   thirty-plus observed ``mlflow.message.format`` values name a framework rather
   than a provider. ``langchain`` becoming a provider called ``langchain`` is a
   false attribution the customer cannot discover and the SDK cannot correct
   retroactively. The parametrized non-promotion test is that prohibition made
   mechanical.
3. **The provider key going empty or absent.** The backend's
   ``GenAISemanticConventionMapper`` would decline the payload and
   ``GenericFallbackMapper`` would rate it under provider id ``"Unknown"`` with
   no error on either side — a billing event with no attributable cause.
4. **Google's two spellings drifting apart.** The ``gemini`` message format and
   the ``gemini-`` model prefix must both yield the literal ``google``. Two
   spellings would not surface as a conflict; they would surface as one
   customer's history split across two provider labels, each reading as correct
   forever.
5. **Either costly-to-reverse literal changing.** Both are pinned against their
   recorded value here, because once traffic has landed they are what the
   backend has indexed.

**Every expected provider value below is spelled as a literal.** Importing
``MESSAGE_FORMAT_PROVIDERS`` and asserting the chain against it would produce a
test that agrees with every future edit to that table — and the table is exactly
what must not change unnoticed. This is the independent-copy rule
``tests/unit/test_attributes.py`` records as load-bearing.

Every span is built from ``tests/fixtures/spans.py``. That module is plan
02-01's and is imported unmodified: a builder four plans extend independently is
how two fixtures come to disagree about what an MLflow span looks like. Shapes
too narrow to earn a named helper are built from :func:`build_readable_span` at
the call site, which is the path that module's own docstring prescribes — and
which is why the MLflow-namespaced values below are ``json.dumps``-ed here while
the ``gen_ai.*`` ones are not. MLflow serializes every span attribute to JSON
before it reaches OpenTelemetry; a bridged instrumentor writes bare values.

One assertion per test, except the Google-spelling test, which deliberately
carries both halves so that changing one step and not the other fails here.
"""

import json

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from revenium_mlflow.tracing.semconv import (
    PROVIDER_SENTINEL,
    infer_provider,
)
from tests.fixtures.spans import build_readable_span

pytestmark = pytest.mark.unit

#: Transcribed from the captured span, so a duration is a real difference.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000

#: The eight ``mlflow.message.format`` values that name a framework rather than a
#: provider. Enumerated from a grep over the installed MLflow's thirty-plus
#: ``MESSAGE_FORMAT`` setters and recorded in
#: ``02-RESEARCH.md`` §"The replacement: mlflow.message.format".
_FRAMEWORK_FORMATS = (
    "langchain",
    "llamaindex",
    "dspy",
    "crewai",
    "ag2",
    "autogen",
    "smolagents",
    "pydantic_ai",
)


def _provider_span(
    *,
    span_type: str | None = "CHAT_MODEL",
    mlflow_provider: str | None = None,
    genai_provider_name: str | None = None,
    genai_system: str | None = None,
    message_format: str | None = None,
    model: str | None = None,
    inputs_model: str | None = None,
) -> ReadableSpan:
    """One span carrying exactly the provider signals a test names, and no others.

    Absent means absent: a parameter left at ``None`` writes no attribute at all,
    rather than writing an empty one. That distinction is the whole point of a
    precedence test — a key present with an empty value would exercise the
    truthiness guard instead of the step ordering.
    """
    attributes: dict[str, object] = {}
    if span_type is not None:
        attributes["mlflow.spanType"] = json.dumps(span_type)
    if mlflow_provider is not None:
        attributes["mlflow.llm.provider"] = json.dumps(mlflow_provider)
    if message_format is not None:
        attributes["mlflow.message.format"] = json.dumps(message_format)
    if model is not None:
        attributes["mlflow.llm.model"] = json.dumps(model)
    if inputs_model is not None:
        attributes["mlflow.spanInputs"] = json.dumps({"model": inputs_model})
    # Bare, not JSON-encoded: these are real OpenTelemetry attributes written by
    # an instrumentor that never heard of MLflow (the Path A case).
    if genai_provider_name is not None:
        attributes["gen_ai.provider.name"] = genai_provider_name
    if genai_system is not None:
        attributes["gen_ai.system"] = genai_system
    return build_readable_span(
        attributes=attributes,
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


# --- The precedence ladder, one test per step ------------------------------


def test_mlflows_own_provider_assertion_wins_over_every_lower_signal() -> None:
    """Step 1 is authoritative: MLflow asserted it, so nothing may overrule it.

    If a lower step could win here, an Anthropic call routed through a
    format-tagged integration would be billed to whichever provider the model
    name happened to look like.
    """
    span = _provider_span(mlflow_provider="anthropic", message_format="openai", model="gpt-4o")

    assert infer_provider(span) == "anthropic"


def test_a_provider_name_already_on_the_span_wins_over_the_message_format() -> None:
    """Step 2: a bridged OTel instrumentor's own assertion outranks a heuristic.

    Overwriting it would mean the SDK second-guessing an instrumentor that was
    closer to the call than MLflow was.
    """
    span = _provider_span(genai_provider_name="cohere", message_format="openai", model="gpt-4o")

    assert infer_provider(span) == "cohere"


def test_gen_ai_system_is_read_when_the_current_spelling_is_absent() -> None:
    """Step 2's compatibility half: an instrumentor on the older spelling still counts.

    Reading only the current spelling would silently drop the assertion of every
    instrumentor that has not migrated, and fall through to a heuristic.
    """
    span = _provider_span(genai_system="cohere", message_format="openai", model="gpt-4o")

    assert infer_provider(span) == "cohere"


def test_the_message_format_wins_over_the_model_name_prefix() -> None:
    """Step 3 outranks step 4: which integration emitted the span is structural.

    The model name is a heuristic that proxies and aliases defeat; the format
    value is written by the integration itself.
    """
    span = _provider_span(message_format="anthropic", model="gpt-4o")

    assert infer_provider(span) == "anthropic"


def test_the_model_prefix_is_consulted_when_no_higher_signal_fires() -> None:
    """Step 4 is the last thing before the sentinel, and it does fire.

    If it did not, every span from an integration that sets no provider and no
    recognized format would rate as an unknown provider.
    """
    span = _provider_span(model="claude-sonnet-4-5")

    assert infer_provider(span) == "anthropic"


def test_a_span_with_no_provider_signal_at_all_infers_the_sentinel() -> None:
    """Step 5: the key is never empty, so SEM-01 holds unconditionally.

    An omitted or empty provider key drops the payload to the backend's generic
    fallback, which rates it under ``"Unknown"`` and reports nothing.
    """
    span = _provider_span(model="some-internal-alias-v3")

    assert infer_provider(span) == PROVIDER_SENTINEL


# --- The model-prefix table, as behaviour rather than as a table -------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("chatgpt-4o-latest", "openai"),
        ("claude-sonnet-4-5", "anthropic"),
        ("gemini-2.0-flash", "google"),
        ("mistral-large-latest", "mistral"),
        ("command-r-plus", "cohere"),
        ("llama-3.1-70b", "meta"),
    ],
)
def test_the_model_prefix_infers_the_recorded_provider(model: str, expected: str) -> None:
    """Each prefix maps to one provider, spelled as a literal here.

    Asserting against the table itself would agree with any future edit to it,
    including one that silently re-labels a customer's traffic.
    """
    span = _provider_span(model=model)

    assert infer_provider(span) == expected


def test_the_model_is_read_from_span_inputs_when_the_model_attribute_is_absent() -> None:
    """The request kwargs carry the model on paths that set no model attribute.

    Reading only ``mlflow.llm.model`` would send those spans to the sentinel
    while the answer was sitting one key away.
    """
    span = _provider_span(inputs_model="claude-opus-4-1")

    assert infer_provider(span) == "anthropic"


# --- The prohibition: no framework value becomes a provider name -------------


@pytest.mark.parametrize("framework", _FRAMEWORK_FORMATS)
def test_a_framework_message_format_is_not_promoted_to_a_provider(framework: str) -> None:
    """A positive allowlist, not a denylist — the structural form of the prohibition.

    ``langchain`` named as the provider on an invoice is a false attribution the
    customer has no way to discover. A denylist would let the next MLflow
    framework integration invent a provider name by accident; non-membership of
    a positive table cannot.
    """
    span = _provider_span(message_format=framework)

    assert infer_provider(span) != framework


@pytest.mark.parametrize("framework", _FRAMEWORK_FORMATS)
def test_a_framework_message_format_falls_all_the_way_to_the_sentinel(framework: str) -> None:
    """Not merely "not the framework name" — nothing else is invented either.

    A future edit could satisfy the test above by mapping ``langchain`` to some
    other wrong provider. This one says the fall-through goes where it should.
    """
    span = _provider_span(message_format=framework)

    assert infer_provider(span) == PROVIDER_SENTINEL


def test_a_capitalised_message_format_does_not_match_the_allowlist() -> None:
    """Comparison is exact over the decoded value: no case folding, no normalization.

    Folding would be a second, undeclared rule about what counts as the same
    provider — and it would silently admit values MLflow never writes.
    """
    span = _provider_span(message_format="OpenAI")

    assert infer_provider(span) == PROVIDER_SENTINEL


def test_a_span_with_an_empty_attribute_map_infers_the_sentinel() -> None:
    """The degenerate input returns a string rather than raising.

    ``infer_provider`` runs inside a ``SpanProcessor`` callback for every span in
    the host process. Raising there would fail an export batch over one
    malformed span.
    """
    span = build_readable_span(attributes={}, start_time_ns=_START_NS, end_time_ns=_END_NS)

    assert infer_provider(span) == PROVIDER_SENTINEL


# --- D-C8: one provider, one spelling, across every step ---------------------


def test_both_google_signals_infer_the_same_literal() -> None:
    """Deliberately two assertions: the point is that the two steps agree.

    ``mlflow.message.format`` is spelled ``gemini`` and the model prefix is
    ``gemini-``; both must yield ``google``. Splitting them across two tests
    would let one be updated and the other left behind, which is the failure
    this test exists to prevent — one customer's Gemini history under two
    provider labels, each of which then reads as correct forever.
    """
    from_format = infer_provider(_provider_span(message_format="gemini"))
    from_model = infer_provider(_provider_span(model="gemini-2.0-flash"))

    assert from_format == "google"
    assert from_model == "google"
