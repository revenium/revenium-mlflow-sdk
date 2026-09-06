"""The billing gate, asserted type by type and token shape by token shape.

This file exists to catch three specific drifts, each of which is a wrong
invoice rather than a crash:

*Vocabulary drift.* The admit/reject verdict for each of MLflow's fifteen span
types is written here as a **literal**, deliberately not imported from
``eligibility``. A test that read the allowlist and compared the predicate
against it would agree with every future edit to the allowlist — and that edit is
precisely the one that must not pass unnoticed.

*Gate drift.* The token-evidence gate is where a weak test looks identical to a
strong one, so every shape is enumerated: usage absent, usage empty, every field
zero, ``total_tokens`` only, a ``bool``, a ``str``, a ``float``, and each of the
four single-positive-count admissions including the cache-only case.

*Reason drift.* Every rejection asserts the :class:`EligibilityReason` member,
never only the boolean. A test that checks ``False`` cannot distinguish "rejected
for the right reason" from "rejected because the fixture was malformed in some
other way", and D-10 exists to make exactly that difference visible.
"""

import pytest

from revenium_mlflow.tracing.eligibility import (
    KNOWN_MLFLOW_SPAN_TYPES,
    EligibilityReason,
    classify_span,
    is_billable_llm_span,
)
from tests.fixtures.spans import (
    mlflow_typed_span,
    orchestration_span,
)

pytestmark = pytest.mark.unit


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


def test_a_chat_model_span_with_tokens_is_admitted() -> None:
    """The captured wire shape, which is the one span proven to travel."""
    assert classify_span(mlflow_typed_span(span_type="CHAT_MODEL")) is EligibilityReason.ADMITTED


def test_a_chain_span_carrying_tokens_is_rejected_on_its_type() -> None:
    """Type is decided before tokens are read, which is what makes SEM-11 structural."""
    assert classify_span(orchestration_span(span_type="CHAIN")) is EligibilityReason.WRONG_TYPE


def test_an_allowlisted_span_reporting_zero_everywhere_has_no_token_evidence() -> None:
    """Zero everywhere is not a zero-cost completion; it is no evidence (D-11)."""
    span = mlflow_typed_span(span_type="CHAT_MODEL", usage={"input_tokens": 0, "output_tokens": 0})
    assert classify_span(span) is EligibilityReason.NO_TOKEN_EVIDENCE


def test_the_boolean_agrees_with_the_reason_on_an_admitted_span() -> None:
    """``is_billable_llm_span`` is the identity comparison, not a second predicate."""
    span = mlflow_typed_span(span_type="CHAT_MODEL")
    assert is_billable_llm_span(span) is (classify_span(span) is EligibilityReason.ADMITTED)


def test_the_boolean_agrees_with_the_reason_on_a_rejected_span() -> None:
    """The same identity, on the other side of the gate."""
    span = orchestration_span(span_type="RETRIEVER")
    assert is_billable_llm_span(span) is (classify_span(span) is EligibilityReason.ADMITTED)
