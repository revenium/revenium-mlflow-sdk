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

_CONTENT_STRINGS = (_PROMPT_CONTENT, _COMPLETION_CONTENT, _EXCEPTION_MARKER)

#: A request carrying prompt text, shaped like what MLflow serializes into
#: ``mlflow.spanInputs``.
_INPUTS_WITH_CONTENT: Mapping[str, object] = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": _PROMPT_CONTENT}],
}

#: A response carrying completion text, shaped like what MLflow serializes into
#: ``mlflow.spanOutputs``. The finish reason and the response id are here on
#: purpose: they are emitted, so the absence assertion below is running against
#: an output that really did read this mapping rather than one that ignored it.
_OUTPUTS_WITH_CONTENT: Mapping[str, object] = {
    "id": "chatcmpl-planted",
    "model": "gpt-4o-2024-08-06",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": _COMPLETION_CONTENT},
        }
    ],
}

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
    ],
)
def test_the_planted_content_is_present_on_the_span_it_was_planted_in(
    content: str, subject: str
) -> None:
    """The control subject is proven known-dirty before its absence means anything.

    Without this, the assertion below is satisfied just as well by a fixture that
    stopped carrying the content at all, or by a mapper that emitted nothing.
    """
    assert content in _span_text(_all_spans()[subject])


def test_no_emitted_value_carries_any_planted_content() -> None:
    """The first prohibition, made mechanical (T-02-03).

    Prompt text, completion text, system instructions, tool arguments and tool
    results must never reach the wire. ``map_span`` reads the mappings that hold
    all of it, so this is one field access away at every mapping — no
    convenience, no debugging aid and no future field may create a path for it.
    The closed allowlist is the structural control; this is the measurement.
    """
    offenders = sorted(
        f"{subject}:{key}={value!r}"
        for subject, attributes in _swept_attributes()
        for key, value in attributes.items()
        for content in _CONTENT_STRINGS
        if content in _rendered(value)
    )
    assert offenders == [], offenders


def _rendered(value: Any) -> str:
    """One attribute value as text, so a tuple's elements are searched too.

    ``gen_ai.response.finish_reasons`` is a tuple of strings; a substring test
    against the tuple object itself would still work through ``repr``, but
    saying so explicitly keeps the guard from depending on a repr detail.
    """
    if isinstance(value, (tuple, list)):
        return "\n".join(str(item) for item in value)
    return str(value)
