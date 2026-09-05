"""The ``revenium.*`` attribution keys, as constants, with the backend's caps.

**This module is data only.** It defines no behaviour, validates nothing, and
touches neither MLflow nor the network. The client-side validation that consumes
:data:`ATTRIBUTE_CAPS` is ATTR-09 and lands in Phase 3; it is deliberately absent
here so that the contract and the enforcement of the contract can be reviewed
separately.

Why the keys are exported at all (D-02). Revenium's ingest silently **drops**
attribute values it does not recognize, and silently drops values that exceed a
column's cap rather than truncating them (``ReveniumAttributes.kt``). A
misspelled key and an oversized identifier therefore both vanish with no error
on either side: the trace still exports, the request still succeeds, and the
attribution the customer is billed against is quietly wrong. Naming every key as
an importable constant converts the misspelling half of that into an
``AttributeError`` at author time, where it costs nothing.

Why the caps are exported as data rather than applied here. A cap that is
enforced in one place and published in another drifts. Publishing the table is
also what lets a caller check a value before handing it over, which matters
because "dropped" and "accepted" are indistinguishable from the client side.

Constant names derive from their keys by one mechanical rule — take the dotted
suffix, uppercase it, replace dots with underscores, prefix ``REVENIUM_`` — so
``revenium.subscriber.email`` is :data:`REVENIUM_SUBSCRIBER_EMAIL` and nothing
has to be looked up. That rule is load-bearing rather than cosmetic: plan 01-05
turns these same 21 names into the 21 explicit keyword parameters of
``attribution()`` (D-03), and ``tests/unit/test_attributes.py`` asserts the
mapping in both directions so a hand-named constant cannot become a hand-named
parameter.

Six further attributes the backend also recognizes — ``revenium.ticket.id``,
``revenium.model.host``, ``revenium.subscriber.email.source``,
``revenium.system.fingerprint``, ``revenium.subscription_tier`` and
``revenium.subscriber.credential.{name,value}`` — are V2-03 and are absent on
purpose. Under D-03 each one is a new keyword parameter, so adding them is a
signature change to make when something can populate them.
"""

import types
from collections.abc import Mapping
from typing import Final

__all__ = [
    "ATTRIBUTE_CAPS",
    "REVENIUM_AGENT_NAME",
    "REVENIUM_ATTRIBUTE_KEYS",
    "REVENIUM_JOB_ID",
    "REVENIUM_JOB_NAME",
    "REVENIUM_JOB_TYPE",
    "REVENIUM_JOB_VERSION",
    "REVENIUM_MIDDLEWARE_SOURCE",
    "REVENIUM_OPERATION_SUBTYPE",
    "REVENIUM_ORGANIZATION_NAME",
    "REVENIUM_PRODUCT_NAME",
    "REVENIUM_REQUEST_STREAM",
    "REVENIUM_RETRY_NUMBER",
    "REVENIUM_SQUAD_ID",
    "REVENIUM_SQUAD_NAME",
    "REVENIUM_SQUAD_ROLE",
    "REVENIUM_SUBSCRIBER_EMAIL",
    "REVENIUM_SUBSCRIBER_ID",
    "REVENIUM_SUBSCRIPTION_ID",
    "REVENIUM_TASK_TYPE",
    "REVENIUM_TRACE_NAME",
    "REVENIUM_TRACE_TYPE",
    "REVENIUM_TRANSACTION_NAME",
]

# --- Billing tenancy -------------------------------------------------------

#: The Revenium organization the traffic is attributed to.
REVENIUM_ORGANIZATION_NAME: Final[str] = "revenium.organization.name"

#: The product the traffic is attributed to.
REVENIUM_PRODUCT_NAME: Final[str] = "revenium.product.name"

#: The subscription the traffic is rated under.
REVENIUM_SUBSCRIPTION_ID: Final[str] = "revenium.subscription.id"

#: The end subscriber the traffic is attributed to.
REVENIUM_SUBSCRIBER_ID: Final[str] = "revenium.subscriber.id"

#: The subscriber's email address. Personal data — never logged unredacted.
REVENIUM_SUBSCRIBER_EMAIL: Final[str] = "revenium.subscriber.email"

# --- Workload shape --------------------------------------------------------

#: The agent that issued the call.
REVENIUM_AGENT_NAME: Final[str] = "revenium.agent.name"

#: The class of task being performed. Capped at 255 by the backend.
REVENIUM_TASK_TYPE: Final[str] = "revenium.task.type"

#: The class of trace. Capped at 128 by the backend.
REVENIUM_TRACE_TYPE: Final[str] = "revenium.trace.type"

#: The human-readable trace name. Capped at 256 by the backend.
REVENIUM_TRACE_NAME: Final[str] = "revenium.trace.name"

#: The logical transaction the call belongs to.
REVENIUM_TRANSACTION_NAME: Final[str] = "revenium.transaction.name"

# --- Job correlation -------------------------------------------------------

#: The agentic job identifier. Capped at 256 by the backend. Job outcomes
#: correlate on this value, which is supplied externally rather than generated
#: here (JOB-01).
REVENIUM_JOB_ID: Final[str] = "revenium.job.id"

#: The job's human-readable name. Capped at 512 by the backend.
REVENIUM_JOB_NAME: Final[str] = "revenium.job.name"

#: The class of job. Capped at 128 by the backend.
REVENIUM_JOB_TYPE: Final[str] = "revenium.job.type"

#: The job's version. Capped at 64 by the backend.
REVENIUM_JOB_VERSION: Final[str] = "revenium.job.version"

# --- Squad -----------------------------------------------------------------

#: The squad the agent belongs to.
REVENIUM_SQUAD_ID: Final[str] = "revenium.squad.id"

#: The squad's human-readable name.
REVENIUM_SQUAD_NAME: Final[str] = "revenium.squad.name"

#: The agent's role within the squad.
REVENIUM_SQUAD_ROLE: Final[str] = "revenium.squad.role"

# --- Call shape ------------------------------------------------------------

#: A refinement of the operation being metered.
REVENIUM_OPERATION_SUBTYPE: Final[str] = "revenium.operation.subtype"

#: Which retry attempt this call is.
REVENIUM_RETRY_NUMBER: Final[str] = "revenium.retry.number"

#: Whether the request was streamed.
REVENIUM_REQUEST_STREAM: Final[str] = "revenium.request.stream"

#: Which Revenium middleware produced the telemetry. Capped at 255 by the
#: backend. This SDK's value is ``mlflow`` (ATTR-08, Phase 3).
REVENIUM_MIDDLEWARE_SOURCE: Final[str] = "revenium.middleware.source"


#: Every ATTR-07 key, in the order the requirement lists them. The order is
#: stable so a diff on this tuple reads as an addition or a removal rather than
#: as a reshuffle.
REVENIUM_ATTRIBUTE_KEYS: Final[tuple[str, ...]] = (
    REVENIUM_ORGANIZATION_NAME,
    REVENIUM_PRODUCT_NAME,
    REVENIUM_SUBSCRIPTION_ID,
    REVENIUM_SUBSCRIBER_ID,
    REVENIUM_SUBSCRIBER_EMAIL,
    REVENIUM_AGENT_NAME,
    REVENIUM_TASK_TYPE,
    REVENIUM_TRACE_TYPE,
    REVENIUM_TRACE_NAME,
    REVENIUM_TRANSACTION_NAME,
    REVENIUM_JOB_ID,
    REVENIUM_JOB_NAME,
    REVENIUM_JOB_TYPE,
    REVENIUM_JOB_VERSION,
    REVENIUM_SQUAD_ID,
    REVENIUM_SQUAD_NAME,
    REVENIUM_SQUAD_ROLE,
    REVENIUM_OPERATION_SUBTYPE,
    REVENIUM_RETRY_NUMBER,
    REVENIUM_REQUEST_STREAM,
    REVENIUM_MIDDLEWARE_SOURCE,
)

#: The per-column maximum lengths ``ReveniumAttributes.kt`` enforces, for the
#: eight columns that carry one. A value longer than its cap is **dropped**,
#: not truncated, and the request still succeeds — which is why the numbers are
#: published rather than merely enforced somewhere out of sight.
#:
#: Source-verified against the backend repository and recorded in PROJECT.md;
#: not runtime-verified, because this project does not call the hosted route.
#: Exported through :class:`types.MappingProxyType` so a caller cannot widen a
#: cap in their own process and then be surprised when the backend does not
#: agree.
ATTRIBUTE_CAPS: Final[Mapping[str, int]] = types.MappingProxyType(
    {
        REVENIUM_TRACE_NAME: 256,
        REVENIUM_TRACE_TYPE: 128,
        REVENIUM_TASK_TYPE: 255,
        REVENIUM_JOB_ID: 256,
        REVENIUM_JOB_NAME: 512,
        REVENIUM_JOB_TYPE: 128,
        REVENIUM_JOB_VERSION: 64,
        REVENIUM_MIDDLEWARE_SOURCE: 255,
    }
)
