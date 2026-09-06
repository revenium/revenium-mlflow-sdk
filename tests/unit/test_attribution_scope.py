"""Attribution reaches a collected span, and only the spans it should.

Every assertion here reads a span the ``InMemorySpanExporter`` collected, never
the live span object the test still holds a reference to. The distinction is the
whole reason this module can be trusted: a live-span assertion reads the same
mutable object the processor just wrote to, so it passes even when the attribute
never survived to export. ``tests/unit/test_on_start_not_on_end.py`` demonstrates
that exact failure going undetected, in one process, against a processor that
writes at the wrong time.

**Nothing here imports MLflow.** Not at module scope, not inside a function body.
The behaviour under test is OpenTelemetry's — a ``SpanProcessor.on_start``
callback and a ``ContextVar`` — and MLflow contributes nothing to it. The
stamp-time facts that *do* depend on MLflow are asserted against the installed
MLflow in ``tests/unit/test_stamp_time_evidence.py``, which imports it inside
function bodies for the reason ``tests/conftest.py`` records.

**The three declared-operation tests are the shape of the checkpoint decision.**
Plan 03-01 opened with a ``checkpoint:decision`` — ``gate="blocking-human"`` —
about what the processor may consult at a point in the span lifecycle where
eligibility is not yet knowable. It was answered ``declared-only``: skip the
stamp only when the span *declares* an operation that is not billable, and stamp
the span that declares nothing, because at ``on_start`` "declares nothing" means
undecided rather than ineligible. All three cases are asserted below, in the same
module, because a rule with only its rejecting half tested is indistinguishable
from a rule that rejects everything, and a rule with only its stamping half
tested is indistinguishable from no rule at all.
"""

import asyncio

import pytest

from revenium_mlflow.attributes import REVENIUM_PRODUCT_NAME, REVENIUM_SUBSCRIBER_ID
from revenium_mlflow.tracing import ReveniumAttributionSpanProcessor, attribution
from tests.fixtures.processors import (
    SCOPED_SUBSCRIBER_ID,
    assert_the_scope_reaches_the_collected_span,
    build_collecting_tracer,
    revenium_attributes,
    stamped,
)
from tests.fixtures.spans import genai_operation_span

pytestmark = pytest.mark.unit


def _creation_attributes(*, operation: str) -> dict[str, object]:
    """A bridged instrumentor's creation-time attributes, from the shared fixture.

    Sourced from ``tests/fixtures/spans.py::genai_operation_span`` rather than
    written out here, so the shape this processor is asked to reject is the same
    shape ``eligibility.classify_span`` is tested against one module over. A
    hand-written dict would be a second opinion about what a Path A span looks
    like, which is the disagreement the shared fixture module exists to prevent.
    """
    return dict(genai_operation_span(operation=operation).attributes or {})


def test_a_span_created_inside_the_scope_is_collected_carrying_the_subscriber_id() -> None:
    """ATTR-01 and ATTR-03, end to end: ContextVar, processor, exporter, assertion.

    Delegated to the shared helper rather than written inline, because
    ``tests/unit/test_on_start_not_on_end.py`` runs this *same function* against
    an ``on_end``-writing processor and expects an ``AssertionError``. Inlining it
    here would leave that control proving something about a copy.
    """
    assert_the_scope_reaches_the_collected_span(ReveniumAttributionSpanProcessor())


def test_a_span_created_outside_any_scope_carries_no_revenium_key() -> None:
    """The processor is installed for every span in the process, and stamps none of them.

    Without this, a processor that unconditionally wrote a hardcoded subscriber
    id would pass the test above.
    """
    tracer, exporter = build_collecting_tracer()
    tracer.start_span("chat").end()
    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == {}


def test_leaving_the_scope_restores_what_was_in_effect_before_it() -> None:
    """ATTR-04's normal path, asserted on spans rather than on internal state.

    The span created after the inner scope closes carries the outer subscriber id
    and not the inner one, which is a statement about restore that survives any
    change to how the snapshot is represented.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id="outer"):
        with attribution(subscriber_id="inner"):
            tracer.start_span("inside-the-inner-scope").end()
        tracer.start_span("after-the-inner-scope").end()
    tracer.start_span("outside-every-scope").end()

    collected = {span.name: revenium_attributes(span) for span in exporter.get_finished_spans()}
    assert collected == {
        "inside-the-inner-scope": stamped({REVENIUM_SUBSCRIBER_ID: "inner"}),
        "after-the-inner-scope": stamped({REVENIUM_SUBSCRIBER_ID: "outer"}),
        "outside-every-scope": {},
    }


def test_a_nested_scope_merges_over_the_outer_one_without_mutating_it() -> None:
    """T-03-01: the snapshot is copy-on-write, and a nested scope proves it.

    The inner scope names a key the outer one did not, so the inner span must
    carry *both* — that is the merge. The span after it must carry only the outer
    key — that is the outer snapshot having survived unmutated, which is what a
    sibling asyncio task is concurrently reading and what the outer ``Token``
    restores.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id="s-1"):
        with attribution(product_name="p-1"):
            tracer.start_span("nested").end()
        tracer.start_span("outer-again").end()

    collected = {span.name: revenium_attributes(span) for span in exporter.get_finished_spans()}
    assert collected == {
        "nested": stamped({REVENIUM_SUBSCRIBER_ID: "s-1", REVENIUM_PRODUCT_NAME: "p-1"}),
        "outer-again": stamped({REVENIUM_SUBSCRIBER_ID: "s-1"}),
    }


def test_a_raising_body_restores_the_prior_state_and_propagates_the_same_exception() -> None:
    """ATTR-04's exception path — T-03-02, the one that leaks across requests.

    A scope that failed to restore on the exception path would leave the failed
    request's attribution installed for whatever ran next on the same task, which
    on a reused worker means one customer's traffic billed to another. The
    identity check on the exception matters too: a ``finally`` that raised its own
    error would replace the caller's exception with the SDK's and lose the
    original stack.
    """
    tracer, exporter = build_collecting_tracer()
    sentinel = RuntimeError("the scope body failed")

    with attribution(subscriber_id="outer"):
        with pytest.raises(RuntimeError) as excinfo, attribution(subscriber_id="inner"):
            raise sentinel
        assert excinfo.value is sentinel
        tracer.start_span("after-the-raise").end()

    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == stamped({REVENIUM_SUBSCRIBER_ID: "outer"})


@pytest.mark.asyncio
async def test_two_interleaved_asyncio_tasks_never_see_each_others_attribution() -> None:
    """ATTR-05 at tracer scale. The 200-task, 50-repetition bijection is 03-07.

    ``await asyncio.sleep(0)`` between setting the scope and creating the span is
    what makes the interleaving real rather than nominal: it yields to the event
    loop at exactly the point where a shared, mutable snapshot would let the
    second task's value overwrite the first task's before its span is created.
    """
    tracer, exporter = build_collecting_tracer()

    async def traced(subscriber: str) -> None:
        with attribution(subscriber_id=subscriber):
            await asyncio.sleep(0)
            tracer.start_span(subscriber).end()
            await asyncio.sleep(0)

    await asyncio.gather(traced("s-1"), traced("s-2"))

    collected = {span.name: revenium_attributes(span) for span in exporter.get_finished_spans()}
    assert collected == {
        "s-1": stamped({REVENIUM_SUBSCRIBER_ID: "s-1"}),
        "s-2": stamped({REVENIUM_SUBSCRIBER_ID: "s-2"}),
    }


def test_a_span_declaring_an_ineligible_operation_at_creation_is_not_stamped() -> None:
    """The rejecting half of ``declared-only``, exercised rather than merely written.

    A bridged non-MLflow instrumentor that states ``gen_ai.operation.name`` at
    span creation is the one span whose ineligibility *is* knowable at
    ``on_start``. ``execute_tool`` is not a member of
    ``BILLABLE_GENAI_OPERATIONS``, so it is rejected and never carries
    ``revenium.subscriber.email`` into the customer's own tracing store.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span(
            "execute_tool", attributes=_creation_attributes(operation="execute_tool")
        ).end()

    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == {}


def test_a_span_declaring_a_billable_operation_at_creation_is_stamped() -> None:
    """The admitting half, on the same shape — so the rejection above is about the value.

    Without this the previous test would pass equally well against a processor
    that refused to stamp any span carrying a ``gen_ai.*`` attribute at all.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span("chat", attributes=_creation_attributes(operation="chat")).end()

    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == stamped({REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID})


def test_a_span_declaring_no_operation_at_creation_is_stamped() -> None:
    """Undecided is stamped — the half of the decision that makes the SDK work at all.

    Every span MLflow creates arrives here: ``mlflow.spanType`` is the JSON
    literal for absent at ``on_start`` and is set afterwards, so a rule that
    treated "no resolvable operation" as "ineligible" would stamp nothing, report
    nothing, and look installed. This assertion is what goes red if anyone ever
    tightens the gate to ``classify_span(span) is ADMITTED``.
    """
    tracer, exporter = build_collecting_tracer()
    with attribution(subscriber_id=SCOPED_SUBSCRIBER_ID):
        tracer.start_span("Completions.create").end()

    (collected,) = exporter.get_finished_spans()
    assert revenium_attributes(collected) == stamped({REVENIUM_SUBSCRIBER_ID: SCOPED_SUBSCRIBER_ID})
