"""The billing gate, asserted type by type and token shape by token shape.

This file exists to catch three specific drifts, each of which is a wrong
invoice rather than a crash:

*Vocabulary drift.* The admit/reject verdict for each of MLflow's fifteen span
types is written here as a **literal**, deliberately not imported from
``eligibility``. A test that read :data:`BILLABLE_MLFLOW_SPAN_TYPES` and compared
the predicate against it would agree with every future edit to that allowlist —
and that edit is precisely the one that must not pass unnoticed. The fifteen
*names* are cross-checked against ``KNOWN_MLFLOW_SPAN_TYPES``, which is a
completeness guard rather than a view of the decision: it fails if a type loses
its row, while the verdict on each row stays an independent copy.

*Gate drift.* The token-evidence gate is where a weak test looks identical to a
strong one, so every shape is enumerated: usage absent, usage empty, every field
zero, ``total_tokens`` only, a ``bool``, a ``str``, a ``float``, and each of the
four single-positive-count admissions including the cache-only case with neither
an input nor an output count present.

*Reason drift.* Every rejection asserts the :class:`EligibilityReason` member,
never only the boolean. A test that checks ``False`` cannot distinguish "rejected
for the right reason" from "rejected because the fixture was malformed in some
other way", and D-10 exists to make exactly that difference visible.

**The drift test lives elsewhere.** ``tests/unit/test_mlflow_vocabulary_drift.py``
is the file that goes red if MLflow ships a real sixteenth span type. Nothing
here imports MLflow, and the invented type below is deliberately absurd so the
two files can never be confused for one another.
"""

import collections
import json

import pytest

from revenium_mlflow.tracing.eligibility import (
    KNOWN_MLFLOW_SPAN_TYPES,
    EligibilityReason,
    classify_span,
    is_billable_llm_span,
)
from tests.fixtures.spans import (
    build_readable_span,
    genai_operation_span,
    mlflow_typed_span,
    orchestration_span,
)

pytestmark = pytest.mark.unit

#: Integer nanoseconds for the handful of shapes built directly from
#: :func:`build_readable_span`. ``tests/fixtures/spans.py`` is plan 02-01's and is
#: imported unmodified here; its own docstring says a shape too narrow to earn a
#: named helper is built at the call site rather than by adding a ninth helper,
#: and "a span with no attributes at all" is exactly that shape.
_START_NS = 1788633658640045000
_END_NS = 1788633658686025000

#: The billing decision for each of MLflow's fifteen span types, written out.
#: Three admitted, twelve rejected. This is the assertion's whole value: an
#: independent copy of the decision, not a view of the module under test.
_SPAN_TYPE_VERDICTS: tuple[tuple[str, EligibilityReason], ...] = (
    ("AGENT", EligibilityReason.WRONG_TYPE),
    ("CHAIN", EligibilityReason.WRONG_TYPE),
    ("CHAT_MODEL", EligibilityReason.ADMITTED),
    ("EMBEDDING", EligibilityReason.ADMITTED),
    ("EVALUATOR", EligibilityReason.WRONG_TYPE),
    ("GUARDRAIL", EligibilityReason.WRONG_TYPE),
    ("LLM", EligibilityReason.ADMITTED),
    ("MEMORY", EligibilityReason.WRONG_TYPE),
    ("PARSER", EligibilityReason.WRONG_TYPE),
    ("RERANKER", EligibilityReason.WRONG_TYPE),
    ("RETRIEVER", EligibilityReason.WRONG_TYPE),
    ("TASK", EligibilityReason.WRONG_TYPE),
    ("TOOL", EligibilityReason.WRONG_TYPE),
    ("UNKNOWN", EligibilityReason.WRONG_TYPE),
    ("WORKFLOW", EligibilityReason.WRONG_TYPE),
)

#: Deliberately absurd. An unknown span type must default to rejected, and a
#: plausible-sounding name would let a reader mistake this for the drift test in
#: ``test_mlflow_vocabulary_drift.py`` — the one that fires when MLflow ships a
#: real sixteenth type. A test whose purpose is misread is a test that gets
#: deleted in the wrong direction.
_INVENTED_SPAN_TYPE = "QUANTUM_ORACLE"


def _mlflow_span_without_usage(*, span_type: str = "CHAT_MODEL"):
    """An MLflow-shaped span carrying no ``mlflow.chat.tokenUsage`` at all.

    Built at the call site with ``json.dumps``, because
    :func:`build_readable_span` stores attributes verbatim and encodes nothing —
    the split ``tests/fixtures/spans.py`` documents, so a Path A span can carry
    bare OpenTelemetry attributes through the same builder.
    """
    return build_readable_span(
        attributes={
            "mlflow.spanType": json.dumps(span_type),
            "mlflow.llm.model": json.dumps("gpt-4o"),
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )


# --- The fifteen-row table -------------------------------------------------


@pytest.mark.parametrize(("span_type", "expected"), _SPAN_TYPE_VERDICTS)
def test_the_span_type_table_verdict_is_exact(span_type: str, expected: EligibilityReason) -> None:
    """Each MLflow span type, paired with token evidence sufficient to admit it."""
    assert classify_span(mlflow_typed_span(span_type=span_type)) is expected


def test_the_span_type_table_covers_every_type_mlflow_declares() -> None:
    """A type that loses its row would otherwise go unjudged rather than red."""
    assert {span_type for span_type, _ in _SPAN_TYPE_VERDICTS} == set(KNOWN_MLFLOW_SPAN_TYPES)


def test_the_span_type_table_admits_three_and_rejects_twelve() -> None:
    """Prints the whole table, so the shape is read rather than inferred."""
    verdicts = [
        (span_type, classify_span(mlflow_typed_span(span_type=span_type)))
        for span_type, _ in _SPAN_TYPE_VERDICTS
    ]
    print("\n" + "\n".join(f"  {name:<12} {verdict.value}" for name, verdict in verdicts))
    assert collections.Counter(verdict.value for _, verdict in verdicts) == {
        "WRONG_TYPE": 12,
        "ADMITTED": 3,
    }


# --- The sixteenth type this repository invented ---------------------------


def test_an_invented_span_type_defaults_to_rejected() -> None:
    """Membership in a positive frozenset: unknown is rejected structurally."""
    span = mlflow_typed_span(span_type=_INVENTED_SPAN_TYPE)
    assert classify_span(span) is EligibilityReason.WRONG_TYPE


def test_the_invented_span_type_is_not_one_mlflow_declares() -> None:
    """If MLflow ever ships this name, the case above stops testing anything."""
    assert _INVENTED_SPAN_TYPE not in KNOWN_MLFLOW_SPAN_TYPES


# --- Type is decided before tokens are read (SEM-11) -----------------------


@pytest.mark.parametrize("span_type", ["RETRIEVER", "CHAIN", "TOOL", "AGENT"])
def test_an_orchestration_span_carrying_tokens_is_rejected_on_its_type(span_type: str) -> None:
    """A thousand input tokens on a CHAIN span is still WRONG_TYPE, not evidence."""
    span = orchestration_span(span_type=span_type, usage={"input_tokens": 1000})
    assert classify_span(span) is EligibilityReason.WRONG_TYPE


# --- The two empty inputs, which must stay distinguishable -----------------


def test_a_span_with_no_attributes_at_all_is_the_wrong_type() -> None:
    """No type to read is not a missing-token problem; collapsing the two loses D-10."""
    span = build_readable_span(attributes={}, start_time_ns=_START_NS, end_time_ns=_END_NS)
    assert classify_span(span) is EligibilityReason.WRONG_TYPE


def test_an_allowlisted_span_with_an_empty_usage_mapping_has_no_token_evidence() -> None:
    """The other empty input, and it reports a different reason on purpose."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


# --- The token-evidence gate, every shape ----------------------------------


def test_an_allowlisted_span_with_no_usage_attribute_has_no_token_evidence() -> None:
    """Absent, as opposed to present-and-empty. Both are rejected, neither crashes."""
    assert classify_span(_mlflow_span_without_usage()) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_usage_reporting_zero_on_every_field_has_no_token_evidence() -> None:
    """Zero everywhere is no evidence of work, not a zero-cost completion (D-11)."""
    span = mlflow_typed_span(
        span_type="CHAT_MODEL",
        usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_tokens": 0,
        },
    )
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_a_positive_total_tokens_alone_is_not_token_evidence() -> None:
    """``total_tokens`` is derived; admitting on it weakens a one-way door for nothing."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={"total_tokens": 1050})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_a_boolean_where_a_count_belongs_is_not_token_evidence() -> None:
    """``isinstance(True, int)`` is ``True`` in Python; ``bool`` is excluded first."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={"input_tokens": True})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_a_string_where_a_count_belongs_is_not_token_evidence() -> None:
    """A count that arrived as text is a count nobody measured."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={"input_tokens": "1000"})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_a_float_where_a_count_belongs_is_not_token_evidence() -> None:
    """Tokens are counted, never measured; a float is a different kind of number."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={"input_tokens": 1000.0})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ],
)
def test_one_positive_count_on_its_own_admits_the_span(field: str) -> None:
    """Each of the four fields is evidence alone — the cache pair included (D-12)."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={field: 900})
    assert classify_span(span) is EligibilityReason.ADMITTED


def test_a_flat_cache_read_count_admits_a_path_a_span_on_its_own() -> None:
    """The same rule in the ``gen_ai.usage.*`` spelling, with no input or output count."""
    span = build_readable_span(
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.cache_read_input_tokens": 900,
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )
    assert classify_span(span) is EligibilityReason.ADMITTED


# --- Exact-match comparison, with no tidying anywhere in it ----------------


@pytest.mark.parametrize("span_type", ["chat_model", " CHAT_MODEL", "CHAT_MODEL "])
def test_a_near_miss_span_type_is_rejected(span_type: str) -> None:
    """No case folding, no strip, no normalization: equality is the whole rule."""
    assert classify_span(mlflow_typed_span(span_type=span_type)) is EligibilityReason.WRONG_TYPE


# --- Path A, and its precedence over Path B --------------------------------


def test_a_bridged_chat_operation_is_admitted_with_no_mlflow_span_type() -> None:
    """Path A exists for an instrumentor that never heard of MLflow."""
    assert classify_span(genai_operation_span(operation="chat")) is EligibilityReason.ADMITTED


def test_a_bridged_chat_operation_without_tokens_has_no_token_evidence() -> None:
    """The gate runs on both paths (D-09), not on Path B only."""
    span = genai_operation_span(operation="chat", input_tokens=0, output_tokens=0)
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


@pytest.mark.parametrize("operation", ["execute_tool", "invoke_agent"])
def test_a_non_billable_operation_overrides_an_allowlisted_span_type(operation: str) -> None:
    """Path A decides first, so the weaker signal cannot overturn the stronger one."""
    span = build_readable_span(
        attributes={
            "gen_ai.operation.name": operation,
            "gen_ai.usage.input_tokens": 1000,
            "mlflow.spanType": json.dumps("CHAT_MODEL"),
        },
        start_time_ns=_START_NS,
        end_time_ns=_END_NS,
    )
    assert classify_span(span) is EligibilityReason.WRONG_TYPE


# --- The reason vocabulary, and the boolean that reads it ------------------


def test_the_reason_vocabulary_has_exactly_three_members() -> None:
    """Three reasons, no more: D-10's counter keys are a closed set."""
    assert sorted(member.name for member in EligibilityReason) == [
        "ADMITTED",
        "NO_TOKEN_EVIDENCE",
        "WRONG_TYPE",
    ]


def test_every_reason_value_equals_its_name() -> None:
    """A ``str``-valued enum, printable and usable as a dict key unconverted."""
    assert all(member.value == member.name for member in EligibilityReason)


def test_the_known_vocabulary_holds_fifteen_members() -> None:
    """MLflow declares fifteen span types; a sixteenth is a billing decision."""
    assert len(KNOWN_MLFLOW_SPAN_TYPES) == 15


@pytest.mark.parametrize(
    "shape",
    [
        "admitted_chat_model",
        "wrong_type_chain",
        "no_token_evidence_empty_usage",
        "invented_type",
        "bridged_chat",
    ],
)
def test_the_boolean_agrees_with_the_reason(shape: str) -> None:
    """``is_billable_llm_span`` is the identity comparison, not a second predicate."""
    spans = {
        "admitted_chat_model": lambda: mlflow_typed_span(span_type="CHAT_MODEL"),
        "wrong_type_chain": lambda: orchestration_span(span_type="CHAIN"),
        "no_token_evidence_empty_usage": lambda: mlflow_typed_span(
            span_type="CHAT_MODEL", usage={}
        ),
        "invented_type": lambda: mlflow_typed_span(span_type=_INVENTED_SPAN_TYPE),
        "bridged_chat": lambda: genai_operation_span(operation="chat"),
    }
    span = spans[shape]()
    assert is_billable_llm_span(span) is (classify_span(span) is EligibilityReason.ADMITTED)
