"""The SDK's billing vocabulary, pinned to MLflow's own tables.

These four assertions are the only tests in this phase whose result can differ
between MLflow 3.15.0 and 3.16.0-plus, which is what makes VER-07's four-leg
version matrix earn its cost. They are ``unit``-marked and need no service, so
``scripts/version_matrix.sh`` picks them up unchanged with no edit to that
script.

**D-06: a red build, never a report.** If MLflow ships a sixteenth span type, or
moves a row of ``_OPERATION_TO_SPAN_KIND``, that is a billing decision nobody has
made yet. Failing is what forces someone to make it. Every assertion below
therefore carries a failure message computed from the *symmetric difference*, so
a red run names the member that drifted — a bare ``assert a == b`` over two
fifteen-member frozensets prints an unreadable diff and gets the test deleted
rather than acted on.

**C1 — the correction to D-08, stated here so this file does not read as a
deviation.** D-08 as written requires that every MLflow type the SDK admits maps
to an operation it admits *and vice versa*, anchored to
``_SPAN_TYPE_TO_OPERATION``. That test cannot pass on any MLflow release. The
operation allowlist contains ``text_completion``; the values of
``_SPAN_TYPE_TO_OPERATION`` are ``chat``, ``generate_content``, ``embeddings``,
``execute_tool`` and ``invoke_agent`` — ``text_completion`` appears nowhere in
that table. Written literally, the only way to make the "vice versa" half pass is
to delete ``text_completion`` from the allowlist, which would silently narrow the
Path A predicate that exists for bridged non-MLflow instrumentors.

The anchor moves to the ``SpanKind.CLIENT``-valued keys of
``_OPERATION_TO_SPAN_KIND``, which are **set-equal** to the allowlist at both
3.15.0 and 3.16.0. That fixes the test and is strictly better than the original:
it additionally anchors SEM-12 to the same table, so "every admitted span is
emitted as ``SpanKind.CLIENT``" stops being an independent rule to keep in sync
and becomes a consequence of one table. D-08's intent — tie the two vocabularies
to each other rather than to the OpenTelemetry semconv package's stability across
the ``>=1.30.0`` floor — is preserved exactly.

**Every MLflow import is inside a test function body, and none at module scope.**
``tests/conftest.py`` lines 15-24 silences MLflow's outbound telemetry from a
session-scoped autouse fixture, and its own comment records the condition that
makes it work: nothing imports MLflow at module scope. pytest imports every test
module during *collection*, and collection finishes before any session-scoped
fixture runs — so a module-scope import here would make an outbound MLflow
telemetry call on every run of the entire suite, before the guard is in place, in
a project whose PROJECT.md forbids network calls to any hosted endpoint during
development or testing. The ``opentelemetry`` import may stay at module scope;
only the MLflow ones move.

**The SDK's own imports moved with them, and not for the same reason.** The
check that enforces the rule above walks this module's top-level statements and
reports any whose source mentions ``mlflow``. ``revenium_mlflow`` contains that
substring, so a module-scope ``from revenium_mlflow.tracing.eligibility import
...`` trips it. The two available fixes were to loosen the check to a word-
boundary match or to move these four imports down beside the MLflow ones. The
check was left alone: a probe relaxed until it passes is a probe that stops
reporting, and a module-scope import in this file is exactly what it exists to
find. Do not "tidy" any import in this file back up to the top.

This costs the D-03 signal nothing. A module MLflow has moved still raises
``ImportError`` from a function body — loudly, in the test that needs it, naming
the module — so the no-``importorskip``, no-``try``/``except`` rule holds exactly
as written; the error simply arrives at call time instead of at collection time.

``_OPERATION_TO_SPAN_KIND``, ``_SPAN_TYPE_TO_OPERATION`` and ``SpanType`` are
private or banned in shipped code. They are legal here under
``[tool.ruff.lint.per-file-ignores] "tests/**" = ["SLF", "TID"]``, which is
OI-01's scope split: VER-08 bans private access in the shipped package, and test
code may use private APIs freely. No third per-file-ignore was added for this
file — plan 01-03 asserts the exemption count is exactly two.
"""

import pytest
from opentelemetry.trace import SpanKind

pytestmark = pytest.mark.unit


def _drift(label: str, ours: frozenset[str] | set[str], theirs: set[str]) -> str:
    """The failure message: which member drifted, and in which direction.

    Pure string formatting, and deliberately so — it imports nothing, so
    factoring it out cannot reintroduce the module-scope MLflow import the
    docstring above forbids.
    """
    return (
        f"{label} no longer matches MLflow's own table. "
        f"MLflow declares and the SDK does not: {sorted(set(theirs) - set(ours))}. "
        f"The SDK declares and MLflow does not: {sorted(set(ours) - set(theirs))}."
    )


def test_the_operation_allowlist_is_mlflows_client_kind_operations() -> None:
    """A failure means MLflow reclassified an operation between CLIENT and INTERNAL."""
    # The import lives here, not at the top of the file: pytest's collection pass
    # runs before conftest.py's session-scoped telemetry guard, so a module-scope
    # MLflow import would make an outbound call on every run of the whole suite.
    # A moved module still raises ImportError from here, one line later, which is
    # the same loud signal D-03 asks for.
    from mlflow.tracing.export.genai_semconv.translator import _OPERATION_TO_SPAN_KIND

    from revenium_mlflow.tracing.eligibility import BILLABLE_GENAI_OPERATIONS

    client_operations = {
        operation for operation, kind in _OPERATION_TO_SPAN_KIND.items() if kind is SpanKind.CLIENT
    }
    assert set(BILLABLE_GENAI_OPERATIONS) == client_operations, _drift(
        "BILLABLE_GENAI_OPERATIONS", BILLABLE_GENAI_OPERATIONS, client_operations
    )


def test_the_span_type_allowlist_is_the_types_mapping_to_a_billable_operation() -> None:
    """A failure means MLflow re-pointed a span type at a different operation."""
    from mlflow.tracing.export.genai_semconv.translator import _SPAN_TYPE_TO_OPERATION

    from revenium_mlflow.tracing.eligibility import (
        BILLABLE_GENAI_OPERATIONS,
        BILLABLE_MLFLOW_SPAN_TYPES,
    )

    billable_types = {
        span_type
        for span_type, operation in _SPAN_TYPE_TO_OPERATION.items()
        if operation in BILLABLE_GENAI_OPERATIONS
    }
    assert set(BILLABLE_MLFLOW_SPAN_TYPES) == billable_types, _drift(
        "BILLABLE_MLFLOW_SPAN_TYPES", BILLABLE_MLFLOW_SPAN_TYPES, billable_types
    )


def test_the_path_b_operation_table_is_mlflows_table_restricted() -> None:
    """A failure means the SDK's Path B mapping has become a second hand-written copy."""
    from mlflow.tracing.export.genai_semconv.translator import _SPAN_TYPE_TO_OPERATION

    from revenium_mlflow.tracing.eligibility import BILLABLE_GENAI_OPERATIONS
    from revenium_mlflow.tracing.semconv import SPAN_TYPE_TO_OPERATION

    restricted = {
        span_type: operation
        for span_type, operation in _SPAN_TYPE_TO_OPERATION.items()
        if operation in BILLABLE_GENAI_OPERATIONS
    }
    assert dict(SPAN_TYPE_TO_OPERATION) == restricted, _drift(
        "SPAN_TYPE_TO_OPERATION",
        {f"{k}->{v}" for k, v in SPAN_TYPE_TO_OPERATION.items()},
        {f"{k}->{v}" for k, v in restricted.items()},
    )


def test_the_known_vocabulary_is_every_span_type_mlflow_declares() -> None:
    """A failure names the sixteenth span type MLflow shipped, which is the point (D-06)."""
    from mlflow.entities.span import SpanType

    from revenium_mlflow.tracing.eligibility import KNOWN_MLFLOW_SPAN_TYPES

    # ``SpanType`` is a plain class, not an Enum: ``isinstance(SpanType,
    # enum.EnumMeta)`` is False and it has no ``__members__``, so an Enum-shaped
    # enumeration would raise. ``dir()`` would sweep in inherited object
    # attributes, so ``vars()`` filtered on a leading underscore and ``str`` is
    # the only correct enumeration.
    declared = {
        value
        for name, value in vars(SpanType).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert set(KNOWN_MLFLOW_SPAN_TYPES) == declared, _drift(
        "KNOWN_MLFLOW_SPAN_TYPES", KNOWN_MLFLOW_SPAN_TYPES, declared
    )
