"""The exception hierarchy this SDK raises.

Everything raised deliberately by ``revenium_mlflow`` descends from
:class:`ReveniumMLflowError`, so an application that wants to treat "the
telemetry side-car had a problem" as one case can catch one name. Callers that
need to distinguish causes catch the subclasses instead.

This module imports nothing outside the standard library and is safe to import
at any point, including from the package ``__init__``.
"""

__all__ = [
    "ConfigurationError",
    "CredentialScopeError",
    "ExportError",
    "OrderingError",
    "ReveniumMLflowError",
    "UnsupportedMLflowError",
]


class ReveniumMLflowError(Exception):
    """Root of every exception this SDK raises on purpose.

    Catching this catches configuration failures, capability failures, and
    export failures alike, without catching unrelated bugs from MLflow, from
    OpenTelemetry, or from the application itself.
    """


class UnsupportedMLflowError(ReveniumMLflowError):
    """The installed MLflow does not provide a capability this SDK requires.

    Raised by :func:`revenium_mlflow._compat.probe` at configure time, never at
    import time. The message names the missing capability, the observed version
    and the remedy, because the alternative — degrading into a state where some
    telemetry is emitted and some is silently dropped — produces an invoice that
    is quietly wrong rather than an error that is loudly right.
    """


class ConfigurationError(ReveniumMLflowError):
    """The supplied configuration is malformed, incomplete, or self-contradictory.

    Raised by the resolution and validation behaviour of Phase 4 (CFG-08,
    EXP-05) — a missing billing tenant, an endpoint that cannot be normalised,
    a protocol that is not ``http/protobuf``. The type exists in Phase 1 with
    nothing raising it yet because :mod:`revenium_mlflow.config` is published
    now and a caller writing ``except`` against it should not have to wait for
    the phase that fills it in.
    """


class CredentialScopeError(ReveniumMLflowError):
    """A metering-scope credential was used where a write-scope one is required.

    Raised by Phase 5 (JOB-05), before the HTTP call rather than after it: a
    ``rev_mk_`` key sent to a write endpoint earns a remote rejection whose
    message says nothing about scope, so the check is worth doing locally where
    the two field names are in view. The scope split itself is an inherited
    design decision recorded on :class:`revenium_mlflow.config.ReveniumConfig`,
    not a defect to route around.
    """


class ExportError(ReveniumMLflowError):
    """Telemetry could not be exported, or was exported and rejected.

    Raised by Phase 4 (EXP-04). OpenTelemetry's ``BatchSpanProcessor`` discards
    ``SpanExportResult.FAILURE`` without telling anyone, so a 401 from Revenium
    reaches no caller and the operator's first evidence is an invoice that is
    missing traffic. This type is how that failure is given somewhere to go.
    """


class OrderingError(ReveniumMLflowError):
    """Configuration was attempted after the tracer provider was already initialised.

    Raised by Phase 4 (CFG-06). Attribution must be written in ``on_start``, and
    a processor attached after MLflow has built and frozen its provider observes
    nothing — the spans it was meant to enrich have already been exported. The
    failure mode without this error is silent and total: everything appears to
    work and no attribution arrives.
    """
