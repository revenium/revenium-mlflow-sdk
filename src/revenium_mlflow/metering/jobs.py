"""Job outcomes: ``report_job_outcome``, with the billing tenant made explicit.

Phase 5 (JOB-01 through JOB-06) implements this. Phase 1 fixes the signature,
and two of its parameters are decisions rather than fields.

**``billing_team_id`` is required and is never inferred (JOB-06).** The house
Revenium SDK guesses the team from the API-key prefix and warns, in three
separate branches, that outcomes "may target the wrong team". That is a warning
about money moving to the wrong tenant, printed into a log nobody reads. Making
the tenant an ordinary required parameter removes the inference entirely: there
is no fallback path to get wrong, and a key rotation cannot silently re-tenant a
customer's traffic. The cost is one more argument at the call site. The
alternative cost is an invoice that is wrong in a way no error message points at.

**``agentic_job_id`` is supplied by the caller, never generated here (JOB-01).**
The outcome has to correlate with spans emitted earlier, possibly in another
process. An identifier minted inside this function would correlate with nothing.

**``outcome_reason`` is a field, not a metadata key (JOB-03).** Failure and
cancellation reasons belong in the documented outcome-reason field. Stuffed into
free-form metadata they are invisible to the rating side, which is the same
class of silent loss a misspelled attribution key produces.
"""

from collections.abc import Mapping

__all__ = ["report_job_outcome"]

_PHASE_5 = (
    "not implemented until Phase 5 (Tool Metering and Job Outcomes). "
    "Phase 1 publishes this signature so callers and type checkers can be "
    "written against it; it raises rather than reporting nothing quietly, "
    "because a job outcome that is silently dropped leaves the job looking "
    "unfinished forever and its ROI uncomputable."
)


def report_job_outcome(
    *,
    agentic_job_id: str,
    billing_team_id: str,
    status: str,
    business_outcome: str | None = None,
    outcome_value: float | None = None,
    currency: str | None = None,
    outcome_reason: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> None:
    """Report the terminal outcome of an agentic job (JOB-01 through JOB-03).

    Requires a write-scope credential (``rev_sk_``). Phase 5 checks the scope
    locally and raises
    :class:`~revenium_mlflow.errors.CredentialScopeError` **before** the HTTP
    call (JOB-05), because a metering key sent to a write endpoint earns a
    remote rejection whose message says nothing about scope.

    Args:
        agentic_job_id: The externally supplied job identifier the outcome
            correlates on. Required, and never generated here.
        billing_team_id: The Revenium billing tenant. Required, and never
            inferred from the API-key prefix.
        status: The terminal execution status of the job.
        business_outcome: The business result the job achieved.
        outcome_value: The monetary or numeric value of that result.
        currency: The currency ``outcome_value`` is denominated in.
        outcome_reason: Why the job failed or was cancelled. The documented
            field for this, not a metadata key.
        metadata: Free-form additional detail carried on the outcome.

    Raises:
        NotImplementedError: Always, in Phase 1.
    """
    raise NotImplementedError(f"report_job_outcome() is {_PHASE_5}")
