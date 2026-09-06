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
6. **An emitted provider value outgrowing the cap.** Steps 1 and 2 forward a
   string written by code this SDK does not control, so the value's length is
   the application's to choose. Emitted unbounded, it is a billing attribute
   that carries whatever the customer happened to put in a provider-shaped
   field — reproduced in ``02-REVIEW.md`` at 264 code points carrying a
   credential (CR-01). The boundary pair below fails whichever way the cap
   breaks: absent, and the over-cap value goes to the wire; blanket, and the
   at-cap value that should survive does not.

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
from collections.abc import Callable

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from revenium_mlflow.tracing.eligibility import EligibilityReason, classify_span
from revenium_mlflow.tracing.semconv import (
    PROVIDER_SENTINEL,
    RESOURCE_PROVIDER_CLAIM,
    infer_provider,
    map_span,
    resource_claim_attributes,
)
from tests.fixtures.spans import build_readable_span, openai_autolog_shaped_span

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

#: The set the backend's ``GenAISemanticConventionMapper.canHandle`` rejects on,
#: checked against both ``service.name`` and the instrumentation scope name.
#: Spelled here as a literal rather than imported from anywhere, so a change on
#: the backend side surfaces as a deliberate edit to this file instead of being
#: silently agreed with. Cited from ``.planning/research/BACKEND-CONTRACT.md:133``.
_KNOWN_CUSTOM_SDK_NAMES = frozenset({"claude-code", "gemini-cli", "codex_exec", "codex_cli_rs"})

#: The character cap this file expects, held as a literal rather than imported
#: from the module under test — the independent-copy rule again, and
#: ``test_semconv_derivations.py`` records the same figure the same way. It is
#: used to *build* the boundary values below, so moving the module's cap in
#: either direction reds the pair: raise it and the 65-code-point value stops
#: becoming the sentinel, lower it and the 64-code-point value stops surviving.
_MAX_EMITTED_VALUE_CHARS = 64

#: The CR-01 reproduction, transcribed from ``02-REVIEW.md`` so the tests below
#: run against the recorded evidence rather than a paraphrase of it. The
#: credential is synthetic and always was — no live key appears in this file,
#: and nothing here is read from an environment variable.
_CREDENTIAL_MARKER = "rev_sk_SUPERSECRET_KEY"
_CREDENTIAL_URL = f"https://user:{_CREDENTIAL_MARKER}@api.internal.example.com/v1 "

#: Padded to the 264 code points the review recorded, with the repeated
#: character it recorded, so the length in the transcript is the length here.
_CREDENTIAL_PROVIDER = _CREDENTIAL_URL + "A" * (264 - len(_CREDENTIAL_URL))


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


def test_the_message_format_wins_over_the_model_prefix() -> None:
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


def test_a_house_aliased_model_attribute_does_not_send_a_claude_span_to_the_sentinel() -> None:
    """WR-04: inference and the emitted request model must read the same names.

    ``mlflow.llm.model`` and ``mlflow.spanInputs["model"]`` disagree here, which
    the SEM-03 comment in ``map_span`` says is the normal case on OpenAI and
    Azure — a gateway alias, an internal name, a fine-tune with a house prefix.
    Inference used to consult only the first, so this span went out labelled with
    the unknown-provider sentinel while carrying, in its own emitted attributes,
    a model name the prefix table resolves.

    Both halves live in one test deliberately, in the style this file already
    uses for criterion 4: the inference assertion alone would pass on a build
    that emitted some other model, and what is wrong in that case is the
    relationship between the two, not either one on its own.
    """
    span = _provider_span(model="house-alias-v3", inputs_model="claude-sonnet-4-5")

    assert infer_provider(span) == "anthropic"
    assert map_span(span).attributes["gen_ai.request.model"] == "claude-sonnet-4-5"


def test_a_capitalised_model_does_not_match_the_prefix_table() -> None:
    """SEM-01's encoding edge at step 4, the twin of the message-format case above.

    Comparison is exact over the decoded value at both heuristic steps: no case
    folding and no Unicode normalization. ``GPT-4o`` therefore falls through to
    the sentinel rather than matching ``gpt-``. Folding would be a second,
    undeclared rule about what counts as the same model — and now that step 4
    consults every model the span records, a fold would apply to two strings
    rather than one.
    """
    span = _provider_span(model="GPT-4o")

    assert infer_provider(span) == PROVIDER_SENTINEL


def test_an_empty_attribute_mapping_infers_the_sentinel_and_never_an_empty_string() -> None:
    """SEM-01's empty-input edge, asserted as three claims rather than one.

    ``test_a_span_with_an_empty_attribute_map_infers_the_sentinel`` above already
    says the degenerate input returns the sentinel rather than raising. This one
    says what SEM-01 actually requires of the returned value: that it is not
    empty, and that it is not the resource claim. An empty provider key drops the
    payload to the backend's ``GenericFallbackMapper``, which rates it under
    ``"Unknown"`` with no error on either side; returning the resource claim
    instead would make "we could not infer this span's provider" indistinguishable
    from "the resource claim is doing its job" (D-C2).
    """
    span = build_readable_span(attributes={}, start_time_ns=_START_NS, end_time_ns=_END_NS)

    inferred = infer_provider(span)

    assert inferred == PROVIDER_SENTINEL
    assert inferred != ""
    assert inferred != RESOURCE_PROVIDER_CLAIM


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


# --- Criterion 4: the OpenAI-autolog-shaped span -----------------------------


def test_the_criterion_four_fixture_carries_no_mlflow_provider_attribute() -> None:
    """The fixture must not drift into proving something easier.

    MLflow's OpenAI autolog never writes ``mlflow.llm.provider`` — established
    positively by enumerating what that path *does* write, not by a grep that
    found nothing. If this attribute ever appeared on the fixture, the inference
    assertion below would pass through step 1 and prove nothing about step 3,
    which is the step SEM-02 exists for.
    """
    span = openai_autolog_shaped_span()

    assert "mlflow.llm.provider" not in (span.attributes or {})


def test_the_criterion_four_fixture_carries_what_the_openai_path_writes() -> None:
    """Positively established, not assumed: four attributes, and exactly four.

    ``mlflow/openai/autolog.py`` sets ``mlflow.message.format`` and
    ``mlflow.chat.tokenUsage`` directly; the model arrives through
    ``set_span_chat_attributes``, which writes one key and never
    ``SpanAttributeKey.MODEL_PROVIDER``.
    """
    span = openai_autolog_shaped_span()

    assert set(span.attributes or {}) == {
        "mlflow.spanType",
        "mlflow.llm.model",
        "mlflow.chat.tokenUsage",
        "mlflow.message.format",
    }


def test_an_openai_autolog_shaped_span_infers_openai() -> None:
    """SEM-01 criterion 4, and the headline assertion of this plan.

    Without step 3 this span reaches Revenium with the sentinel — or, before
    D-13, with no provider key at all, in which case
    ``GenAISemanticConventionMapper.canHandle`` declines it and
    ``GenericFallbackMapper`` rates the whole batch under ``"Unknown"`` with no
    error on either side.
    """
    assert infer_provider(openai_autolog_shaped_span()) == "openai"


def test_the_mapped_openai_span_carries_openai_rather_than_the_sentinel() -> None:
    """The same claim one layer out: what ``map_span`` actually puts on the wire.

    Inference could be right while the emission site read a stale local.
    """
    attributes = map_span(openai_autolog_shaped_span()).attributes

    assert attributes["gen_ai.provider.name"] == "openai"


# --- D-16: one value, both spellings -----------------------------------------


def test_a_mapped_span_carries_both_provider_spellings() -> None:
    """Both keys present. The older spelling is what an unverified backend build
    may still be reading, and dropping it as redundant is a change nobody could
    detect from the client side.
    """
    attributes = map_span(openai_autolog_shaped_span()).attributes

    assert {"gen_ai.provider.name", "gen_ai.system"} <= set(attributes)


def test_both_provider_spellings_carry_the_same_value() -> None:
    """Two spellings of one fact, not two facts.

    If these could diverge, the backend would have two answers to "who provided
    this" and no rule for choosing between them.
    """
    attributes = map_span(openai_autolog_shaped_span()).attributes

    assert attributes["gen_ai.provider.name"] == attributes["gen_ai.system"]


# --- CR-01: the emitted provider value is bounded ----------------------------


def _step_one_provider_span(provider: str) -> ReadableSpan:
    """An ADMITTED span whose only provider signal is MLflow's own assertion.

    ``mlflow.llm.provider`` is ``json.dumps``-ed because that is the shape
    MLflow's serializer puts on the wire, and ``gen_ai.usage.input_tokens``
    carries the token evidence :func:`classify_span` requires — without it the
    span is dropped before ``map_span`` is reached and an assertion about what
    ``map_span`` emits would be an assertion about a span nothing rates.
    """
    return build_readable_span(
        attributes={
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "mlflow.llm.provider": json.dumps(provider),
            "gen_ai.usage.input_tokens": 5,
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


def _step_two_provider_span(provider: str) -> ReadableSpan:
    """The same span through step 2: a bridged instrumentor's own assertion.

    Bare rather than JSON-encoded — a non-MLflow OTel instrumentor writes a real
    OpenTelemetry attribute. The review reproduced the leak on this path too, at
    500 code points, so a cap applied to one source path and not the other would
    read here as a working fix.
    """
    return build_readable_span(
        attributes={
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "gen_ai.provider.name": provider,
            "gen_ai.usage.input_tokens": 5,
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


def _admitted_span_with_no_provider_signal() -> ReadableSpan:
    """An ADMITTED span carrying no provider signal at any of the five steps."""
    return build_readable_span(
        attributes={
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "gen_ai.usage.input_tokens": 5,
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


#: Both source paths a provider value can arrive on, so every boundary assertion
#: below runs against each. One path bounded and the other not is the shape a
#: single-factory test cannot tell apart from a working cap.
_PROVIDER_SOURCE_PATHS = (
    pytest.param(_step_one_provider_span, id="step1-mlflow-llm-provider"),
    pytest.param(_step_two_provider_span, id="step2-gen-ai-provider-name"),
)


@pytest.mark.parametrize("factory", _PROVIDER_SOURCE_PATHS)
def test_a_provider_at_the_cap_reaches_both_spellings_whole(
    factory: Callable[[str], ReadableSpan],
) -> None:
    """The value that fits survives, entire, under both D-16 spellings.

    This is the half that makes the pair a boundary rather than a blanket drop.
    A cap asserted only from above is indistinguishable from rejecting every
    provider name outright, and rejecting every provider name reads downstream
    as one customer's whole history attributed to the sentinel — no error on
    either side.
    """
    at_cap = "p" * _MAX_EMITTED_VALUE_CHARS

    attributes = map_span(factory(at_cap)).attributes

    assert (attributes["gen_ai.provider.name"], attributes["gen_ai.system"]) == (at_cap, at_cap)


@pytest.mark.parametrize("factory", _PROVIDER_SOURCE_PATHS)
def test_a_provider_one_character_over_the_cap_becomes_the_sentinel(
    factory: Callable[[str], ReadableSpan],
) -> None:
    """One code point over, and both spellings carry step 5's answer instead.

    This is the half that makes the pair a cap rather than no cap at all. An
    over-cap string is not a provider name — it is an unbounded blob sitting in
    a provider-shaped attribute — so it takes the answer the chain already
    declares for "no provider I can name" (D-CR01).
    """
    over_cap = "p" * (_MAX_EMITTED_VALUE_CHARS + 1)

    attributes = map_span(factory(over_cap)).attributes

    assert (attributes["gen_ai.provider.name"], attributes["gen_ai.system"]) == (
        PROVIDER_SENTINEL,
        PROVIDER_SENTINEL,
    )


def test_an_over_cap_provider_leaves_both_provider_keys_present() -> None:
    """Rejecting the value must not drop the key — D-13 / SEM-01, unconditionally.

    Asserted separately from the value so that a future change from substitution
    to omission reds here by name. Omission would emit an eligible, billable
    span with no provider at all, which the backend's
    ``GenAISemanticConventionMapper`` declines and ``GenericFallbackMapper``
    rates under ``"Unknown"`` with no error on either side — the exact outcome
    step 5 exists to prevent.
    """
    span = _step_one_provider_span("p" * (_MAX_EMITTED_VALUE_CHARS + 1))

    assert {"gen_ai.provider.name", "gen_ai.system"} <= set(map_span(span).attributes)


def test_the_credential_reproduction_is_admitted_and_carries_its_marker() -> None:
    """The known-dirty precondition, without which the absence test below is empty.

    Both halves are one precondition and are asserted together deliberately: a
    clean absence result is exactly what a check inspecting nothing also
    produces. This span has to be the thing the mapper reads *and* the thing the
    gate admits, or the assertion in the next test is about a span nobody rates.
    That is the discipline ``test_semconv_allowlist.py`` records, and the GAP-2
    failure it was written after.
    """
    span = _step_one_provider_span(_CREDENTIAL_PROVIDER)
    raw = span.attributes or {}

    assert _CREDENTIAL_MARKER in str(raw["mlflow.llm.provider"])
    assert classify_span(span) is EligibilityReason.ADMITTED


def test_the_credential_marker_reaches_neither_emitted_provider_value() -> None:
    """CR-01 itself: the 264-code-point reproduction no longer goes to the wire.

    The leak was duplicated across both spellings, so both are swept. A test
    over one key would pass while the other kept exporting the credential.
    """
    attributes = map_span(_step_one_provider_span(_CREDENTIAL_PROVIDER)).attributes
    emitted = (attributes["gen_ai.provider.name"], attributes["gen_ai.system"])

    assert not any(_CREDENTIAL_MARKER in str(value) for value in emitted)


def test_the_sentinel_is_short_enough_to_survive_its_own_cap() -> None:
    """The fallback cannot reject itself, asserted rather than left to inspection.

    A sentinel longer than the cap would make the rejection path either recurse
    or emit nothing — and it would fail on exactly the spans the cap fires on,
    which are the ones no fixture in this repository has.
    """
    assert len(PROVIDER_SENTINEL) <= _MAX_EMITTED_VALUE_CHARS


def test_an_over_cap_provider_emits_what_no_provider_signal_at_all_emits() -> None:
    """One spelling of "unknown", not two, so the two paths cannot drift apart.

    If the rejection path grew its own literal, one customer's spans would split
    across two provider labels — each reading as correct forever, and neither
    discoverable from the client side. This is drift 4 applied to the new path.
    """
    rejected = map_span(_step_one_provider_span("p" * (_MAX_EMITTED_VALUE_CHARS + 1))).attributes
    absent = map_span(_admitted_span_with_no_provider_signal()).attributes

    assert rejected["gen_ai.provider.name"] == absent["gen_ai.provider.name"]


# --- SEM-02: the resource claim set ------------------------------------------


def test_the_resource_claim_has_exactly_the_two_provider_keys() -> None:
    """These two keys are what ``canHandle`` checks the resource for.

    Any other key is inert there, and a missing one is the whole payload
    dropping to the generic fallback.
    """
    assert sorted(resource_claim_attributes()) == ["gen_ai.provider.name", "gen_ai.system"]


def test_both_resource_claim_keys_carry_the_claim_literal() -> None:
    """Same D-16 reason as the per-span pair: one value, both spellings."""
    assert set(resource_claim_attributes().values()) == {"revenium-mlflow-sdk"}


def test_the_resource_claim_takes_no_span_and_is_deterministic() -> None:
    """Two calls, equal mappings — the claim is not order- or concurrency-dependent.

    D-15 rejected first-eligible-span-wins for exactly this: it is
    nondeterministic under concurrency and it actively mislabels a process
    calling two providers by whichever span happened to arrive first.
    """
    assert resource_claim_attributes() == resource_claim_attributes()


def test_the_resource_claim_is_the_recorded_literal() -> None:
    """Costly to reverse (D-15): once emitted, this is what the backend indexed.

    Changing it risks a window in which payloads are claimed by a different
    mapper than the one that claimed the earlier ones.
    """
    assert RESOURCE_PROVIDER_CLAIM == "revenium-mlflow-sdk"


def test_the_sentinel_is_the_recorded_literal() -> None:
    """Costly to reverse (D-13): changing it splits one customer's
    unknown-provider history across two labels, an undo that touches stored data
    rather than code.
    """
    assert PROVIDER_SENTINEL == "revenium-unknown-provider"


def test_the_resource_claim_differs_from_the_per_span_sentinel() -> None:
    """Two distinct literals, deliberately (D-C2).

    It is what lets a Phase 6 diagnostic tell "we could not infer this span's
    provider" apart from "the resource claim is doing its job". Collapsing them
    would make those two states indistinguishable in the field.
    """
    assert RESOURCE_PROVIDER_CLAIM != PROVIDER_SENTINEL


def test_the_resource_claim_is_not_a_rejected_sdk_name() -> None:
    """A collision here silently routes every payload to the generic fallback.

    ``canHandle`` returns ``false`` before it ever looks at the provider keys if
    the resource's ``service.name`` or the scope name is in this set.
    """
    assert RESOURCE_PROVIDER_CLAIM not in _KNOWN_CUSTOM_SDK_NAMES


def test_the_sentinel_is_not_a_rejected_sdk_name() -> None:
    """Same check on the other literal, for the same reason.

    The sentinel is a span attribute rather than a resource attribute today, but
    both literals are SDK-owned names the backend may come to match on, and the
    cost of the extra assertion is one line.
    """
    assert PROVIDER_SENTINEL not in _KNOWN_CUSTOM_SDK_NAMES


def test_neither_literal_lowercases_to_the_generic_fallback_provider_id() -> None:
    """``GenericFallbackMapper`` rates under provider id ``"Unknown"``.

    A sentinel that case-folds into that bucket would merge the SDK's visible,
    correctable unknown with the silent fallback it exists to stay out of —
    partly defeating D-13. Assumption A3 (whether the backend matches provider
    ids case-sensitively) is unverifiable without calling production, so the
    literals avoid the question rather than answer it.
    """
    assert {PROVIDER_SENTINEL.lower(), RESOURCE_PROVIDER_CLAIM.lower()}.isdisjoint({"unknown"})


def test_the_model_prefix_table_is_ordered_longest_prefix_first() -> None:
    """D-C5's ordering invariant, asserted in the tree rather than by a one-off probe.

    Matching at step 4 is first-hit, so the order of this table decides the
    answer. Today no shorter entry is a prefix of a longer one, so a reshuffle
    changes no result and every behavioural test above stays green — which is
    exactly why this assertion is structural. The first entry pair that *does*
    overlap would otherwise be mislabelled silently, and a mislabelled provider
    is not discoverable by the customer.

    Importing the table here is not the thing the module docstring forbids. That
    rule is about asserting the chain's *answers* against the table, which would
    agree with any future edit to it. This asserts a property the table must
    have whatever its contents are — the same distinction
    ``tests/unit/test_eligibility.py`` draws when it cross-checks type *names*
    while keeping every billing verdict an independent literal.
    """
    from revenium_mlflow.tracing.semconv import MODEL_PREFIX_PROVIDERS

    lengths = [len(prefix) for prefix, _ in MODEL_PREFIX_PROVIDERS]

    assert lengths == sorted(lengths, reverse=True)
