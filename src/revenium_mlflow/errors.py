"""The exception hierarchy this SDK raises.

Everything raised deliberately by ``revenium_mlflow`` descends from
:class:`ReveniumMLflowError`, so an application that wants to treat "the
telemetry side-car had a problem" as one case can catch one name. Callers that
need to distinguish causes catch the subclasses instead.

This module imports nothing outside the standard library and is safe to import
at any point, including from the package ``__init__``.
"""

__all__ = ["ReveniumMLflowError", "UnsupportedMLflowError"]


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
