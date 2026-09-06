"""ATTR-02: the same write, at two times, in one process — and one of them is lost.

This module exists because ATTR-02 is the load-bearing requirement in phase 3 and
its failure mode is silent. Every other requirement here fails loudly if it is
implemented wrongly. This one produces spans that export successfully, arrive at
the customer's Tracking Server, arrive at Revenium, and carry no attribution at
all — from a processor that is installed, runs for every span, and reports
nothing.

**Two failure shapes, and only one of them is the dangerous one.**

* Writing through ``on_end``'s own argument raises ``AttributeError``: the
  argument is a ``ReadableSpan``, which has no ``set_attribute`` on it at all.
  This is the loud version. Nobody ships it, because it fails the first time it
  runs.
* Writing through a live span reference *retained* from ``on_start`` does not
  raise. That object does have the method, and ``Span.end()`` has already frozen
  the attribute store behind it, so the call returns normally and the value is
  discarded. This is the version that survives review.

Both are asserted below, and the silent one is asserted on **both** of its
halves — that the write does not raise, *and* that the value is absent.
"Does not raise" is not a footnote here; it is the property that lets the bug
live, and a test that only checked for the missing attribute would pass equally
well against a processor that never ran.

**The falsifiability control (VER-03).** A test asserting "we stamp in
``on_start``" is worthless unless it can fail against an implementation that
stamps in ``on_end``. The last test in this module runs the *same function*
``tests/unit/test_attribution_scope.py`` calls — not a copy of it — against the
``on_end`` variant, inside ``pytest.raises(AssertionError)``, and then runs it
against the shipped processor and expects it to pass. A comment claiming the
assertion can fail is not evidence. The inverted run is.

**Nothing here imports MLflow**, at module scope or inside a function body. The
freeze being reproduced is OpenTelemetry's — ``Span.end()`` and ``ReadableSpan``
— and MLflow contributes nothing to it beyond suppressing the warning that would
otherwise reveal it. A plain ``TracerProvider`` reproduces the whole thing, and
keeps the module out of the collection-time import race ``tests/conftest.py``
records.
"""

import logging

import pytest
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from revenium_mlflow.attributes import REVENIUM_SUBSCRIBER_ID
from revenium_mlflow.tracing import ReveniumAttributionSpanProcessor, attribution
from tests.fixtures.processors import (
    SCOPED_SUBSCRIBER_ID,
    OnEndWritingAttributionProcessor,
    assert_the_scope_reaches_the_collected_span,
    build_collecting_tracer,
    revenium_attributes,
    stamped,
)

pytestmark = pytest.mark.unit


class _ArgumentWritingOnEndProcessor(SpanProcessor):
    """The loud mistake: writing through ``on_end``'s own ``ReadableSpan`` argument.

    Kept in this module rather than in ``tests/fixtures/processors.py`` under that
    file's own rule — a shape read by exactly one test module is built at the call
    site, and only the *silent* control is shared, because plan 03-06 needs that
    one too.

    The exception is caught and recorded rather than allowed to propagate.
    ``SynchronousMultiSpanProcessor.on_end`` calls each processor directly with no
    guard of its own, so an escaping ``AttributeError`` would surface out of
    ``span.end()`` and abort the test before it could assert anything about it.
    """

    def __init__(self) -> None:
        """Start with nothing raised and nothing returned."""
        #: What the write raised. Expected to hold exactly one ``AttributeError``.
        self.raised: list[BaseException] = []
        #: How many writes returned normally. Expected to stay zero — a non-zero
        #: value would mean ``on_end``'s argument had become mutable, which is
        #: the assumption underneath this whole module.
        self.returned_normally = 0

    def on_end(self, span: ReadableSpan) -> None:
        """Attempt the write the type system already forbids, and record the result."""
        try:
            span.set_attribute(REVENIUM_SUBSCRIBER_ID, SCOPED_SUBSCRIBER_ID)
            self.returned_normally += 1
        except AttributeError as error:
            self.raised.append(error)


def _collect_one_scoped_span(processor: SpanProcessor) -> ReadableSpan:
    """One span, created inside one attribution scope, returned as the exporter saw it.

    Args:
        processor: The attribution processor under test.

    Returns:
        The single collected span. Everything about the two runs in the A/B below
        is identical except this argument, which is what makes the comparison a
        statement about write timing.
    """
    tracer, exporter = build_collecting_tracer(processor=processor)
    with attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span("chat").end()
    (collected,) = exporter.get_finished_spans()
    return collected


def test_the_on_end_write_is_silent_and_the_on_start_write_arrives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The A/B, in one function, in one process — the whole of ATTR-02.

    Same tracer construction, same scope, same key, same value. The only
    difference between the two runs is the callback the write happens in, and one
    of them loses it without raising.
    """
    with caplog.at_level(logging.WARNING, logger="opentelemetry.sdk.trace"):
        losing = OnEndWritingAttributionProcessor()
        lost = _collect_one_scoped_span(losing)
        kept = _collect_one_scoped_span(ReveniumAttributionSpanProcessor())

    # Non-vacuity first: a run that attempted no write would satisfy the
    # absent-attribute assertion below for entirely the wrong reason. The control
    # writes one attribute per resolved key, and a scope naming one parameter now
    # resolves to two — the named key and the defaulted ``middleware.source``
    # (ATTR-08) — so the expected count is derived from the same helper the
    # arrival assertion uses rather than left as the literal 1 it was before that
    # default existed.
    expected_writes = len(stamped({REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID}))
    assert losing.writes_attempted == expected_writes, (
        "the control never attempted the writes it exists to make"
    )

    # The half that makes the bug survivable: the call returns.
    assert losing.write_errors == []

    # And the half that makes it expensive.
    assert revenium_attributes(lost) == {}

    # The shipped path, on the same shape, in the same process.
    assert revenium_attributes(kept) == stamped({REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID})

    # Precisely how loud the loss is, measured rather than assumed. OpenTelemetry
    # does emit one thing — a WARNING on the ``opentelemetry.sdk.trace`` logger —
    # and that log line is the entire signal: no exception, no return value, no
    # metric, and nothing at all on the exported span. It is recorded here so the
    # word "silent" in this module means something checkable, and because it is
    # the one thread a future debugger has to pull on. The class docstring on
    # ``ReveniumAttributionSpanProcessor`` records that MLflow suppresses this
    # warning in a real deployment, which is what removes even that thread.
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert {record.name for record in warnings} == {"opentelemetry.sdk.trace"}
    assert len(warnings) == expected_writes
    assert all("ended span" in record.getMessage() for record in warnings)


def test_writing_through_on_ends_own_argument_raises_attribute_error() -> None:
    """The loud half, asserted so the silent half is known to be the *other* one.

    Without this, "the ``on_end`` write is silent" would be an unsupported claim
    about which of two failure modes the retained-reference control reproduces.
    """
    probe = _ArgumentWritingOnEndProcessor()
    tracer, exporter = build_collecting_tracer(processor=probe)
    tracer.start_span("chat").end()

    assert probe.returned_normally == 0
    assert [type(error) for error in probe.raised] == [AttributeError]
    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == {}


def test_the_tracer_assertion_fails_against_an_on_end_implementation() -> None:
    """The control is a control: the passing assertion is shown able to fail.

    ``assert_the_scope_reaches_the_collected_span`` is the *same object*
    ``test_attribution_scope.py`` calls to prove the tracer works. Running it here
    against the ``on_end`` variant and requiring an ``AssertionError`` is what
    distinguishes an assertion that holds from an assertion that cannot fail —
    the shape phase 2's verification caught more than once.

    Both directions are asserted in one function on purpose. A test that only
    demonstrated the failure would still pass if the helper had been broken into
    always raising.
    """
    with pytest.raises(AssertionError):
        assert_the_scope_reaches_the_collected_span(OnEndWritingAttributionProcessor())

    assert_the_scope_reaches_the_collected_span(ReveniumAttributionSpanProcessor())


def test_the_control_writes_nothing_when_there_is_no_attribution_scope() -> None:
    """The control differs from the shipped processor in timing and nothing else.

    If it stamped unscoped spans it would be a second variable in the A/B above,
    and the comparison would stop being about when the write happens.
    """
    losing = OnEndWritingAttributionProcessor()
    tracer, exporter = build_collecting_tracer(processor=losing)
    tracer.start_span("chat").end()

    (collected,) = exporter.get_finished_spans()
    assert losing.writes_attempted == 0
    assert revenium_attributes(collected) == {}


def test_the_processors_disagree_about_the_span_and_agree_about_the_parent_context() -> None:
    """``parent_context`` is unused by the shipped processor, and stays unused.

    ``on_start``'s second parameter is part of the ``SpanProcessor`` contract and
    is deliberately not consulted: the attribution comes from the ``ContextVar``
    in effect on the current task, which is the same context the span was created
    under by construction. Passing an explicit ``Context()`` must therefore change
    nothing at all — a processor that started reading attribution out of the
    parent context would silently stop attributing spans created with an explicit
    one.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span("chat", context=Context()).end()

    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == stamped({REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID})
