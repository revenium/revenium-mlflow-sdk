"""One MLflow ``CHAT_MODEL`` span, end to end, through every layer this phase builds.

This is the tracer for phase 2: the thin vertical slice that proves the whole
pipeline before any of it is expanded. One hand-built ``ReadableSpan`` shaped
exactly like the span captured off a real MLflow tracer provider goes in — every
attribute a JSON string, ``SpanKind.INTERNAL``, integer-nanosecond timings,
``mlflow.chat.tokenUsage`` carrying cache tokens — and a ``MappedSpan`` carrying
``gen_ai.*`` attributes, ``SpanKind.CLIENT``, hex ids and a derived duration
comes out. Four layers are exercised at once: the fixture builder, the shared
decoder, the eligibility predicate and the semconv mapper.

The architectural risk this file retires is not any single mapping rule. It is
whether a dict-in/dict-out design over a bare ``ReadableSpan`` can carry
everything the phase needs **without importing MLflow at runtime**. If that were
false, plans 02-02 through 02-05 would each be building on a foundation that
cannot hold, and the failure would only surface at the end. Answering it here
costs one commit.

One assertion per test, and each docstring names what breaks in production if
that assertion fails rather than restating the assert.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from revenium_mlflow.tracing.eligibility import is_billable_llm_span
from revenium_mlflow.tracing.semconv import MappedSpan, map_span
from tests.fixtures.spans import mlflow_chat_model_span

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Lowercase hex only. An uppercase or ``0x``-prefixed id is not what the OTLP
#: wire carries, and the backend compares these as strings.
_LOWER_HEX = re.compile(r"\A[0-9a-f]+\Z")


@pytest.fixture
def mapped() -> MappedSpan:
    """The captured span, mapped once, shared by the assertions below."""
    return map_span(mlflow_chat_model_span())


def test_the_fixture_carries_mlflows_json_encoding() -> None:
    """A fixture storing a bare value would make every test below vacuous.

    MLflow serializes every span attribute to JSON, so the raw wire value is
    ``'"CHAT_MODEL"'`` — six characters longer than it looks and identical to the
    bare form in a debugger that strips one layer of quoting. A predicate that
    compared the raw value to ``CHAT_MODEL`` would reject every real span while
    passing every test built on an un-encoded fixture.
    """
    assert mlflow_chat_model_span().attributes["mlflow.spanType"] == '"CHAT_MODEL"'


def test_the_fixture_span_kind_is_internal() -> None:
    """SEM-12 has nothing to prove unless the input kind really is ``INTERNAL``.

    Measured on a real captured MLflow span. If the fixture were built as
    ``CLIENT``, the mapper could pass the kind straight through and the
    assertion that it emits ``CLIENT`` would prove nothing.
    """
    assert mlflow_chat_model_span().kind.name == "INTERNAL"


def test_the_fixture_timings_are_integer_nanoseconds() -> None:
    """Float timings would silently lose nanosecond resolution on the wire."""
    span = mlflow_chat_model_span()
    assert type(span.start_time) is int and type(span.end_time) is int


def test_the_captured_chat_model_span_is_billable() -> None:
    """If the predicate rejects the shape MLflow really emits, export goes to zero.

    Silently: there is no error on either side, only an invoice missing every
    model call the customer made.
    """
    assert is_billable_llm_span(mlflow_chat_model_span()) is True


def test_the_mapped_span_carries_the_chat_operation(mapped: MappedSpan) -> None:
    """Without an operation the backend cannot tell a completion from an embedding."""
    assert mapped.attributes["gen_ai.operation.name"] == "chat"


def test_the_mapped_span_carries_the_request_model(mapped: MappedSpan) -> None:
    """The model is what the rate is looked up by; a missing one rates as unknown."""
    assert mapped.attributes["gen_ai.request.model"] == "gpt-4o"


def test_the_mapped_span_carries_the_input_token_count(mapped: MappedSpan) -> None:
    """Input tokens are the larger half of most invoices."""
    assert mapped.attributes["gen_ai.usage.input_tokens"] == 1000


def test_the_mapped_span_carries_the_output_token_count(mapped: MappedSpan) -> None:
    """Output tokens rate at a different, usually higher, unit price."""
    assert mapped.attributes["gen_ai.usage.output_tokens"] == 50


def test_the_mapped_span_carries_the_cache_read_token_count(mapped: MappedSpan) -> None:
    """This is the number MLflow's own OTLP translator discards.

    Its absence is the overbill this SDK exists to fix: a prompt-caching
    customer's cached tokens rate at the full input price, and nothing anywhere
    reports an error.
    """
    assert mapped.attributes["gen_ai.usage.cache_read_input_tokens"] == 900


def test_all_four_token_counts_are_emitted_when_the_span_carries_them() -> None:
    """Both cache spellings survive, not only the one the captured span happened to have.

    The captured wire shape in ``mlflow_chat_model_span`` carries no
    ``cache_creation_input_tokens`` — the real span measured in 02-RESEARCH.md did
    not — so the assertions above exercise three counts. This is the fourth. It is
    a separate test rather than an addition to that fixture on purpose: editing
    the captured shape to carry a field the capture did not would make the
    fixture's claim to reproduce the wire false, and every later plan reads it as
    the wire.
    """
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 2,
    }
    attributes = map_span(mlflow_chat_model_span(usage=usage)).attributes
    assert {k: v for k, v in attributes.items() if k.startswith("gen_ai.usage.")} == {
        "gen_ai.usage.input_tokens": 100,
        "gen_ai.usage.output_tokens": 20,
        "gen_ai.usage.cache_read_input_tokens": 3,
        "gen_ai.usage.cache_creation_input_tokens": 2,
    }


def test_the_provider_is_non_empty_under_both_key_spellings(mapped: MappedSpan) -> None:
    """An absent provider drops the payload to the backend's generic fallback.

    Both spellings are emitted (D-16) because the deployed backend build is not
    yet verified, and duplicate *string* keys carry none of the summing risk
    that restricts the cache-token keys to one spelling.
    """
    provider = mapped.attributes["gen_ai.provider.name"]
    assert provider and mapped.attributes["gen_ai.system"] == provider


def test_every_emitted_token_value_is_exactly_int(mapped: MappedSpan) -> None:
    """``isinstance`` is not enough here, which is why the check is on ``type``.

    ``isinstance(True, int)`` is true in Python and the OTLP encoder ships such a
    value as ``bool_value: true``, so a boolean token count would violate SEM-04
    behind a green ``isinstance`` assertion.
    """
    tokens = [v for k, v in mapped.attributes.items() if k.startswith("gen_ai.usage.")]
    assert tokens and all(type(value) is int for value in tokens)


def test_a_boolean_in_the_usage_dict_never_reaches_a_token_count() -> None:
    """A ``True`` where a count belongs must be dropped, not shipped as a boolean.

    The encoder does not reject it and the backend has no way to tell the
    difference from a count, so the guard has to be here.
    """
    usage = {"input_tokens": True, "output_tokens": 50, "cache_read_input_tokens": 900}
    attributes = map_span(mlflow_chat_model_span(usage=usage)).attributes
    assert not any(isinstance(value, bool) for value in attributes.values())


def test_the_mapped_span_kind_is_client(mapped: MappedSpan) -> None:
    """SEM-12. The GenAI semantic conventions require ``CLIENT`` for inference spans.

    The input is ``INTERNAL`` — the requirement is about what the SDK emits, not
    about what MLflow produced.
    """
    assert mapped.kind.name == "CLIENT"


def test_the_trace_id_is_thirty_two_lowercase_hex_characters(mapped: MappedSpan) -> None:
    """The backend correlates on this string; a wrong width breaks every join."""
    assert len(mapped.trace_id) == 32 and _LOWER_HEX.match(mapped.trace_id)


def test_the_span_id_is_sixteen_lowercase_hex_characters(mapped: MappedSpan) -> None:
    """The backend uses this as the transaction id, and mints a random one if it is blank."""
    assert len(mapped.span_id) == 16 and _LOWER_HEX.match(mapped.span_id)


def test_a_root_span_reports_no_parent_span_id(mapped: MappedSpan) -> None:
    """The backend treats a blank parent as a root; an invented one forges a tree."""
    assert mapped.parent_span_id is None


def test_duration_is_derived_from_the_two_timestamps(mapped: MappedSpan) -> None:
    """Read off the span, never off ``mlflow.spanStartTimeNs``, which real spans lack."""
    assert mapped.duration_ns == mapped.end_time_ns - mapped.start_time_ns > 0


def test_total_tokens_is_never_emitted(mapped: MappedSpan) -> None:
    """It is derived, absent from the backend's inventory, and a double-count surface.

    A backend that sums rather than replaces would bill the same tokens twice.
    """
    assert "gen_ai.usage.total_tokens" not in mapped.attributes


def test_no_emitted_attribute_value_is_none(mapped: MappedSpan) -> None:
    """The OTLP encoder does not reject ``None`` — it ships an empty ``AnyValue``.

    The backend then sees a present key with no value, which is worse than an
    absent key because it looks like an answer.
    """
    assert None not in mapped.attributes.values()


def test_no_emitted_key_is_mlflow_namespaced(mapped: MappedSpan) -> None:
    """The fixture carries ``mlflow.traceRequestId`` and ``mlflow.spanOutputs``.

    Neither may be forwarded: ``mlflow.spanOutputs`` holds the serialized
    provider response, completion text included, and content capture is out of
    scope for this SDK.
    """
    assert [key for key in mapped.attributes if key.startswith("mlflow.")] == []


def test_importing_the_new_modules_loads_no_mlflow() -> None:
    """D-05 and PKG-09, checked in a clean interpreter rather than in this one.

    This session imports MLflow elsewhere, so an in-process ``sys.modules`` check
    would report test ordering. ``mlflow.entities.span`` pulls roughly 495
    submodules in about 0.9 s, and this predicate runs inside a ``SpanProcessor``
    callback for every span in the process.
    """
    probe = (
        "import sys, revenium_mlflow.tracing._spanattrs, "
        "revenium_mlflow.tracing.eligibility, revenium_mlflow.tracing.semconv; "
        "print('mlflow' in sys.modules)"
    )
    # Fixed argv, no shell, no interpolated input.
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    assert result.stdout.strip() == "False", result.stderr
