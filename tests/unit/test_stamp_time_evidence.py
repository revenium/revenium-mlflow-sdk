"""The measurement plan 03-01's checkpoint decision rests on, pinned to MLflow.

``ReveniumAttributionSpanProcessor.on_start`` does **not** gate the stamp on
:func:`eligibility.classify_span`, and the reason is a measurement rather than a
preference: at ``on_start`` MLflow has not yet set ``mlflow.spanType``, so
``classify_span`` returns ``WRONG_TYPE`` for every span in the process, billable
ones included. A processor gated on it would be installed, would observe every
span, would stamp nothing, and would report no error.

That is a fact about MLflow, not about this SDK, and facts about MLflow expire.
This module is the drift anchor for it — the same discipline
``tests/unit/test_mlflow_vocabulary_drift.py`` applies to the span-type
vocabulary. If a future MLflow release starts setting ``mlflow.spanType`` at span
creation, the ``declared-only`` rule stops being the only workable one and the
decision should be reopened. Failing the build is how that reaches a person.
Reporting it and continuing would leave a docstring quietly claiming a
measurement nobody had re-run.

**Three assertions, three distinct ways the decision can rot.**

1. At ``on_start``, ``mlflow.spanType`` does not decode to a member of
   ``KNOWN_MLFLOW_SPAN_TYPES``. Derived from that vocabulary constant rather than
   compared against the observed ``'null'`` literal, so a release that starts
   setting a *real* type at creation goes red and names itself, and a release
   that merely changes how absence is spelled does not produce a false alarm.
2. At ``on_start``, ``classify_span`` returns ``WRONG_TYPE`` for a span that is
   ``ADMITTED`` at ``on_end`` — the contradiction stated as an assertion instead
   of as prose.
3. At ``on_end``, that same span reaches ``ADMITTED``. This is the half that
   makes the export-time filter (EXP-02) the place SEM-11 is genuinely enforced,
   and without it assertion 2 would also be satisfied by an MLflow that never
   admitted anything at all.

All three run against **all three** span-creation paths MLflow offers, because
the autolog integrations do not all use the same one: ``mlflow.start_span``, the
``@mlflow.trace`` decorator, and ``start_span_no_context``, which is the path
autolog takes for child LLM spans.

**Every MLflow import is inside a function body, and none at module scope.**
``tests/conftest.py`` silences MLflow's outbound telemetry from a session-scoped
autouse fixture whose own comment records the condition that makes it work:
nothing imports MLflow at module scope. pytest imports every test module during
*collection*, which finishes before any session-scoped fixture runs, so a
module-scope import here would make an outbound MLflow telemetry call on every
run of the entire suite — in a project whose PROJECT.md forbids network calls to
any hosted endpoint during development or testing. The OpenTelemetry and
``revenium_mlflow`` imports may stay at module scope: neither pulls MLflow in,
and ``test_public_surface.py`` asserts the second of those in a clean
interpreter.

**The tracking store is an explicit ``sqlite:`` file under ``tmp_path``.** MLflow
logs a finished trace to whatever tracking URI it can resolve. Left to a default
it reaches for the file store, which is in maintenance mode as of 3.16.0 and
raises unless ``MLFLOW_ALLOW_FILE_STORE=true`` — and a default that *did* resolve
could point at something hosted. A temporary sqlite file is local, disposable,
and unambiguous.
"""

import dataclasses
import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from revenium_mlflow.tracing._spanattrs import MLFLOW_SPAN_TYPE, decode
from revenium_mlflow.tracing.eligibility import EligibilityReason, classify_span

pytestmark = pytest.mark.unit

#: The three span-creation paths, named by the span name each one produces so a
#: failure message says which path drifted.
_START_SPAN = "path-a-start-span"
_TRACE_DECORATOR = "path-b-trace-decorator"
_NO_CONTEXT = "path-c-start-span-no-context"
_PATHS = (_START_SPAN, _TRACE_DECORATOR, _NO_CONTEXT)

#: Token counts written onto every probe span. Positive and present, so that a
#: span reaching ``on_end`` is rejected for its *type* or admitted outright, and
#: never for missing token evidence — which would make assertion 3 pass for a
#: reason that has nothing to do with what is being measured.
_USAGE: Mapping[str, int] = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

#: Resolved from this file rather than from the working directory, so the
#: transcript check means the same thing run from anywhere.
_EVIDENCE_DOCUMENT = (
    Path(__file__).resolve().parents[2] / "docs" / "verification" / "attr-02-stamp-time.md"
)


@dataclasses.dataclass(frozen=True)
class _Capture:
    """What the probe saw about one span at one moment in its life."""

    #: ``mlflow.spanType`` exactly as it sits on the wire, JSON encoding included.
    raw_span_type: object
    #: The same value through the SDK's own shared decoder, which is what every
    #: predicate in this package actually reads.
    decoded_span_type: object
    #: The eligibility verdict at that moment.
    verdict: EligibilityReason


def _capture(span: ReadableSpan) -> _Capture:
    """Read the three facts under test off one span, at whatever moment this is called."""
    attributes: Mapping[str, object] = span.attributes or {}
    return _Capture(
        raw_span_type=attributes.get(MLFLOW_SPAN_TYPE),
        decoded_span_type=decode(attributes, MLFLOW_SPAN_TYPE),
        verdict=classify_span(span),
    )


class _StampTimeProbe(SpanProcessor):
    """Records each span at ``on_start`` and again at ``on_end``, and changes nothing.

    A read-only observer on purpose. It is attached to the *process-global*
    bridged tracer provider — ``add_span_processor`` does not deduplicate and
    there is no public way to detach one — so anything it wrote would follow
    MLflow around for the rest of the session.
    """

    def __init__(self, captures: dict[str, dict[str, _Capture]]) -> None:
        """Record into ``captures``, keyed by span name and then by moment."""
        self._captures = captures

    def on_start(self, span: Span, parent_context: object = None) -> None:
        """Snapshot the span as OpenTelemetry created it, before MLflow finished with it."""
        self._captures.setdefault(span.name, {})["on_start"] = _capture(span)

    def on_end(self, span: ReadableSpan) -> None:
        """Snapshot it again once MLflow has set the type and the token counts."""
        self._captures.setdefault(span.name, {})["on_end"] = _capture(span)


@pytest.fixture(scope="module")
def captures(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, dict[str, _Capture]]]:
    """Attach the probe once, drive all three paths, hand back what it saw.

    Module-scoped because attaching the probe is not undoable: OpenTelemetry's
    ``add_span_processor`` appends, and the bridged provider is global to the
    process. Attaching one per test would leave a growing stack of probes writing
    into stale dictionaries.
    """
    recorded: dict[str, dict[str, _Capture]] = {}
    database = tmp_path_factory.mktemp("mlflow-tracking") / "tracking.db"

    previous = os.environ.get("MLFLOW_TRACKING_URI")
    os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{database}"
    try:
        import mlflow

        # The public attachment point. ``mlflow.tracing.provider`` is banned by
        # TID251 and would need the ``_compat`` boundary; this needs neither,
        # which is the whole reason PKG-03 puts the MLflow floor at 3.15.0.
        mlflow.tracing.get_bridged_tracer_provider().add_span_processor(_StampTimeProbe(recorded))

        with mlflow.start_span(name=_START_SPAN, span_type="CHAT_MODEL") as span:
            span.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))

        @mlflow.trace(name=_TRACE_DECORATOR, span_type="CHAT_MODEL")
        def traced() -> None:
            active = mlflow.get_current_active_span()
            assert active is not None
            active.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))

        traced()

        detached = mlflow.start_span_no_context(name=_NO_CONTEXT, span_type="CHAT_MODEL")
        detached.set_attribute("mlflow.chat.tokenUsage", dict(_USAGE))
        detached.end()

        yield recorded
    finally:
        if previous is None:
            os.environ.pop("MLFLOW_TRACKING_URI", None)
        else:
            os.environ["MLFLOW_TRACKING_URI"] = previous


def test_the_probe_saw_every_path_at_both_moments(
    captures: dict[str, dict[str, _Capture]],
) -> None:
    """The non-vacuity control: a probe that saw nothing satisfies everything below.

    Every other assertion in this module reads out of ``captures``. If MLflow
    stopped routing a path through the bridged provider — or renamed a span — the
    dictionary lookups would fail, but a sweep written over ``captures.items()``
    would silently pass over an empty mapping. This asserts the subject exists
    before anything asserts a property of it.
    """
    assert sorted(captures) == sorted(_PATHS)
    assert all(sorted(captures[path]) == ["on_end", "on_start"] for path in _PATHS)


@pytest.mark.parametrize("path", _PATHS)
def test_at_on_start_the_span_type_is_not_a_known_mlflow_type(
    path: str, captures: dict[str, dict[str, _Capture]]
) -> None:
    """MLflow sets ``mlflow.spanType`` *after* creating the OpenTelemetry span.

    Which is what makes ``on_start`` the moment where a span's type is not yet
    knowable. A release that started setting it at creation would make this red,
    and reopening plan 03-01's checkpoint decision is the correct response — the
    ``declared-only`` rule would no longer be the only one that works.
    """
    from revenium_mlflow.tracing.eligibility import KNOWN_MLFLOW_SPAN_TYPES

    at_start = captures[path]["on_start"]
    assert at_start.decoded_span_type not in KNOWN_MLFLOW_SPAN_TYPES, (
        f"{path}: mlflow.spanType decoded to {at_start.decoded_span_type!r} at on_start "
        f"(raw {at_start.raw_span_type!r}). MLflow now types spans at creation time; "
        "plan 03-01's stamp-time decision was measured against a release that did not."
    )


@pytest.mark.parametrize("path", _PATHS)
def test_the_same_span_is_wrong_type_at_start_and_admitted_at_end(
    path: str, captures: dict[str, dict[str, _Capture]]
) -> None:
    """The contradiction, as an assertion: one span, two verdicts, one lifetime.

    This is the whole reason ``on_start`` cannot gate on ``classify_span``. Both
    halves are asserted together, on the same span, because either alone is
    satisfiable by an MLflow that classified nothing or everything.
    """
    at_start = captures[path]["on_start"]
    at_end = captures[path]["on_end"]
    assert (at_start.verdict, at_end.verdict) == (
        EligibilityReason.WRONG_TYPE,
        EligibilityReason.ADMITTED,
    ), (
        f"{path}: verdicts were {at_start.verdict.value} at on_start and "
        f"{at_end.verdict.value} at on_end; plan 03-01 measured WRONG_TYPE then ADMITTED. "
        f"Raw mlflow.spanType was {at_start.raw_span_type!r} then {at_end.raw_span_type!r}."
    )


def test_the_verification_document_records_what_the_probe_just_measured(
    captures: dict[str, dict[str, _Capture]],
) -> None:
    """The transcript in ``docs/verification/`` and the live measurement stay one fact.

    This project's evidence constraint requires command output behind a claim,
    and ``docs/verification/attr-02-stamp-time.md`` carries it. A checked-in
    transcript rots the moment someone upgrades MLflow, and a rotted transcript
    is worse than none: it reads as current evidence for a measurement nobody
    re-ran. The same circularity is handled the same way in
    ``tests/unit/test_semconv_cache_tokens.py`` and
    ``docs/verification/sem-05-cache-token-ab.md``.

    Whitespace is collapsed on both sides before comparison. The document's table
    is column-aligned for a human reader, and the alignment is not the fact — the
    six ``when``/``path``/``spanType``/``verdict`` tuples are.
    """
    import mlflow

    document = _EVIDENCE_DOCUMENT.read_text(encoding="utf-8")
    collapsed = " ".join(document.split())

    assert mlflow.__version__ in document, (
        f"{_EVIDENCE_DOCUMENT.name} does not name the installed MLflow "
        f"({mlflow.__version__}); the transcript in it was produced against something else."
    )

    missing = [
        line
        for line in (
            f"{when} {path} {captures[path][when].raw_span_type!r} "
            f"{captures[path][when].verdict.value}"
            for path in _PATHS
            for when in ("on_start", "on_end")
        )
        if line not in collapsed
    ]
    assert missing == [], (
        f"{_EVIDENCE_DOCUMENT.name} no longer records what the probe measured. "
        f"Absent from it: {missing}. Re-run the reproducer in its section 2 and paste "
        "the new output, rather than editing the table by hand."
    )


@pytest.mark.parametrize("path", _PATHS)
def test_at_on_end_the_span_carries_the_type_it_was_created_with(
    path: str, captures: dict[str, dict[str, _Capture]]
) -> None:
    """By ``on_end`` the type has arrived, JSON-encoded, as the wire form.

    Asserted separately from the verdict pair above because it pins *why* the
    verdict changes. A future release could keep the verdicts moving from
    ``WRONG_TYPE`` to ``ADMITTED`` for some entirely different reason — a change
    in how token evidence is reported, say — and the pair assertion would not
    notice.
    """
    at_end = captures[path]["on_end"]
    assert at_end.decoded_span_type == "CHAT_MODEL"
    assert at_end.raw_span_type == '"CHAT_MODEL"'
