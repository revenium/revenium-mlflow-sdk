"""The install entry point and the handle it returns.

Phase 1 publishes the shape only. Nothing here attaches a processor, resolves an
endpoint, reads an environment variable, or opens a socket — that is Phase 4
(CFG-01 through CFG-11). What is fixed now is the part that becomes a contract
the moment a user writes it down: the function's name, its keyword-only
parameters, and the fact that it returns a value rather than ``None``.

Two shapes here are decisions rather than defaults.

**The name stays ``configure_dual_export`` (D-04).** The SDK no longer drives
MLflow's ``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`` mechanism, so the name no
longer describes the *mechanism*. It still describes the *outcome* — the trace
reaches both the customer's Tracking Server and Revenium — and the outcome is
what a caller is choosing when they type it. Renaming a published entry point
costs every user an import change and buys a more literal name for one release.

**It returns a typed handle, never ``None`` (CFG-07).** A configure call that
returns nothing leaves an operator with no way to answer "is it actually
installed?", and that question is not academic here: MLflow's ``enable()``,
``disable()`` and ``set_destination()`` rebuild the tracer provider and evict
third-party processors as a side effect. The handle is how CFG-06 gives that
eviction somewhere to be observed and repaired.
"""

from revenium_mlflow.config import ReveniumConfig

__all__ = ["ReveniumExportHandle", "configure_dual_export"]

#: The default bound on :meth:`ReveniumExportHandle.flush`, in seconds. Bounded
#: rather than indefinite on purpose: an unbounded flush against a hung
#: collector turns process shutdown into a hang, and a telemetry side-car that
#: prevents an application from exiting has done more damage than the data it
#: was trying to save is worth.
_DEFAULT_FLUSH_TIMEOUT: float = 5.0

_PHASE_4 = (
    "not implemented until Phase 4 (Revenium-Owned OTLP Export and the Install Gate). "
    "Phase 1 publishes this signature so callers and type checkers can be written "
    "against it; it deliberately raises rather than succeeding silently, because a "
    "no-op install would report a working integration while exporting nothing."
)


class ReveniumExportHandle:
    """The live handle to an installed Revenium export path (CFG-07).

    Returned by :func:`configure_dual_export` so the caller holds something they
    can interrogate and repair, instead of a ``None`` that says nothing. Every
    method raises in Phase 1; Phase 4 fills them in.
    """

    def is_active(self) -> bool:
        """Whether this SDK's processor is still attached to MLflow's provider.

        The question exists because the answer can change without anyone calling
        this SDK: MLflow rebuilds its tracer provider on ``enable()``,
        ``disable()`` and ``set_destination()``, and the rebuild drops
        third-party processors (CFG-06, measured).
        """
        raise NotImplementedError(f"ReveniumExportHandle.is_active() is {_PHASE_4}")

    def reinstall(self) -> None:
        """Re-attach the processor and exporter after a provider rebuild (CFG-06).

        Idempotent by contract once implemented: re-attaching a processor that is
        already attached would double-export every span, and a duplicated model
        call is a wrong invoice rather than a duplicated log line.
        """
        raise NotImplementedError(f"ReveniumExportHandle.reinstall() is {_PHASE_4}")

    def flush(self, timeout: float = _DEFAULT_FLUSH_TIMEOUT) -> bool:
        """Force-export anything queued, bounded by ``timeout`` seconds.

        Returns whether the queue drained within the bound. The bound is part of
        the signature rather than an implementation detail so that no caller can
        write a flush that hangs a process against an unreachable collector.
        """
        raise NotImplementedError(f"ReveniumExportHandle.flush() is {_PHASE_4}")


def configure_dual_export(
    *,
    config: ReveniumConfig | None = None,
    otlp_traces_endpoint: str | None = None,
    api_key: str | None = None,
) -> ReveniumExportHandle:
    """Attach Revenium's span processor and exporter to MLflow's tracer provider.

    "Dual" is the outcome, not the mechanism (D-04): the customer's Tracking
    Server keeps receiving every trace and Revenium receives the same traces
    enriched with attribution. Nothing is diverted and nothing is replaced.

    **This function must never write the process-global OTLP variables**
    (CFG-03). ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` and
    ``OTEL_EXPORTER_OTLP_TRACES_HEADERS`` are single-valued and they belong to
    the customer. Setting them would not merely redirect the customer's own
    collector traffic to Revenium — it would ship the Revenium API key in the
    headers variable to every OTLP destination the customer has configured. The
    Revenium exporter therefore carries its own endpoint and its own headers on
    its own instance. That constraint is recorded here, before any
    implementation exists, because it is the kind of shortcut that looks like a
    convenience at the moment someone reaches for it.

    The MLflow capability probe runs here rather than at import time (D-12), so
    ``import revenium_mlflow`` stays inert and a capability failure surfaces
    where the caller has the context to act on it.

    Args:
        config: A fully-formed configuration. When ``None``, Phase 4 resolves
            one from the remaining arguments and the environment (CFG-08).
        otlp_traces_endpoint: Overrides the resolved traces endpoint.
        api_key: The metering credential (``rev_mk_``) used for trace ingest.

    Returns:
        A :class:`ReveniumExportHandle` — never ``None`` (CFG-07).

    Raises:
        NotImplementedError: Always, in Phase 1.
    """
    raise NotImplementedError(f"configure_dual_export() is {_PHASE_4}")
