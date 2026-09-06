"""D-04: the emit set is closed, and nothing else has a path to the wire.

``map_span`` reads ``mlflow.spanInputs`` and ``mlflow.spanOutputs``, which hold
the full serialized provider request and response — prompt text, completion
text, system instructions, tool arguments, tool results. It also runs on spans
carrying MLflow's own LiteLLM-derived cost estimate. Both are one field access
away at every mapping, and both are forbidden: PROJECT.md rules content capture
out of scope on privacy grounds disproportionate to the metering need, and names
Revenium as the authoritative rating source, so a second cost signal arriving
alongside the token counts is a billing input nobody decided to trust.

A denylist stops the leaks someone thought of. **A closed allowlist stops the
ones nobody did**, because a value cannot escape a set it is not a member of.
This file is that set asserted mechanically, against the three drifts it exists
to catch:

*A key added to the module without being added to the closed set.* Caught by the
constants-into-the-set direction, and by the scan for any other module-level
constant holding an attribute-key-shaped value.

*A key added to the set without a named constant.* Caught by the
set-members-back-to-constants direction.

*A value reaching the wire that no constant names.* Caught by the sweep: every
fixture helper the shared builder exports, mapped with and without environment
and region, with the union of emitted keys required to be a subset of the closed
set.

**The expectation is a literal, and that is the whole value of the file.**
Comparing ``EMITTED_ATTRIBUTE_KEYS`` only against the module's own constants
proves internal consistency and nothing about whether the right keys are in it —
both sides move together on a rename. The independent copy below is what makes a
dropped or renamed key a failure rather than a silent change to what the backend
rates on. ``tests/unit/test_attributes.py`` records the same reasoning for the 21
attribution keys.

**The cost guard and the namespace guard are two tests, not one, and neither is
redundant.** This is the Phase 1 house style, where a guard that matters is
enforced twice by non-overlapping mechanisms — the same argument
``pyproject.toml``'s banned-api comment records for the private-access wall's
fast and slow halves. A future field named for something other than cost slips
the cost guard; a cost field that does not carry the MLflow namespace slips the
namespace guard. Deleting either as redundant re-opens exactly one of those two
holes.

**The sweep is the mechanism, and it derives its own subject list.** A guard
asserted against one fixture proves only that one fixture is clean. Building the
list from every public helper ``tests/fixtures/spans.py`` exports is what makes
the claim about the mapper — and it means a fixture added to the builder later is
covered automatically. A helper that grows a *required* parameter fails loudly
here until someone adds it to :data:`_REQUIRED_ARGUMENTS`, rather than being
silently skipped.

**The content-leak assertion proves its subject known-dirty first.** A clean
result is exactly what a check inspecting nothing also produces, so each planted
string is asserted present on the span it was planted in *before* its absence
from the output means anything. ``tests/fixtures/planted_private_access.py``
records the same discipline for the private-access scanner.

**Known-dirty is necessary and was not sufficient, which is the lesson plan
02-08 exists to record.** The predecessor of the control below planted its
markers in ``messages[].content`` and ``choices[].message.content`` and proved
them present on the span — and ``map_span`` reads neither path. The precondition
passed, the absence assertion passed, and a credential-bearing URL reached
``gen_ai.response.finish_reasons`` verbatim the whole time (GAP-2, WR-06). A
marker has to be planted where the function under test *reads*, not merely
somewhere on its input.

**Planting where the mapper reads forces a question the old control never had to
answer: which keys is an absence assertion entitled to cover?** Not all of them.
Every marker below therefore belongs to exactly one declared value class, and
the class decides which assertion sees it:

*Class A — closed-set values.* ``gen_ai.response.finish_reasons`` and
``error.type`` may carry only a member of a closed set, so an absence assertion
is entitled to cover them. :data:`_FORBIDDEN_CONTENT` is swept against them by
:func:`test_no_emitted_value_carries_any_forbidden_content`.

*Class B — identifier values.* ``gen_ai.request.model``,
``gen_ai.response.model``, ``gen_ai.response.id`` and ``gen_ai.operation.name``
carry the provider's or the span's own identifier, bounded by a character cap
and by nothing else. SEM-03 *requires* the provider's own model string, so an
absence assertion over these could only ever be made green by deleting the
plant. :data:`_FORWARDED_IDENTIFIERS` is asserted **present** on them by
:func:`test_the_model_and_id_keys_forward_the_providers_own_string` instead. The
perimeter is a written decision, not whatever the sweep happened to cover.

*Class B with a fallback — the provider pair.* ``gen_ai.provider.name`` and
``gen_ai.system`` were classified nowhere, and that omission is what let them
ship emitted unbounded (CR-01, reproduced at 264 code points carrying a
credential). They are Class B: bounded by length, and by nothing else, because
an allowlist there would drop every provider this SDK has not heard of. They
differ from the four keys above in what a rejection does — an over-cap value is
replaced by ``PROVIDER_SENTINEL`` rather than omitting the key, because the
provider key is never permitted to be absent (D-13, SEM-01).

They are deliberately **not** added to the :data:`_FORBIDDEN_CONTENT` sweep. A
sub-cap provider string is forwarded verbatim by design — that is the same shape
as the accepted T-02-08-07 residual — so an absence assertion over them could
only ever be made green by deleting the plant, exactly as for the four
identifier keys. Their boundary is pinned in
``tests/unit/test_semconv_provider.py`` instead, from both sides and on both
source paths.
"""

import inspect
import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.util.types import AttributeValue

from revenium_mlflow.tracing import semconv
from tests.fixtures import spans as span_fixtures

pytestmark = pytest.mark.unit

#: The fourteen keys, spelled out. An independent copy of the contract, not a
#: view of the module — see the module docstring.
_EXPECTED_EMITTED_KEYS = frozenset(
    {
        "gen_ai.provider.name",
        "gen_ai.system",
        "gen_ai.operation.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.response.id",
        "gen_ai.response.finish_reasons",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.cache_read_input_tokens",
        "gen_ai.usage.cache_creation_input_tokens",
        "error.type",
        "deployment.environment.name",
        "cloud.region",
    }
)

#: The constant *names* that are supposed to hold those fourteen keys. Named
#: rather than derived, because "which constants are emit keys" is itself part of
#: the contract: ``ERROR_TYPE_UNKNOWN``, ``PROVIDER_SENTINEL`` and
#: ``RESOURCE_PROVIDER_CLAIM`` are public string constants that are deliberately
#: *not* keys, and a rule clever enough to exclude them automatically would be a
#: rule that could be fooled.
_EMIT_KEY_CONSTANT_NAMES = (
    "GEN_AI_PROVIDER_NAME",
    "GEN_AI_SYSTEM",
    "GEN_AI_OPERATION_NAME",
    "GEN_AI_REQUEST_MODEL",
    "GEN_AI_RESPONSE_MODEL",
    "GEN_AI_RESPONSE_ID",
    "GEN_AI_RESPONSE_FINISH_REASONS",
    "GEN_AI_USAGE_INPUT_TOKENS",
    "GEN_AI_USAGE_OUTPUT_TOKENS",
    "GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS",
    "GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS",
    "ERROR_TYPE",
    "DEPLOYMENT_ENVIRONMENT_NAME",
    "CLOUD_REGION",
)

#: The key deliberately absent from the set. It is not in the backend's
#: recognized inventory, it is derivable from the input and output counts, and it
#: is the key most exposed to a backend that sums rather than replaces — the same
#: arithmetic hazard D-02 cites for the cache spellings. Omitting it costs
#: nothing and removes a double-count surface. ``semconv.py`` records it as a
#: comment rather than a constant so that the one key the module must never emit
#: is not itself a spelling of that key living in the module.
_TOTAL_TOKENS_KEY = "gen_ai.usage.total_tokens"

#: MLflow writes its LiteLLM-derived cost estimate onto the span. Its own
#: translator happens to drop it, which is an accident of that implementation
#: rather than a guarantee this SDK can rely on.
_COST_SUBSTRING = "cost"

#: Everything MLflow puts on a span lives under this prefix, including the
#: serialized request and response.
_MLFLOW_NAMESPACE = "mlflow."

#: Supplied to the mapper on half the sweep (D-C6). Phase 4 sources them from
#: configuration; this module takes them as arguments.
_ENVIRONMENT = "prod"
_REGION = "us-east-1"

#: The captured span's timings, needed only for the one-off ``build_readable_span``
#: call in the sweep.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000

#: The planted strings. Distinctive enough that a substring match against an
#: emitted value cannot fire by coincidence, and shaped like the three things
#: that must never reach the wire: a prompt, a completion, and the text of an
#: exception raised inside customer code.
_PROMPT_CONTENT = "planted-prompt-text-6f2a91"
_COMPLETION_CONTENT = "planted-completion-text-b47d03"
_EXCEPTION_MARKER = "planted-exception-secret-1d9e"

#: The fourth forbidden marker, and the only one shaped like the reproduction
#: 02-VERIFICATION.md recorded rather than like a category: a URL carrying an
#: embedded key-shaped token. Synthetic — ``rev_sk_planted_4a2d`` is not a
#: credential and never was — but it is the exact shape CLAUDE.md requires be
#: redacted from anything leaving the process. It is planted in ``status`` on a
#: subject of its own, because ``status`` already carries
#: :data:`_COMPLETION_CONTENT` on the shared content span and one field cannot
#: hold two markers.
_CREDENTIAL_CONTENT = "https://user:rev_sk_planted_4a2d@api.internal.example.com/v1 failed: 401"

#: Class A. Markers that must reach **no** emitted value, planted in the three
#: Class A source fields ``map_span`` reads (``status``, ``stop_reason``,
#: ``choices[].finish_reason``) plus the two content paths it does not read
#: today. The two retained plants stay deliberately: they are the real
#: disclosure surface, and a future read added to either path is caught by the
#: control the day it lands.
_FORBIDDEN_CONTENT = (
    _PROMPT_CONTENT,
    _COMPLETION_CONTENT,
    _EXCEPTION_MARKER,
    _CREDENTIAL_CONTENT,
)

#: Class B. Markers the mapper is **expected** to forward, planted in the three
#: Class B source fields ``map_span`` reads: ``inputs["model"]``,
#: ``outputs["model"]`` and ``outputs["id"]``. SEM-03 requires the provider's own
#: model string and SEM-06 the provider's own response id, so an absence
#: assertion covering these keys could only ever be made green by deleting the
#: plant — which is the defect this run exists to close. The plant stays and the
#: assertion is scoped instead; the exception is asserted by name in
#: :func:`test_the_model_and_id_keys_forward_the_providers_own_string`.
#:
#: **Every one of these is deliberately shorter than the 64-character cap plan
#: 02-08 introduces** — the longest, :data:`_FORWARDED_REQUEST_MODEL`, is 39
#: code points. That is what makes the carve-out test pass for the reason it
#: claims: the plant's *placement* in a Class B field decides it, not
#: ``semconv._bounded`` happening to let it through.
_FORWARDED_REQUEST_MODEL = "gpt-4o-forwarded-request-model-5b1e7a3c"
_FORWARDED_RESPONSE_MODEL = "gpt-4o-forwarded-response-model-9d4c"
_FORWARDED_RESPONSE_ID = "chatcmpl-forwarded-response-id-2f86"

_FORWARDED_IDENTIFIERS = (
    _FORWARDED_REQUEST_MODEL,
    _FORWARDED_RESPONSE_MODEL,
    _FORWARDED_RESPONSE_ID,
)

#: A request carrying prompt text **and** the forwarded request-model marker,
#: shaped like what MLflow serializes into ``mlflow.spanInputs``. ``model`` is
#: the field ``map_span`` reads for ``gen_ai.request.model``; ``messages`` is a
#: path it does not read, kept so a future read there fails this file.
_INPUTS_WITH_CONTENT: Mapping[str, object] = {
    "model": _FORWARDED_REQUEST_MODEL,
    "messages": [{"role": "user", "content": _PROMPT_CONTENT}],
}

#: A response carrying a marker in **every** field ``map_span`` reads out of
#: ``mlflow.spanOutputs``, split by value class. ``id`` and ``model`` carry
#: Class B markers the mapper must forward; ``status``, ``stop_reason`` and
#: ``choices[0]["finish_reason"]`` carry the Class A marker it must not.
#:
#: Before plan 02-08 the plants were ``"chatcmpl-planted"``, ``"gpt-4o-2024-08-06"``
#: and ``"stop"`` — three benign literals in the fields the mapper reads, with
#: the markers confined to ``messages[].content`` and
#: ``choices[].message.content``, which it reads neither of. The absence
#: assertion below was therefore structurally incapable of failing (GAP-2,
#: WR-06). Moving the markers into the read fields is what gives it a boundary.
_OUTPUTS_WITH_CONTENT: Mapping[str, object] = {
    "id": _FORWARDED_RESPONSE_ID,
    "model": _FORWARDED_RESPONSE_MODEL,
    "status": _COMPLETION_CONTENT,
    "stop_reason": _COMPLETION_CONTENT,
    "choices": [
        {
            "finish_reason": _COMPLETION_CONTENT,
            "message": {"role": "assistant", "content": _COMPLETION_CONTENT},
        }
    ],
}

#: The credential reproduction, on its own subject. ``status`` is a Class A
#: source, so this belongs squarely in the forbidden set.
_OUTPUTS_WITH_CREDENTIAL: Mapping[str, object] = {"status": _CREDENTIAL_CONTENT}

#: The arguments every helper that has a *required* parameter needs. Kept
#: explicit and asserted complete: a helper that grows a required parameter must
#: fail here until someone decides what to pass it, rather than dropping out of
#: the sweep unnoticed.
_REQUIRED_ARGUMENTS: Mapping[str, Mapping[str, object]] = {
    "build_readable_span": {
        # The raw builder encodes nothing, so its MLflow-namespaced values are
        # JSON-encoded at the call site — the division of labour the fixture
        # module's docstring sets out. Content-carrying, so this leg of the
        # sweep is not a vacuous pass.
        "attributes": {
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
            "mlflow.llm.model": json.dumps("gpt-4o"),
            "mlflow.spanInputs": json.dumps(_INPUTS_WITH_CONTENT),
            "mlflow.spanOutputs": json.dumps(_OUTPUTS_WITH_CONTENT),
        },
        "start_time_ns": _START_NS,
        "end_time_ns": _END_NS,
    },
    "mlflow_typed_span": {"span_type": "CHAT_MODEL"},
    "error_span": {"marker": _EXCEPTION_MARKER},
}


def _exported_helpers() -> dict[str, Callable[..., ReadableSpan]]:
    """Every public span helper the shared fixture module defines.

    Derived rather than listed, so a helper added by a later plan joins the
    sweep without anyone remembering to add it here. Filtered on
    ``__module__`` so an imported name could never be mistaken for a helper.
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


def _content_spans() -> dict[str, ReadableSpan]:
    """Spans whose MLflow inputs and outputs carry the planted message content.

    Separate from the helper sweep because the control has to be built with
    known content in it; the helpers' own defaults carry none.
    """
    return {
        "content_span": span_fixtures.mlflow_chat_model_span(
            inputs=_INPUTS_WITH_CONTENT,
            outputs=_OUTPUTS_WITH_CONTENT,
        ),
        "planted_error_span": span_fixtures.error_span(marker=_EXCEPTION_MARKER),
        "credential_span": span_fixtures.mlflow_chat_model_span(
            outputs=_OUTPUTS_WITH_CREDENTIAL,
        ),
    }


def _all_spans() -> dict[str, ReadableSpan]:
    """Every span the guards below run over."""
    return {**_helper_spans(), **_content_spans()}


def _mapped_attributes(span: ReadableSpan) -> tuple[Mapping[str, AttributeValue], ...]:
    """The span mapped both ways: with the caller's dimensions, and without them.

    Both legs matter. ``deployment.environment.name`` and ``cloud.region`` are
    only ever emitted when supplied, so a sweep that never supplied them would
    leave two of the fourteen keys unreached by every guard in this file.
    """
    return (
        semconv.map_span(span).attributes,
        semconv.map_span(span, environment=_ENVIRONMENT, region=_REGION).attributes,
    )


def _swept_attributes() -> list[tuple[str, Mapping[str, AttributeValue]]]:
    """Every attribute mapping the sweep produces, labelled by its subject."""
    return [
        (name, attributes)
        for name, span in _all_spans().items()
        for attributes in _mapped_attributes(span)
    ]


def _swept_keys() -> set[str]:
    """The union of every key any subject emitted."""
    return {key for _, attributes in _swept_attributes() for key in attributes}


def _span_text(span: ReadableSpan) -> str:
    """Everything on a span a leak could plausibly be read out of, as one string.

    Attribute values, the status description, and every exception-event attribute
    value — the three places ``tests/fixtures/spans.py`` plants a marker,
    measured against the real disclosure surface rather than an imagined one.
    """
    parts = [str(value) for value in (span.attributes or {}).values()]
    parts.append(str(span.status.description))
    parts.extend(str(value) for event in span.events for value in (event.attributes or {}).values())
    return "\n".join(parts)


def _symmetric_difference(label: str, ours: set[str], theirs: set[str]) -> str:
    """A failure message naming what drifted, in which direction."""
    return (
        f"{label}. Present in the first and not the second: {sorted(ours - theirs)}. "
        f"Present in the second and not the first: {sorted(theirs - ours)}."
    )


# --- The closed set itself -------------------------------------------------


def test_the_closed_set_is_exactly_the_fourteen_expected_keys() -> None:
    """The literal comparison — the assertion a rename cannot agree with."""
    assert set(semconv.EMITTED_ATTRIBUTE_KEYS) == set(_EXPECTED_EMITTED_KEYS), (
        _symmetric_difference(
            "EMITTED_ATTRIBUTE_KEYS no longer matches this file's independent copy",
            set(semconv.EMITTED_ATTRIBUTE_KEYS),
            set(_EXPECTED_EMITTED_KEYS),
        )
    )


def test_every_emit_key_constant_is_a_member_of_the_closed_set() -> None:
    """Direction one: a key named by the module but missing from the set.

    That is a key ``map_span`` can write and the allowlist does not sanction —
    the drift that turns a closed set back into an open one.
    """
    named = {getattr(semconv, name) for name in _EMIT_KEY_CONSTANT_NAMES}
    assert named <= set(semconv.EMITTED_ATTRIBUTE_KEYS), sorted(
        named - set(semconv.EMITTED_ATTRIBUTE_KEYS)
    )


def test_every_member_of_the_closed_set_is_named_by_a_constant() -> None:
    """Direction two: a key in the set that no constant names.

    An unnamed key is one nothing can emit through a constant, so it is either
    dead or written as a bare literal somewhere — both worth failing over.
    """
    named = {getattr(semconv, name) for name in _EMIT_KEY_CONSTANT_NAMES}
    assert set(semconv.EMITTED_ATTRIBUTE_KEYS) <= named, sorted(
        set(semconv.EMITTED_ATTRIBUTE_KEYS) - named
    )


def test_no_other_module_constant_holds_a_key_outside_the_closed_set() -> None:
    """The drift the two directions above cannot see: a *new* key constant.

    Both directions run over a fixed list of fourteen names, so a fifteenth
    constant added later is invisible to them. This scans every public string
    constant in the module for an attribute-key shape — a dotted value — and
    requires it to be in the set. It is why ``gen_ai.usage.total_tokens`` is
    recorded in ``semconv.py`` as a comment and never as a constant.
    """
    dotted = {
        name: value
        for name, value in vars(semconv).items()
        if not name.startswith("_") and isinstance(value, str) and "." in value
    }
    stray = {
        name: value for name, value in dotted.items() if value not in semconv.EMITTED_ATTRIBUTE_KEYS
    }
    assert stray == {}, stray


def test_the_closed_set_is_a_frozenset() -> None:
    """A caller who could widen it in their own process would change the wire.

    The same reasoning ``attributes.py`` records for ``ATTRIBUTE_CAPS``: the
    extra values would then do nothing, with no error on either side.
    """
    assert isinstance(semconv.EMITTED_ATTRIBUTE_KEYS, frozenset)


# --- The sweep -------------------------------------------------------------


def test_the_sweep_reaches_every_helper_the_fixture_module_exports() -> None:
    """Non-vacuity, and the guard against a silently skipped helper.

    Every guard below is a statement about the union of the sweep. If the sweep
    were empty, or missing a helper, each of them would pass while proving
    nothing — the failure mode a scanner that detects nothing also produces.
    """
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


def test_the_sweep_emits_only_keys_from_the_closed_set() -> None:
    """D-04 itself: nothing reaches the wire that the allowlist does not sanction."""
    assert _swept_keys() <= set(semconv.EMITTED_ATTRIBUTE_KEYS), sorted(
        _swept_keys() - set(semconv.EMITTED_ATTRIBUTE_KEYS)
    )


def test_the_emitted_keys_are_a_subset_of_the_closed_set_by_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WR-03: a statement about the *function*, where the sweep is one about the fixtures.

    ``test_the_sweep_emits_only_keys_from_the_closed_set`` above asserts that the
    spans in the sweep emit no stray key. That is a claim about those spans. It
    cannot see a key emitted on a code path the fixtures do not reach — which is
    exactly the "leaks nobody thought of" case the module docstring says the
    closed allowlist structurally prevents. Until plan 02-08,
    ``EMITTED_ATTRIBUTE_KEYS`` was consulted by nothing at runtime: the allowlist
    was a naming convention plus this file.

    So this narrows the set to a single key and asserts the mapper's output
    narrows with it. ``map_span`` is pure and has no injection point, so there is
    no stray key to plant; substituting the set is the one way to observe the
    filter *firing* rather than to read the source and infer that it would.
    Equality rather than containment is what makes it non-vacuous in both
    directions: a mapper that ignored the set emits eleven keys here, and one that
    dropped everything emits none.
    """
    narrowed = frozenset({semconv.GEN_AI_PROVIDER_NAME})
    monkeypatch.setattr(semconv, "EMITTED_ATTRIBUTE_KEYS", narrowed)
    emitted = set(semconv.map_span(_all_spans()["content_span"]).attributes)
    assert emitted == set(narrowed), _symmetric_difference(
        "map_span did not filter its output against EMITTED_ATTRIBUTE_KEYS",
        emitted,
        set(narrowed),
    )


def test_no_emitted_key_names_a_cost() -> None:
    """T-02-04, and **not** redundant with the namespace guard below.

    MLflow's LiteLLM-derived cost estimate reaching Revenium's rating engine is
    a second, untrusted billing input, and Revenium is the authoritative rating
    source in this integration. This guard is the one that catches a cost field
    arriving under a key that does *not* carry the MLflow namespace — a value
    copied into a ``gen_ai.*`` or ``revenium.*`` spelling, say. Casing is folded
    because the constraint is about the concept, not about a spelling.
    """
    named = sorted(key for key in _swept_keys() if _COST_SUBSTRING in key.lower())
    assert named == [], named


def test_no_emitted_key_carries_the_mlflow_namespace() -> None:
    """The second, non-overlapping half, and **not** redundant with the cost guard.

    Everything MLflow puts on a span lives under ``mlflow.`` — including
    ``mlflow.spanInputs`` and ``mlflow.spanOutputs``, which hold the serialized
    request and response. This guard catches a future MLflow field named for
    something other than cost being forwarded wholesale; the cost guard cannot
    see it. Deleting either test as redundant re-opens one of the two holes.
    """
    named = sorted(key for key in _swept_keys() if key.startswith(_MLFLOW_NAMESPACE))
    assert named == [], named


def test_the_total_tokens_key_is_emitted_by_nothing() -> None:
    """Deliberately absent, and the fixtures record it so the absence is testable.

    ``tests/fixtures/spans.py`` carries ``total_tokens`` in its usage dicts
    because MLflow records it. It is not in the backend's recognized inventory,
    it is derivable from the input and output counts, and it is the key most
    exposed to a backend that sums rather than replaces.
    """
    assert _TOTAL_TOKENS_KEY not in _swept_keys()


def test_no_emitted_value_is_none() -> None:
    """T-02-08: the OTLP encoder does not reject a ``None``.

    It ships an ``AnyValue`` with no field set, and the backend receives a
    present key carrying an empty value — which reads as an answer rather than
    as an absence. Conditional insertion is the construction that prevents it;
    this is the assertion that it was used everywhere.
    """
    offenders = sorted(
        f"{subject}:{key}"
        for subject, attributes in _swept_attributes()
        for key, value in attributes.items()
        if value is None
    )
    assert offenders == [], offenders


# --- The content-leak control ----------------------------------------------


@pytest.mark.parametrize(
    ("content", "subject"),
    [
        (_PROMPT_CONTENT, "content_span"),
        (_COMPLETION_CONTENT, "content_span"),
        (_EXCEPTION_MARKER, "planted_error_span"),
        (_CREDENTIAL_CONTENT, "credential_span"),
        (_FORWARDED_REQUEST_MODEL, "content_span"),
        (_FORWARDED_RESPONSE_MODEL, "content_span"),
        (_FORWARDED_RESPONSE_ID, "content_span"),
    ],
)
def test_the_planted_content_is_present_on_the_span_it_was_planted_in(
    content: str, subject: str
) -> None:
    """The control subject is proven known-dirty before its absence means anything.

    Without this, the assertion below is satisfied just as well by a fixture that
    stopped carrying the content at all, or by a mapper that emitted nothing.

    Every marker in **both** value classes is covered, not only the forbidden
    ones. The Class B markers are the precondition of the carve-out test in the
    same way: an assertion that the mapper forwarded an identifier proves nothing
    if the identifier was never on the span.
    """
    assert content in _span_text(_all_spans()[subject])


def test_no_marker_belongs_to_both_value_classes() -> None:
    """The two sets must not overlap, in either direction, at substring level.

    Both sweeps below match by substring. If a forwarded identifier contained a
    forbidden marker, the Class A control would red on a Class B key and the
    failure would name the wrong defect; if a forbidden marker contained a
    forwarded one, the carve-out would go green on a leak. Neither is possible
    with markers this file chose, and this is the assertion that keeps it that
    way when someone edits one of them.
    """
    overlaps = sorted(
        f"{forbidden!r} <-> {forwarded!r}"
        for forbidden in _FORBIDDEN_CONTENT
        for forwarded in _FORWARDED_IDENTIFIERS
        if forbidden in forwarded or forwarded in forbidden
    )
    assert overlaps == [], overlaps


def test_no_emitted_value_carries_any_forbidden_content() -> None:
    """The first prohibition, made mechanical (T-02-03), over Class A only.

    Prompt text, completion text, system instructions, tool arguments and tool
    results must never reach the wire, and no free text from a response body may
    reach a Class A key. ``map_span`` reads the mappings that hold all of it, so
    this is one field access away at every mapping — no convenience, no debugging
    aid and no future field may create a path for it.

    **The perimeter, written down rather than left to whatever the sweep
    happened to cover.** This sweeps :data:`_FORBIDDEN_CONTENT` and not
    :data:`_FORWARDED_IDENTIFIERS`, because 02-VERIFICATION.md answers the
    question directly:

        The model and id keys copying provider-controlled strings is inherent to
        SEM-03 and defensible. The sharp edge is ``FINISH_REASON_SOURCES``'
        ``("status", None)`` row.

    An absence assertion covering ``gen_ai.request.model``,
    ``gen_ai.response.model`` or ``gen_ai.response.id`` could only ever be made
    green by deleting the plant from those fields — which is precisely how the
    predecessor of this test shipped green while a credential-bearing URL reached
    ``gen_ai.response.finish_reasons`` verbatim. The keys this test stops
    covering are picked up by
    :func:`test_the_model_and_id_keys_forward_the_providers_own_string`, which
    states the exception rather than leaving it implicit.

    **Enforcement is uneven, and the unevenness is stated rather than averaged
    over.** On the Class A keys the prohibition is mechanized: a planted marker
    in ``outputs["status"]``, ``outputs["stop_reason"]`` or
    ``choices[].finish_reason`` reds this test. On the three Class B source
    fields it is enforced by length alone, so content arriving under the cap in
    ``inputs["model"]``, ``outputs["model"]`` or ``outputs["id"]`` would violate
    the clause with nothing red. That is the accepted residual **T-02-08-07**,
    sized deliberately at plan 02-08's checkpoint.
    """
    offenders = sorted(
        f"{subject}:{key}={value!r}"
        for subject, attributes in _swept_attributes()
        for key, value in attributes.items()
        for content in _FORBIDDEN_CONTENT
        if content in _rendered(value)
    )
    assert offenders == [], offenders


def test_the_model_and_id_keys_forward_the_providers_own_string() -> None:
    """The carve-out, asserted rather than assumed.

    An exception nobody wrote down is indistinguishable from a leak nobody
    noticed. SEM-03 requires ``gen_ai.request.model`` and ``gen_ai.response.model``
    to carry the provider's own model string — an allowlist there would drop every
    model this SDK has not heard of, which is every new model — and SEM-06
    requires ``gen_ai.response.id`` to carry the provider's own opaque id, which
    has no vocabulary by definition. So these three keys forward what was planted,
    and that is the requirement, not a gap.

    **This test passes both before and after the value constraints land, and that
    is intended — do not "fix" it.** It is a characterization test pinning a
    deliberate exception, not a defect control. If it ever goes red, a constraint
    written for Class A has been applied to Class B and the SDK has started
    dropping legitimate model names and response ids silently.

    Every planted identifier is under the character cap (the longest is 39 code
    points against a cap of 64), so what this test measures is the perimeter, not
    ``semconv._bounded``.
    """
    attributes = semconv.map_span(_all_spans()["content_span"]).attributes
    forwarded = {
        "gen_ai.request.model": _FORWARDED_REQUEST_MODEL,
        "gen_ai.response.model": _FORWARDED_RESPONSE_MODEL,
        "gen_ai.response.id": _FORWARDED_RESPONSE_ID,
    }
    missing = sorted(
        f"{key}={attributes.get(key)!r} does not carry {marker!r}"
        for key, marker in forwarded.items()
        if marker not in _rendered(attributes.get(key))
    )
    assert missing == [], missing


def _rendered(value: Any) -> str:
    """One attribute value as text, so a tuple's elements are searched too.

    ``gen_ai.response.finish_reasons`` is a tuple of strings; a substring test
    against the tuple object itself would still work through ``repr``, but
    saying so explicitly keeps the guard from depending on a repr detail.
    """
    if isinstance(value, (tuple, list)):
        return "\n".join(str(item) for item in value)
    return str(value)
