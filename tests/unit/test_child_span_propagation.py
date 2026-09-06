"""ATTR-03: the child span is stamped for itself, and not by inheriting.

**The obvious test proves nothing, and that is the whole subject of this
module.** Open a scope, create a parent, create a child inside it, assert the
child carries the keys — per-span stamping and parent-attribute inheritance
produce byte-identical output on that shape, so the assertion passes under either
mechanism and distinguishes neither. ATTR-03's wording is specifically that
attribution "propagates onto each eligible **child** LLM span rather than relying
on parent-attribute inheritance", so a test that cannot tell those apart does not
test the requirement. It is the same cannot-fail shape Phase 2's verification
caught.

**What separates them is putting the parent and the child on opposite sides of
the scope**, which the controls below do in both directions:

============================  ==================  ==================
control                       per-span stamping   inheritance
============================  ==================  ==================
parent outside, child inside  parent bare,        both bare
                              child stamped
parent inside, child outside  parent stamped,     both stamped
                              child bare
============================  ==================  ==================

The two mechanisms disagree on both rows, so a single run of the pair decides
between them. Each control additionally asserts that the child really is a child
— same trace, and its recorded parent span id is the parent's — because a child
that was never parented would satisfy the per-span-stamping column for the wrong
reason and quietly turn the whole comparison into a tautology.

:func:`test_opentelemetry_does_not_copy_a_parent_attribute_onto_its_child` pins
the mechanism assumption the controls rest on, so a future OpenTelemetry that
started propagating attributes down the tree reds this file rather than silently
making its reasoning wrong.

Parenting is plain OpenTelemetry, through
``tests/fixtures/processors.py::start_child_span``. Nothing here imports MLflow:
what MLflow does at span creation is already pinned by 03-01's drift anchor in
``tests/unit/test_stamp_time_evidence.py``, and the mechanism under test is
OpenTelemetry's.
"""

import pytest
from opentelemetry.sdk.trace import ReadableSpan

from revenium_mlflow.attributes import (
    REVENIUM_MIDDLEWARE_SOURCE,
    REVENIUM_PRODUCT_NAME,
    REVENIUM_SUBSCRIBER_ID,
)
from revenium_mlflow.tracing import attribution
from tests.fixtures.processors import (
    build_collecting_tracer,
    revenium_attributes,
    stamped,
    start_child_span,
)

pytestmark = pytest.mark.unit

#: The creation-time attribute that makes the child an *eligible* LLM span under
#: the ``declared-only`` stamp-time rule rather than an undecided one — the shape
#: ATTR-03 is written about. The parent declares nothing, which is what an
#: orchestration span looks like at ``on_start``.
_ELIGIBLE_CHILD = {"gen_ai.operation.name": "chat"}


def _by_name(spans: list[ReadableSpan]) -> dict[str, ReadableSpan]:
    """The collected spans keyed by name, so assertions do not depend on end order.

    Args:
        spans: Whatever :class:`InMemorySpanExporter` handed back.

    Returns:
        Name to span. Names are unique within each test here, and the count is
        asserted so a silently-missing span cannot be read as a passing test.
    """
    assert len(spans) == 2, f"expected a parent and a child, got {len(spans)}"
    return {span.name: span for span in spans}


def _assert_is_child_of(child: ReadableSpan, parent: ReadableSpan) -> None:
    """The parenting itself, asserted rather than assumed.

    Args:
        child: The collected span that should be the child.
        parent: The collected span that should be its parent.

    Raises:
        AssertionError: When they are unrelated, or on different traces.

    Without this the two controls below are vacuous in the direction that
    matters: an unparented "child" would carry exactly what per-span stamping
    predicts, for the entirely unrelated reason that it had no parent to inherit
    from.
    """
    assert child.parent is not None, "the child was never parented"
    parent_context = parent.get_span_context()
    assert child.parent.span_id == parent_context.span_id
    assert child.parent.trace_id == parent_context.trace_id
    assert child.get_span_context().trace_id == parent_context.trace_id


def test_a_child_created_inside_the_scope_is_stamped_though_its_parent_is_bare() -> None:
    """Control one. Under inheritance the child would be as bare as its parent.

    The parent is created before the scope opens, so it carries nothing to
    inherit. The child is created inside the scope, parented to it explicitly.
    A stamped child descending from a bare parent is a result inheritance cannot
    produce.
    """
    tracer, exporter = build_collecting_tracer()

    parent = tracer.start_span("orchestration")
    with attribution(subscriber_id="s-1", product_name="p-1"):
        start_child_span(tracer, parent, "chat", attributes=_ELIGIBLE_CHILD).end()
    parent.end()

    collected = _by_name(exporter.get_finished_spans())
    _assert_is_child_of(collected["chat"], collected["orchestration"])

    assert revenium_attributes(collected["orchestration"]) == {}
    assert revenium_attributes(collected["chat"]) == stamped(
        {REVENIUM_SUBSCRIBER_ID: "s-1", REVENIUM_PRODUCT_NAME: "p-1"}
    )


def test_a_child_created_outside_the_scope_is_bare_though_its_parent_is_stamped() -> None:
    """Control two, the inverse. Under inheritance the child would carry the keys.

    The parent is created inside the scope and the child after it closes. This is
    the direction that catches attribution flowing *down* a trace: a child
    carrying its parent's attribution here would mean something other than the
    ContextVar in effect at the child's own ``on_start`` is delivering the keys,
    and whatever that something was would also deliver a closed scope's
    attribution to the next request that reused the trace.
    """
    tracer, exporter = build_collecting_tracer()

    with attribution(subscriber_id="s-1", product_name="p-1"):
        parent = tracer.start_span("orchestration")
    start_child_span(tracer, parent, "chat", attributes=_ELIGIBLE_CHILD).end()
    parent.end()

    collected = _by_name(exporter.get_finished_spans())
    _assert_is_child_of(collected["chat"], collected["orchestration"])

    assert revenium_attributes(collected["orchestration"]) == stamped(
        {REVENIUM_SUBSCRIBER_ID: "s-1", REVENIUM_PRODUCT_NAME: "p-1"}
    )
    assert revenium_attributes(collected["chat"]) == {}


def test_a_nested_scope_gives_parent_and_child_different_values_on_one_trace() -> None:
    """The real agent shape: a CHAIN parent wrapping an autologged CHAT_MODEL child.

    The outer scope names the subscriber and a product; the inner scope overrides
    the product only, and the child is created under it. Parent and child end up
    carrying *different* values for the same key on the same trace, which is only
    possible if each was stamped at its own start from the state in effect at that
    moment. A single write applied to a trace, or to a parent and copied down,
    cannot produce two values.

    It is also the shape a real MLflow application actually has: the child LLM
    span is created by autologging, inside the parent, and the application never
    sees it — so the child is precisely the span nobody can stamp by hand.
    """
    tracer, exporter = build_collecting_tracer()

    with attribution(subscriber_id="s-1", product_name="outer"):
        parent = tracer.start_span("chain")
        with attribution(product_name="inner"):
            start_child_span(tracer, parent, "chat", attributes=_ELIGIBLE_CHILD).end()
        parent.end()

    collected = _by_name(exporter.get_finished_spans())
    _assert_is_child_of(collected["chat"], collected["chain"])

    assert revenium_attributes(collected["chain"]) == stamped(
        {REVENIUM_SUBSCRIBER_ID: "s-1", REVENIUM_PRODUCT_NAME: "outer"}
    )
    assert revenium_attributes(collected["chat"]) == stamped(
        {REVENIUM_SUBSCRIBER_ID: "s-1", REVENIUM_PRODUCT_NAME: "inner"}
    )
    assert (
        revenium_attributes(collected["chain"])[REVENIUM_MIDDLEWARE_SOURCE]
        == revenium_attributes(collected["chat"])[REVENIUM_MIDDLEWARE_SOURCE]
    )


def test_opentelemetry_does_not_copy_a_parent_attribute_onto_its_child() -> None:
    """The mechanism assumption behind both controls, pinned against the installed SDK.

    The controls above read as decisive only because an OpenTelemetry child does
    not inherit its parent's attributes at all — the ``revenium.*`` keys are
    merely one case of that. Asserted here on a non-``revenium.`` attribute so it
    is a statement about OpenTelemetry rather than about this processor, and with
    no attribution scope open at all so nothing this SDK does is involved.

    If a future OpenTelemetry release starts propagating attributes down the
    tree, this goes red first and says so, rather than leaving the controls
    passing for a reason that no longer holds.
    """
    tracer, exporter = build_collecting_tracer()

    parent = tracer.start_span("orchestration", attributes={"probe.marker": "parent-only"})
    start_child_span(tracer, parent, "chat", attributes=_ELIGIBLE_CHILD).end()
    parent.end()

    collected = _by_name(exporter.get_finished_spans())
    _assert_is_child_of(collected["chat"], collected["orchestration"])

    assert (collected["orchestration"].attributes or {})["probe.marker"] == "parent-only"
    assert "probe.marker" not in (collected["chat"].attributes or {})
