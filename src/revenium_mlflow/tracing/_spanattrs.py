"""The one reader of MLflow span attributes, and the one spelling of each key.

**Why this module exists at all (D-C1).** ``eligibility.py`` decides whether a
span is billed; ``semconv.py`` decides what it is billed *as*. Both read the same
attributes off the same span. If their decoders were not byte-identical, a span
could be admitted under one reading and mapped under a different one — admitted,
then mapped wrong, which is worse than either failure alone and produces no error
anywhere. One decoder, imported by both, makes that disagreement impossible
rather than unlikely.

**The decode contract (D-07).** MLflow serializes *every* span attribute to a
JSON string before it reaches OpenTelemetry
(``mlflow/entities/span.py:1509`` at 3.16.0), so ``mlflow.spanType`` arrives on
the wire as ``'"CHAT_MODEL"'`` — two characters longer than it looks.
:func:`decode` mirrors MLflow's own reader, ``_SpanAttributesRegistry.get``, body
for body: a truthiness-guarded walrus, ``json.loads`` inside ``try``, and the raw
serialized value returned on any exception. Cited with the version because the
*body* is identical at 3.15.0 and 3.16.0 while the line numbers move:
``mlflow/entities/span.py:1493-1500`` at 3.16.0, ``:1446-1453`` at 3.15.0.

**MLflow has a second reader with different failure semantics, and the divergence
is deliberate.** ``mlflow/tracing/utils/__init__.py:460-467`` returns ``None`` on
a decode failure instead of falling back to the raw value. D-07 chose the lenient
one on purpose: a bridged non-MLflow instrumentor writes ``'CHAT_MODEL'`` bare,
and the strict reader would discard it. A reader who does not know the two
disagree will see them disagree on a malformed value and file it as a bug, so it
is recorded here.

**The truthiness guard is MLflow's, not a simplification.** ``if serialized_value
:=`` means an **empty-string** attribute decodes to ``None`` rather than to
``''``. Diverging there is invisible until it matters, so it is mirrored exactly.

Nothing here imports MLflow (D-05). The keys are plain strings in MLflow too, and
``mlflow.entities.span`` pulls roughly 495 submodules in about 0.9 seconds —
a cost this package will not pay inside a ``SpanProcessor`` callback that runs
for every span in the process.

Imported under private aliases so this module's public surface is exactly the
names in ``__all__``, which is asserted mechanically.
"""

import json as _json
from collections.abc import Mapping as _Mapping
from typing import Final as _Final

__all__ = [
    "MLFLOW_CHAT_USAGE",
    "MLFLOW_LLM_MODEL",
    "MLFLOW_LLM_PROVIDER",
    "MLFLOW_MESSAGE_FORMAT",
    "MLFLOW_SPAN_INPUTS",
    "MLFLOW_SPAN_OUTPUTS",
    "MLFLOW_SPAN_TYPE",
    "decode",
    "decode_int",
    "decode_mapping",
    "decode_str",
    "is_positive_int",
]

# --- MLflow attribute keys, each spelled exactly once in this codebase --------
#
# Read off ``mlflow.tracing.constant.SpanAttributeKey`` and transcribed rather
# than imported, for the D-05 reason above. Every value below was verified
# against the installed 3.16.0 constant of the same name.

#: The MLflow span type, JSON-encoded. Decodes to one of MLflow's fifteen
#: span-type strings, or to whatever a bridged instrumentor wrote.
MLFLOW_SPAN_TYPE: _Final[str] = "mlflow.spanType"

#: The normalized token-usage dict — **``tokenUsage``, not ``usage``**. The
#: roadmap flag and PITFALLS.md both write ``mlflow.chat.usage``, which is not an
#: attribute MLflow ever sets. Reading the wrong name looks exactly like a span
#: with no token evidence, so every span would be rejected and export would fall
#: to zero with no error on either side.
MLFLOW_CHAT_USAGE: _Final[str] = "mlflow.chat.tokenUsage"

#: The model name. Its *provenance* differs by integration — the response model
#: on the OpenAI path, the request model on Anthropic's — which is why SEM-03
#: forbids copying it blindly into ``gen_ai.request.model``.
MLFLOW_LLM_MODEL: _Final[str] = "mlflow.llm.model"

#: The provider, when MLflow asserted one. Thirteen or more integrations set it;
#: the OpenAI path never does, which is the whole reason provider inference needs
#: steps beyond reading this key.
MLFLOW_LLM_PROVIDER: _Final[str] = "mlflow.llm.provider"

#: Which integration produced the span. Declared by MLflow as the flavour marker
#: downstream consumers parse the message format with, which is what makes it a
#: structural signal about the emitting integration rather than a hint.
MLFLOW_MESSAGE_FORMAT: _Final[str] = "mlflow.message.format"

#: The serialized request kwargs. Read for the request model only.
MLFLOW_SPAN_INPUTS: _Final[str] = "mlflow.spanInputs"

#: The serialized provider response — **completion text included**. Read for the
#: response model, response id and finish reasons only. Nothing from it is ever
#: forwarded wholesale: prompt and completion content capture is out of scope for
#: this SDK, and the emit allowlist in ``semconv.py`` is what enforces that.
MLFLOW_SPAN_OUTPUTS: _Final[str] = "mlflow.spanOutputs"


def decode(attributes: _Mapping[str, object], key: str, /) -> object:
    """Read one MLflow attribute, exactly as MLflow itself would.

    Args:
        attributes: A span's raw attribute mapping.
        key: One of the module constants above.

    Returns:
        The JSON-decoded value; the raw serialized value when it is not valid
        JSON; or ``None`` when the key is absent or its value is falsy.

    This never raises. A malformed attribute on one span must not fail the whole
    export batch, so the ``except`` is as broad as MLflow's own and for the same
    reason (T-02-05). The return type is ``object`` rather than ``Any``
    deliberately: ``mypy --strict`` runs over this package, and ``Any`` leaking
    out of the decoder would defeat the gate for every caller downstream.
    """
    if serialized_value := attributes.get(key):
        if not isinstance(serialized_value, str | bytes | bytearray):
            # An attribute MLflow did not serialize — a bridged instrumentor set
            # a real int or bool. There is nothing to decode, and json.loads
            # would reject it. Hand it back unchanged.
            return serialized_value
        try:
            decoded: object = _json.loads(serialized_value)
        except Exception:
            # MLflow's comment, and its behaviour: a string value set directly on
            # the OTel span is returned as is. This is the lenient half of the
            # divergence recorded in the module docstring.
            return serialized_value
        return decoded
    return None


def decode_str(attributes: _Mapping[str, object], key: str, /) -> str | None:
    """:func:`decode`, narrowed to a string.

    Anything that decodes to a non-string — a dict, a number, a bridged
    instrumentor's list — is reported as absent rather than stringified. A
    stringified dict would compare unequal to every allowlist member anyway, but
    it would do so while looking like a real value in a log.
    """
    decoded = decode(attributes, key)
    return decoded if isinstance(decoded, str) else None


def decode_int(attributes: _Mapping[str, object], key: str, /) -> int | None:
    """:func:`decode`, narrowed to a non-``bool`` integer.

    ``bool`` is excluded **before** ``int`` is accepted, and the order is the
    whole point: ``isinstance(True, int)`` is ``True`` in Python and the OTLP
    protobuf encoder ships such a value as ``bool_value: true``. A boolean
    reaching a billed token count would violate SEM-04 behind a green
    ``isinstance`` assertion, and the backend has no way to tell it from a real
    count (T-02-07-04).

    A negative value is returned rather than dropped. This helper reports what
    was recorded; what to do about a count nobody could have measured is a policy
    its callers hold, and it lands in plan 02-08 in one place rather than in
    every reader.

    **The decision this function exists to carry out (plan 02-07,
    ``checkpoint:decision``, ``gate="blocking-human"``, answered
    ``decode-everywhere``).** All three remaining raw ``gen_ai.*`` reads — the
    token-evidence gate in ``eligibility._has_token_evidence``, the operation
    read in ``semconv.operation_for_span``, and the flat token fallback in
    ``semconv.map_span`` — now go through this module. Two of the three are on
    the **gate**, so this widens what is admitted into billing. That was accepted
    deliberately, on the record, before anything shipped, and these are the five
    span shapes whose verdict moved:

    1. ``gen_ai.operation.name`` JSON-encoded as a billable operation
       (``'"chat"'``) with token evidence: ``WRONG_TYPE`` becomes ``ADMITTED``.
    2. ``gen_ai.operation.name = ""`` on a span whose ``mlflow.spanType`` is
       billable: ``WRONG_TYPE`` becomes ``ADMITTED``. An empty declared operation
       stops being a rejection trigger — :func:`decode`'s truthiness guard
       reports it absent — and the span falls through to its MLflow span type.
    3. ``gen_ai.operation.name`` holding valid JSON that is not a JSON string
       (``"123"``, ``"true"``, ``"[1]"``) on a span whose ``mlflow.spanType`` is
       billable: ``WRONG_TYPE`` becomes ``ADMITTED``, by the same fall-through.
    4. ``gen_ai.usage.<count>`` JSON-encoded as a number (``"10"``):
       ``NO_TOKEN_EVIDENCE`` becomes ``ADMITTED``.
    5. ``gen_ai.operation.name`` JSON-encoded as a billable operation with **no**
       token evidence: ``WRONG_TYPE`` becomes ``NO_TOKEN_EVIDENCE``. The span
       stays rejected; only its reason code moves, and D-10 exists because that
       code is the one number a mis-tuned gate is visible in.

    Every one of those five is pinned by name in
    ``tests/unit/test_operation_precedence.py``'s ``_VERDICT_CHANGES``, and the
    four near-neighbour shapes that must **not** move are pinned in
    ``_VERDICT_UNCHANGED``. A sixth shape changing verdict reds that test rather
    than moving silently.
    """
    decoded = decode(attributes, key)
    if isinstance(decoded, bool) or not isinstance(decoded, int):
        return None
    return decoded


def decode_mapping(attributes: _Mapping[str, object], key: str, /) -> _Mapping[str, object] | None:
    """:func:`decode`, narrowed to a mapping, copied into a plain ``dict``.

    Copied rather than returned by reference so a caller cannot mutate a value
    another caller is about to read — the token-usage dict is read by both the
    eligibility predicate and the mapper, and they must see the same thing.
    """
    decoded = decode(attributes, key)
    if not isinstance(decoded, dict):
        return None
    narrowed: dict[str, object] = {str(name): value for name, value in decoded.items()}
    return narrowed


def is_positive_int(value: object, /) -> bool:
    """Whether ``value`` is a genuine positive integer count.

    ``bool`` is excluded **before** ``int`` is accepted, and the order is the
    whole point: ``isinstance(True, int)`` is ``True`` in Python, and the OTLP
    protobuf encoder ships such a value as ``bool_value: true``. A boolean
    reaching a token count would violate SEM-04 behind a green test, and the
    backend has no way to tell it from a real count (T-02-09).

    Positive, not merely present: D-11 admits a span on evidence of work done,
    and a usage dict reporting zero everywhere would otherwise rate as a
    zero-cost completion instead of being dropped.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
