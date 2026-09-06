"""Hand-built OpenTelemetry spans shaped like the ones MLflow really emits.

**This module is written once, by plan 02-01, and imported unmodified by every
later plan in phase 2.** Plans 02-02 through 02-05 own no part of it. That is
deliberate rather than tidy: six test modules need these spans, and a builder
four plans extend independently is exactly how two fixtures come to disagree
about what an MLflow span looks like — after which a green suite proves nothing.
A shape too narrow to earn a named helper is built from
:func:`build_readable_span` at the call site, not by adding another helper here.

**Plan 02-09 is the one exception, and it is recorded rather than quietly taken.**
It widened :func:`build_readable_span` and added the ninth helper,
:func:`degenerate_span`. The rule above sends a one-off shape to the call site
because a call-site shape is read by one test; this shape had to be read by
*every* sweep. ``tests/unit/test_semconv_allowlist.py`` and
``tests/unit/test_operation_precedence.py`` derive their subjects from ``vars()``
of this module, so the malformed-input contract only reaches those guards if the
shape lives here. No pre-existing helper's defaults changed, and neither did
:data:`_CAPTURED_USAGE`, :data:`_MLFLOW_RESOURCE` or the two default timestamps —
the disagreement the rule exists to prevent is between *fixtures*, and adding a
subject to the shared module is the opposite of that.

**Nothing here imports MLflow, at module scope or anywhere else.**
``tests/conftest.py`` silences MLflow's outbound telemetry from a session-scoped
autouse fixture, and that fixture only wins the race because nothing imports
MLflow before it runs. An import in this file would be imported during pytest
collection — before any fixture — and would break the guarantee for the whole
run. The shapes below are transcribed from a real captured span, recorded in
``.planning/phases/02-span-eligibility-and-genai-semantic-conventions/02-RESEARCH.md``
§"The Wire Format", so no MLflow import is needed to reproduce them.

**Division of labour, stated so it cannot be guessed at.**
:func:`build_readable_span` stores the ``attributes`` mapping it is handed
**verbatim and encodes nothing**. The JSON encoding is done by each shaped
helper. That split is required, not stylistic: a Path A span's
``gen_ai.operation.name`` and ``gen_ai.usage.*`` values are real OpenTelemetry
attributes and must reach the predicate as bare values, so
:func:`genai_operation_span` cannot go through the same encoder
:func:`mlflow_chat_model_span` does. A caller building a one-off shape directly
from :func:`build_readable_span` is therefore on the raw side of that line and
must ``json.dumps`` its own MLflow-namespaced values at the call site.

Why every MLflow value is JSON-encoded at all: MLflow serializes every span
attribute to a JSON string before it reaches OpenTelemetry
(``mlflow/entities/span.py:1509`` at 3.16.0), so ``mlflow.spanType`` arrives on
the wire as ``'"CHAT_MODEL"'`` — six characters longer than it looks, and
identical to the bare form in a debugger that strips one layer of quoting. The
builder must produce the wire shape, not a convenience shape, or every test
downstream of it exercises a span that never existed.

Everything is imported under a private alias so that this module's public
surface is exactly the nine helpers below, checkable with one command.
"""

import json as _json
import random as _random
from collections.abc import Mapping as _Mapping
from collections.abc import Sequence as _Sequence

from opentelemetry.sdk.resources import Resource as _Resource
from opentelemetry.sdk.trace import Event as _Event
from opentelemetry.sdk.trace import ReadableSpan as _ReadableSpan
from opentelemetry.sdk.util.instrumentation import InstrumentationScope as _InstrumentationScope
from opentelemetry.trace import Link as _Link
from opentelemetry.trace import SpanContext as _SpanContext
from opentelemetry.trace import SpanKind as _SpanKind
from opentelemetry.trace import TraceFlags as _TraceFlags
from opentelemetry.trace.status import Status as _Status
from opentelemetry.trace.status import StatusCode as _StatusCode
from opentelemetry.util.types import AttributeValue as _AttributeValue

#: The span name a real captured ``CHAT_MODEL`` span carried.
_DEFAULT_SPAN_NAME = "Completions.create"

#: The instrumentation scope a real captured MLflow span carries. Measured, not
#: assumed: MLflow's tracer accessor is called with ``__name__`` from inside
#: ``mlflow/tracing/provider.py`` for the fluent and no-context span paths, which
#: is where the OpenAI, Anthropic, Gemini and Bedrock autologs all enter — so the
#: scope name is the provider module, never the integration's.
_MLFLOW_SCOPE_NAME = "mlflow.tracing.provider"

#: The resource a real captured MLflow span carries: no ``service.name`` and no
#: ``gen_ai.*``. That absence is why SEM-02 exists at all — the SDK has to
#: produce its own resource claim, because MLflow's carries nothing the backend's
#: mapper selection can key on.
#: Constructed directly rather than through ``Resource.create``, which merges in
#: OpenTelemetry's default resource and would add a ``service.name`` the captured
#: span demonstrably does not carry — quietly falsifying the one fact this
#: resource exists to reproduce.
_MLFLOW_RESOURCE = _Resource(
    attributes={
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "mlflow",
        "telemetry.sdk.version": "3.16.0",
    }
)

#: Integer nanoseconds, transcribed from the captured span. Their difference is
#: 45_980_000 ns, which is what makes a derived-duration assertion mean
#: something rather than comparing zero to zero.
_DEFAULT_START_TIME_NS = 1788633658640045000
_DEFAULT_END_TIME_NS = 1788633658686025000

#: The usage dict on the captured span, cache tokens included. ``total_tokens``
#: is present here because MLflow records it; the SDK deliberately does not emit
#: it, and a fixture that omitted it would make that omission untestable.
_CAPTURED_USAGE: _Mapping[str, int] = {
    "input_tokens": 1000,
    "output_tokens": 50,
    "total_tokens": 1050,
    "cache_read_input_tokens": 900,
}


def _mlflow_encode(values: _Mapping[str, object]) -> dict[str, _AttributeValue]:
    """JSON-encode every value, which is what MLflow puts on the wire.

    Kept here rather than inside :func:`build_readable_span` because the builder
    must stay able to carry bare, un-encoded values — see the module docstring.
    """
    return {key: _json.dumps(value) for key, value in values.items()}


def _fresh_context() -> _SpanContext:
    """A real ``SpanContext`` with a 128-bit trace id and a 64-bit span id.

    ``| 1`` guarantees both ids are non-zero, so the context is valid by
    OpenTelemetry's own definition and can never collide with the all-zero
    invalid id the mapper uses to stand in for a context it was not given.
    """
    return _SpanContext(
        trace_id=_random.getrandbits(128) | 1,
        span_id=_random.getrandbits(64) | 1,
        is_remote=False,
        trace_flags=_TraceFlags(_TraceFlags.SAMPLED),
    )


def build_readable_span(
    *,
    attributes: _Mapping[str, _AttributeValue],
    kind: _SpanKind = _SpanKind.INTERNAL,
    start_time_ns: int | None,
    end_time_ns: int | None,
    parent: _SpanContext | None = None,
    status: _Status | None = None,
    events: _Sequence[_Event] = (),
    name: str = _DEFAULT_SPAN_NAME,
    unset_status: bool = False,
    unset_events: bool = False,
    unset_context: bool = False,
) -> _ReadableSpan:
    """Build one ``ReadableSpan``, storing ``attributes`` verbatim.

    **This function encodes nothing.** Callers wanting MLflow's wire shape must
    JSON-encode their MLflow-namespaced values themselves — the shaped helpers
    below do it with :func:`_mlflow_encode`, and a one-off shape built directly
    from here does it with ``json.dumps`` at the call site. A builder that
    encoded unconditionally could not produce a Path A span, whose ``gen_ai.*``
    attributes are real OpenTelemetry attributes and arrive bare.

    The constructor field list is copied from MLflow's own ``_build_readable_span``
    (``mlflow/tracing/export/genai_semconv/translator.py:190-212`` at 3.16.0)
    rather than invented, so ``instrumentation_scope``, ``links`` and ``events``
    are passed explicitly instead of being silently dropped — a span missing its
    scope is a span the backend and the customer's own collector read differently
    from a real one.

    **``start_time_ns`` and ``end_time_ns`` accept ``None``, and that is what
    makes the mapper's own degradation branch testable.** ``map_span`` already
    contained an unset-``end_time`` fallback, and
    ``02-VERIFICATION.md`` recorded SEM-08 as ⚠ PARTIAL for exactly one reason:
    this builder typed both timings as required ``int`` and passed them straight
    through, so no test could reach the branch. They are passed through
    uncoerced for the same reason they always were — a builder that substituted
    a default here would make the branch permanently unreachable rather than
    merely untested. Both stay keyword-only and required: a caller must still
    say what the timings are, including when the answer is ``None``.

    **The three ``unset_*`` flags are separate parameters rather than an
    overload of ``status``, ``events`` and a new ``context``, deliberately.**
    The coercion ``status if status is not None else Status(OK)`` makes a
    *stored* ``None`` impossible through ``status=`` alone, and reusing the
    parameter would make ``status=None`` mean two different things depending on
    a second argument — the implicit rule this module's docstring argues
    against. Each flag reproduces one shape ``map_span`` was measured raising or
    degrading on; :func:`degenerate_span` carries all three at once and is what
    most callers want.
    """
    links: _Sequence[_Link] = ()
    resolved_status = (
        None if unset_status else (status if status is not None else _Status(_StatusCode.OK))
    )
    return _ReadableSpan(
        name=name,
        context=None if unset_context else _fresh_context(),
        parent=parent,
        resource=_MLFLOW_RESOURCE,
        attributes=attributes,
        events=None if unset_events else events,
        links=links,
        kind=kind,
        instrumentation_scope=_InstrumentationScope(_MLFLOW_SCOPE_NAME),
        status=resolved_status,
        start_time=start_time_ns,
        end_time=end_time_ns,
    )


def mlflow_chat_model_span(
    *,
    model: str = "gpt-4o",
    usage: _Mapping[str, object] | None = None,
    provider: str | None = None,
    inputs: _Mapping[str, object] | None = None,
    outputs: _Mapping[str, object] | None = None,
    start_time_ns: int = _DEFAULT_START_TIME_NS,
    end_time_ns: int = _DEFAULT_END_TIME_NS,
) -> _ReadableSpan:
    """The captured wire shape: a real MLflow ``CHAT_MODEL`` span, reproduced.

    Every attribute is JSON-encoded, the kind is ``SpanKind.INTERNAL``, the
    timings are integer nanoseconds and the span is a root. ``mlflow.spanLogLevel``
    and ``mlflow.traceRequestId`` are carried because the captured span carried
    them — they are the two attributes that make "no emitted key begins with
    ``mlflow.``" a claim with something to fail against.
    """
    values: dict[str, object] = {
        "mlflow.spanType": "CHAT_MODEL",
        "mlflow.llm.model": model,
        "mlflow.chat.tokenUsage": dict(usage) if usage is not None else dict(_CAPTURED_USAGE),
        "mlflow.spanLogLevel": 20,
        "mlflow.traceRequestId": "tr-b2f338cd27fd010778c1641c6a324124",
        "mlflow.spanOutputs": dict(outputs) if outputs is not None else {"ok": True},
    }
    if provider is not None:
        values["mlflow.llm.provider"] = provider
    if inputs is not None:
        values["mlflow.spanInputs"] = dict(inputs)
    return build_readable_span(
        attributes=_mlflow_encode(values),
        start_time_ns=start_time_ns,
        end_time_ns=end_time_ns,
    )


def mlflow_typed_span(
    *,
    span_type: str,
    usage: _Mapping[str, object] | None = None,
    model: str = "gpt-4o",
) -> _ReadableSpan:
    """The same shape, parametrized over any span-type string.

    Including one MLflow does not define — plan 02-02's fifteen-row table drives
    this helper, and criterion 1's "unknown type" case needs a string that is
    deliberately not one of MLflow's fifteen.
    """
    return build_readable_span(
        attributes=_mlflow_encode(
            {
                "mlflow.spanType": span_type,
                "mlflow.llm.model": model,
                "mlflow.chat.tokenUsage": dict(usage)
                if usage is not None
                else dict(_CAPTURED_USAGE),
            }
        ),
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
    )


def orchestration_span(
    *,
    span_type: str = "CHAIN",
    usage: _Mapping[str, object] | None = None,
) -> _ReadableSpan:
    """An orchestration-typed span that *does* carry token counts.

    The point of the helper is the combination: without token evidence a
    ``CHAIN`` span would be rejected for two reasons at once, and a test could
    not tell which one fired. Carrying tokens is what makes "the type gate is
    consulted before the token gate" provable.
    """
    return mlflow_typed_span(
        span_type=span_type,
        usage=usage if usage is not None else _CAPTURED_USAGE,
    )


def openai_autolog_shaped_span(
    *,
    model: str = "gpt-4o",
    usage: _Mapping[str, object] | None = None,
) -> _ReadableSpan:
    """What MLflow's OpenAI path actually writes — and what it never writes.

    ``mlflow/openai/autolog.py`` sets exactly ``mlflow.message.format`` and
    ``mlflow.chat.tokenUsage`` directly, plus the model through
    ``set_span_model_attribute``; it never sets ``mlflow.llm.provider``. Anthropic
    does (``mlflow/anthropic/autolog.py:140``). That asymmetry is the whole
    reason provider inference needs a step beyond reading the provider attribute,
    so this fixture deliberately omits it.
    """
    return build_readable_span(
        attributes=_mlflow_encode(
            {
                "mlflow.spanType": "CHAT_MODEL",
                "mlflow.llm.model": model,
                "mlflow.chat.tokenUsage": dict(usage)
                if usage is not None
                else dict(_CAPTURED_USAGE),
                "mlflow.message.format": "openai",
            }
        ),
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
    )


def anthropic_cache_span(
    *,
    cache_read: int = 3,
    cache_creation: int = 2,
    input_tokens: int = 100,
    output_tokens: int = 20,
    model: str = "claude-sonnet-4-5",
) -> _ReadableSpan:
    """The A/B fixture: one span fed to both mappers side by side.

    ``input_tokens`` is the total MLflow recorded, cached portion **included** —
    MLflow normalizes cache tokens in as a subset on the Anthropic and Bedrock
    paths (``mlflow/anthropic/autolog.py:194-200``). The fixture reproduces that
    relation rather than treating the cache counts as additive, because a fixture
    that got it backwards would make a double-counting mapper look correct.
    """
    return build_readable_span(
        attributes=_mlflow_encode(
            {
                "mlflow.spanType": "CHAT_MODEL",
                "mlflow.llm.model": model,
                "mlflow.llm.provider": "anthropic",
                "mlflow.message.format": "anthropic",
                "mlflow.chat.tokenUsage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_creation,
                },
            }
        ),
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
    )


def error_span(
    *,
    marker: str,
    exception_type: str = "ValueError",
    model: str = "gpt-4o",
) -> _ReadableSpan:
    """An ERROR-status span carrying ``marker`` everywhere a real failure would.

    The shape is measured, not imagined: an OpenTelemetry ``record_exception``
    writes an ``exception`` event whose attributes are ``exception.type``,
    ``exception.message`` and ``exception.stacktrace``, and a failing span's
    ``Status`` carries the exception text as its description. Both places hold
    ``marker`` verbatim, and the stacktrace value is stacktrace-shaped rather
    than a bare string, so a test planting a secret through this helper is
    testing against the real disclosure surface. Plan 02-04 does exactly that:
    it asserts the marker is present here **before** asserting it reaches no
    emitted attribute, because a clean result is also what a check that inspects
    nothing produces.
    """
    message = f"{exception_type}: {marker}"
    event = _Event(
        name="exception",
        attributes={
            "exception.type": exception_type,
            "exception.message": marker,
            "exception.stacktrace": (
                "Traceback (most recent call last):\n"
                '  File "/home/user/app/service.py", line 42, in call_model\n'
                "    raise ValueError(secret)\n"
                f"{message}\n"
            ),
            "exception.escaped": False,
        },
        timestamp=_DEFAULT_END_TIME_NS,
    )
    return build_readable_span(
        attributes=_mlflow_encode(
            {
                "mlflow.spanType": "CHAT_MODEL",
                "mlflow.llm.model": model,
                "mlflow.chat.tokenUsage": dict(_CAPTURED_USAGE),
            }
        ),
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
        status=_Status(_StatusCode.ERROR, description=message),
        events=(event,),
    )


def genai_operation_span(
    *,
    operation: str = "chat",
    model: str = "gpt-4o",
    input_tokens: int = 11,
    output_tokens: int = 7,
) -> _ReadableSpan:
    """A Path A span: bridged non-MLflow instrumentation, no MLflow attributes.

    Every value is bare rather than JSON-encoded, because these are real
    OpenTelemetry attributes written by an instrumentor that never heard of
    MLflow. That is the case the lenient decoder (D-07) exists for, and the
    reason this helper does not go through :func:`_mlflow_encode`.
    """
    attributes: dict[str, _AttributeValue] = {
        "gen_ai.operation.name": operation,
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
    }
    return build_readable_span(
        attributes=attributes,
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
    )


def degenerate_span() -> _ReadableSpan:
    """The malformed span ``map_span``'s own contract claims to survive, actually built.

    ``map_span``'s docstring says it "returns a record on **every** input and
    raises on none: a malformed attribute on one span must not fail the export
    batch it happens to be in (T-02-05)". ``classify_span`` already honours that
    half of the contract — it returns ``WRONG_TYPE`` on this shape rather than
    raising — so before this helper existed the *mapper's* half was asserted in
    a docstring and checked by nothing.

    Both shapes were reproduced against the shipped tree before this helper was
    written, and both are carried here at once so one subject covers both:

    * an unset status raised ``AttributeError: 'NoneType' object has no
      attribute 'status_code'``;
    * unset events raised ``TypeError: 'NoneType' object is not iterable``. That
      one comes out of ``ReadableSpan.events`` itself, which returns
      ``tuple(self._events)``, so reading ``span.events or ()`` at the call site
      does **not** guard it — the property raises before the ``or`` is reached.

    It also carries an empty attribute mapping and no span context, which reaches
    the two remaining degenerate branches in one go: the provider sentinel, and
    the all-zero trace and span ids that stand in for a context the mapper was
    not given.

    Public and parameterless on purpose. ``tests/unit/test_semconv_allowlist.py``
    and ``tests/unit/test_operation_precedence.py`` both derive their sweep
    subjects from ``vars()`` of this module, filtered on ``__module__``, so a
    helper with no required parameter joins both sweeps without either file
    being edited. That is the point of the shape: the malformed-input contract
    gets exercised by the closed-set guards and by the operation-agreement guard,
    not only by the tests written for it.
    """
    return build_readable_span(
        attributes={},
        start_time_ns=_DEFAULT_START_TIME_NS,
        end_time_ns=_DEFAULT_END_TIME_NS,
        unset_status=True,
        unset_events=True,
        unset_context=True,
    )
