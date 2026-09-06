"""The decode contract, proven against the encoding a real MLflow span carries.

MLflow serializes every span attribute to a JSON string before it reaches
OpenTelemetry, so ``mlflow.spanType`` arrives on the wire as ``'"CHAT_MODEL"'``
— twelve characters, not ten. Comparing the raw value to ``CHAT_MODEL`` fails for
every real span, every time, and the two forms print identically in a debugger
that strips one layer of quoting. That is the failure this file exists to make
impossible, and it is not hypothetical: it is the single most likely way this
phase ships a predicate that rejects one hundred percent of production traffic
while every test stays green.

Two further failure modes are pinned here because nothing else in the phase pins
them:

*The empty-string case.* MLflow's reader guards on truthiness — ``if
serialized_value :=`` — so an empty-string attribute decodes to ``None`` rather
than to ``''``. A decoder that "simplified" that to ``is not None`` diverges
silently, and the divergence only surfaces on a span that carries an empty
attribute, which is exactly when nobody is looking.

*The boolean-token case.* ``isinstance(True, int)`` is ``True`` in Python and the
OTLP protobuf encoder ships such a value as ``bool_value: true``. A token count
arriving as a boolean would violate SEM-04 behind a green ``isinstance``
assertion, and the backend cannot tell it from a real count.

**Every expectation below is spelled as a literal.** None is imported from
``_spanattrs.py``. That is the rule ``tests/unit/test_attributes.py`` records as
load-bearing: a test that reads its expectations out of the module under test is
a view of that module, and it agrees with every future edit — including the ones
that are wrong.
"""

import pytest

from revenium_mlflow.tracing._spanattrs import (
    decode,
    decode_mapping,
    decode_str,
    is_positive_int,
)
from tests.fixtures.spans import mlflow_chat_model_span

pytestmark = pytest.mark.unit


def test_a_json_encoded_string_decodes_to_the_bare_value() -> None:
    """Without this, the span-type allowlist rejects every real MLflow span.

    Silently: export falls to zero and no error appears on either side.
    """
    assert decode({"mlflow.spanType": '"CHAT_MODEL"'}, "mlflow.spanType") == "CHAT_MODEL"


def test_the_encoded_form_is_two_characters_longer_than_the_bare_form() -> None:
    """The quotes are the whole trap, stated as arithmetic so it cannot be argued with."""
    assert len('"CHAT_MODEL"') == len("CHAT_MODEL") + 2


def test_a_json_encoded_dict_decodes_to_a_dict() -> None:
    """The token-usage dict is the only source of cache-token counts (D-01)."""
    raw = '{"input_tokens": 1000, "output_tokens": 50, "cache_read_input_tokens": 900}'
    assert decode({"mlflow.chat.tokenUsage": raw}, "mlflow.chat.tokenUsage") == {
        "input_tokens": 1000,
        "output_tokens": 50,
        "cache_read_input_tokens": 900,
    }


def test_the_decoded_usage_values_are_integers() -> None:
    """Counts that arrived as strings would fail the token gate and drop the span."""
    raw = '{"input_tokens": 1000, "output_tokens": 50}'
    decoded = decode_mapping({"mlflow.chat.tokenUsage": raw}, "mlflow.chat.tokenUsage")
    assert decoded is not None and all(type(v) is int for v in decoded.values())


def test_a_malformed_value_decodes_to_the_raw_string_unchanged() -> None:
    """MLflow's lenient fallback, mirrored (D-07).

    The strict reader MLflow also ships returns ``None`` here. Choosing the
    lenient one is what lets a bridged non-MLflow instrumentor, which writes a
    bare unquoted value, still be understood.
    """
    assert decode({"k": "not json"}, "k") == "not json"


def test_a_malformed_value_raises_nothing() -> None:
    """One malformed attribute must not fail the whole export batch (T-02-05)."""
    assert decode({"k": "{unclosed"}, "k") == "{unclosed"


def test_an_empty_string_value_decodes_to_none() -> None:
    """The consequence of mirroring MLflow's truthiness walrus rather than ``is not None``.

    A decoder that returned ``''`` here would report a span type of empty string,
    which is not a member of any allowlist — so the span is rejected either way,
    but for a reason no log would explain.
    """
    assert decode({"k": ""}, "k") is None


def test_an_absent_key_decodes_to_none() -> None:
    """The ordinary case for every attribute a given integration does not set."""
    assert decode({"present": '"x"'}, "absent") is None


def test_a_bare_unquoted_value_decodes_to_itself() -> None:
    """Path B has to work for spans MLflow did not produce.

    A bridged OpenTelemetry instrumentor writes ``CHAT_MODEL`` with no quotes,
    because it never went through MLflow's serializer.
    """
    assert decode({"mlflow.spanType": "CHAT_MODEL"}, "mlflow.spanType") == "CHAT_MODEL"


def test_decode_str_reports_a_non_string_as_absent() -> None:
    """A stringified dict would compare unequal to every allowlist member anyway.

    It would do so while looking like a real value in a log, which is worse than
    reporting nothing.
    """
    assert decode_str({"k": '{"a": 1}'}, "k") is None


def test_decode_mapping_reports_a_non_mapping_as_absent() -> None:
    """A usage attribute holding a list must not be indexed as if it were a dict."""
    assert decode_mapping({"mlflow.chat.tokenUsage": "[1, 2]"}, "mlflow.chat.tokenUsage") is None


def test_is_positive_int_rejects_true() -> None:
    """SEM-04, and the sharpest edge in this file.

    ``isinstance(True, int)`` is ``True`` in Python and the OTLP encoder emits
    ``bool_value: true`` for it, so a boolean reaching a billed token count would
    pass an ``isinstance`` guard and violate the requirement with a green test.
    """
    assert is_positive_int(True) is False


def test_is_positive_int_rejects_zero() -> None:
    """D-11 requires a positive count, not a present field.

    A usage dict reporting zero everywhere would otherwise rate as a zero-cost
    completion instead of being dropped as showing no work done.
    """
    assert is_positive_int(0) is False


def test_is_positive_int_rejects_a_negative_count() -> None:
    """A negative token count is not evidence of anything but a broken integration."""
    assert is_positive_int(-1) is False


def test_is_positive_int_rejects_a_numeric_string() -> None:
    """``"3"`` is what an attribute looks like when it was never decoded."""
    assert is_positive_int("3") is False


def test_is_positive_int_rejects_a_float() -> None:
    """Token counts are whole; a float here means something upstream computed it."""
    assert is_positive_int(3.0) is False


def test_is_positive_int_accepts_a_positive_int() -> None:
    """The gate has to admit real traffic, or the SDK bills nothing at all."""
    assert is_positive_int(3) is True


def test_the_fixture_itself_carries_the_embedded_quotes() -> None:
    """The fixture proves the encoding rather than the test taking it on trust.

    Without this, a fixture that accidentally stored a bare value would make
    every downstream test in the phase pass while the real wire shape went
    completely unexercised. Asserted on length and on the first and last
    characters, because the raw form prints identically to the bare form in a
    debugger that strips one layer of quoting.
    """
    raw = mlflow_chat_model_span().attributes["mlflow.spanType"]
    assert len(raw) == 12 and raw[0] == '"' and raw[-1] == '"'


def test_the_fixture_value_decodes_through_the_shared_decoder() -> None:
    """The two halves joined: MLflow's encoding in, the allowlist's spelling out."""
    span = mlflow_chat_model_span()
    assert decode_str(span.attributes or {}, "mlflow.spanType") == "CHAT_MODEL"
