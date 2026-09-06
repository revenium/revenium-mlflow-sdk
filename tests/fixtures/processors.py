"""The in-memory collector every plan in phase 3 asserts against.

**This module is written once, by plan 03-01, and imported unmodified by every
later plan in phase 3.** It is the same single-owner rule ``tests/fixtures/spans.py``
states for phase 2, adopted here for the same reason: six test modules that each
stand up their own tracer and their own exporter are how two fixtures come to
disagree about what "collected" means, after which a green suite proves nothing.

**The attribution processor is registered first, before the exporting one.** That
ordering is production's, not a convenience: in a real process MLflow's own
processors are already attached to the bridged provider and this SDK's is
appended after them, so the stamp must be written by a processor that runs before
whatever finally exports. A fixture that registered them the other way round
would pass while production lost the attribute.

**Assert on what the exporter collected, never on the live span the test still
holds.** A live-span assertion passes even when the attribute never survived to
export — it reads the same mutable object the processor just wrote to. That is
the assertion shape VER-03 exists to rule out, and it is exactly the shape
``tests/unit/test_on_start_not_on_end.py`` demonstrates going green against a
processor that loses every attribute. :func:`revenium_attributes` therefore takes
a finished :class:`ReadableSpan`, which is what
:class:`InMemorySpanExporter` hands back.

**Nothing here imports MLflow, at module scope or anywhere else.**
``tests/conftest.py`` silences MLflow's outbound telemetry from a session-scoped
autouse fixture, and that fixture only wins its race because nothing imports
MLflow before it runs. This module is imported during pytest *collection*, which
finishes before any fixture runs, so an import here would break the guarantee for
the whole suite. Nothing in phase 3's attribution path needs MLflow: the freeze
being reproduced is OpenTelemetry's.

Everything is imported under a private alias so this module's public surface is
exactly the names below.
"""

from opentelemetry.sdk.trace import ReadableSpan as _ReadableSpan
from opentelemetry.sdk.trace import SpanProcessor as _SpanProcessor
from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor as _SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter as _InMemorySpanExporter,
)
from opentelemetry.trace import Tracer as _Tracer
from opentelemetry.util.types import AttributeValue as _AttributeValue

from revenium_mlflow.attributes import REVENIUM_SUBSCRIBER_ID as _REVENIUM_SUBSCRIBER_ID
from revenium_mlflow.tracing import ReveniumAttributionSpanProcessor as _ShippedProcessor
from revenium_mlflow.tracing import attribution as _attribution

#: The prefix every ATTR-07 key carries. :func:`revenium_attributes` filters on
#: the prefix rather than on membership of ``REVENIUM_ATTRIBUTE_KEYS``, and the
#: difference matters in exactly one direction: a processor that wrote
#: ``revenium.subscriber.idd`` would be invisible to a membership filter and is
#: caught by this one. Filtering on the prefix can only ever report *more* than
#: the key list, never less, so every assertion of the form "no key from
#: ``REVENIUM_ATTRIBUTE_KEYS``" is satisfied a fortiori.
_REVENIUM_PREFIX = "revenium."

#: The subscriber id the shared tracer assertion uses. Held here so the assertion
#: and its inverted twin in ``tests/unit/test_on_start_not_on_end.py`` cannot
#: drift onto two different values and stop being the same assertion.
SCOPED_SUBSCRIBER_ID = "s-1"


def build_collecting_tracer(
    *,
    processor: _SpanProcessor | None = None,
    scope_name: str = "revenium_mlflow.tests",
) -> tuple[_Tracer, _InMemorySpanExporter]:
    """A private ``TracerProvider`` with the attribution processor and a collector.

    Args:
        processor: The attribution processor under test. Defaults to the shipped
            :class:`ReveniumAttributionSpanProcessor`. It is a parameter rather
            than a fixed construction because the falsifiability control in
            ``tests/unit/test_on_start_not_on_end.py`` has to substitute a
            deliberately wrong processor into *this* assertion path — a control
            that ran against a separately-built tracer would be proving something
            about its own tracer instead.
        scope_name: The instrumentation scope name. Irrelevant to every
            assertion in this phase and named anyway, so a span produced here is
            identifiable in a failure dump.

    Returns:
        The tracer and the exporter, together. Returned as a pair rather than
        through a provider handle because every caller needs both and a caller
        that had to reach back through the provider for the exporter would be
        one refactor away from reading a different exporter than the one it
        registered.

    The provider is constructed here and never installed globally: nothing calls
    ``trace.set_tracer_provider``. OpenTelemetry's global provider can be set
    exactly once per process, so a fixture that installed one would make the
    second test in the suite silently read the first test's provider.
    """
    provider = _TracerProvider()
    provider.add_span_processor(processor if processor is not None else _ShippedProcessor())
    exporter = _InMemorySpanExporter()
    provider.add_span_processor(_SimpleSpanProcessor(exporter))
    return provider.get_tracer(scope_name), exporter


def revenium_attributes(span: _ReadableSpan, /) -> dict[str, _AttributeValue]:
    """The ``revenium.*`` subset of a **finished** span's attributes.

    Args:
        span: A span :class:`InMemorySpanExporter` collected, not a live one.

    Returns:
        Only the keys under the ``revenium.`` prefix, so an assertion can be an
        equality against the whole expected mapping rather than a membership
        check that would pass while nineteen other keys leaked alongside it.
    """
    return {
        key: value
        for key, value in (span.attributes or {}).items()
        if key.startswith(_REVENIUM_PREFIX)
    }


def assert_the_scope_reaches_the_collected_span(processor: _SpanProcessor, /) -> None:
    """The phase's tracer assertion, parametrized over the processor under test.

    Args:
        processor: The attribution processor to run the assertion against.

    Raises:
        AssertionError: When the scoped subscriber id is not on the collected
            span. That is the whole point of the helper: ``test_attribution_scope``
            calls it with the shipped processor and expects it to pass, and
            ``test_on_start_not_on_end`` calls it with an ``on_end``-writing
            processor *inside* ``pytest.raises(AssertionError)`` and expects it
            to fail. One function, two call sites, opposite expectations — which
            is what makes "this assertion is able to fail" a demonstration rather
            than a comment.
    """
    tracer, exporter = build_collecting_tracer(processor=processor)
    with _attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span("chat").end()
    collected = exporter.get_finished_spans()
    assert len(collected) == 1, f"expected exactly one collected span, got {len(collected)}"
    assert revenium_attributes(collected[0]) == {_REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID}
