"""``validate_connection()`` and the structured result it returns.

Phase 6 (DIAG-01 through DIAG-04) implements this. Phase 1 fixes the result
*type*, which is the part that matters most here.

**Why the result is a dataclass and not a ``bool`` (DIAG-01).** A diagnostic
that returns ``False`` has told the user that something is wrong and nothing
about what or how to fix it, which leaves them exactly where they started except
now they know to worry. Every field below exists because it answers a question a
user stuck at this point actually asks: *is the route reachable*, *did my key
work*, *which protocol was negotiated*, *what URL did my configuration actually
resolve to*, *did I configure before or after MLflow built its provider*, *where
are my traces going*, and *what do I do about it*.

**Why the status codes are distinguished (DIAG-02).** 200, 401, 403, 404 and a
timeout have four different remedies and one of them is not "check your key".
404 in particular is the signal that the traces route is not deployed in the
environment being tested — a question this project is structurally forbidden to
answer for the user, because it makes no call to Revenium production, any
customer environment, or any hosted write endpoint. Distinguishing the codes is
therefore not a nicety; it is the sanctioned way the user resolves in their own
environment a fact this repository cannot establish in ours.

This module opens no socket and builds no HTTP client, here or at import time.
"""

import dataclasses
from collections.abc import Mapping

from revenium_mlflow.config import ReveniumConfig

__all__ = ["ConnectionDiagnostics", "validate_connection"]

_PHASE_6 = (
    "not implemented until Phase 6 (Production HTTP Behavior and Diagnostics). "
    "Phase 1 publishes this signature and its result type so callers and type "
    "checkers can be written against it; it raises rather than reporting a "
    "healthy-looking result, because a diagnostic that reports health it did "
    "not measure is worse than no diagnostic at all."
)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConnectionDiagnostics:
    """What :func:`validate_connection` found, per check, with remedies.

    Frozen because a diagnostic result is a record of one moment; a mutable one
    invites code that patches a field and passes the result on as though it had
    been measured. Keyword-only because field order must not become a contract
    this record cannot grow past.
    """

    #: Whether the resolved traces endpoint answered at all.
    reachable: bool

    #: The HTTP status observed, or ``None`` when nothing answered — which is
    #: how a timeout is distinguished from a refusal (DIAG-02).
    http_status: int | None

    #: What the credential proved: accepted, rejected, out of scope, or never
    #: presented. Distinct from :attr:`reachable`, because a route that answers
    #: 401 is reachable and unusable at the same time.
    auth_status: str

    #: The OTLP protocol actually negotiated. Always ``http/protobuf`` when
    #: correct; anything else is the ``grpc`` default leaking through.
    protocol: str

    #: The endpoint the configuration actually resolved to, after every
    #: override. Present because "which URL did it really use" is otherwise
    #: unanswerable from outside the process.
    resolved_url: str

    #: Whether configuration ran before MLflow initialised its tracer provider.
    #: Configuring afterwards silently observes nothing (CFG-06), so this is
    #: reported even when every other check is green.
    ordering_status: str

    #: Every destination the traces are being exported to, the customer's own
    #: collector included. The SDK adds a destination; it never replaces one
    #: (CFG-03), and this is where a user confirms that.
    destinations: tuple[str, ...]

    #: Per-check remedy text, keyed by check name. A remedy attached to the
    #: check it belongs to, rather than one summary string, so a partial
    #: failure produces a specific instruction instead of a generic one.
    remedies: Mapping[str, str]


def validate_connection(*, config: ReveniumConfig | None = None) -> ConnectionDiagnostics:
    """Check the Revenium export path and report what was found (DIAG-01).

    Args:
        config: The configuration to validate. When ``None``, Phase 6 resolves
            one the same way :func:`~revenium_mlflow.configure_tracing`
            does, so the diagnostic describes what would actually be installed
            rather than a second, differently-resolved configuration.

    Returns:
        A :class:`ConnectionDiagnostics` — never a bare ``bool``.

    Raises:
        NotImplementedError: Always, in Phase 1.
    """
    raise NotImplementedError(f"validate_connection() is {_PHASE_6}")
