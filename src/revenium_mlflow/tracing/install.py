"""The install entry point and the handle it returns.

Phase 1 published the shape; plan 04-01 filled in the two members the integration
gate needs — :func:`configure_tracing` and
:meth:`ReveniumExportHandle.flush`. :meth:`ReveniumExportHandle.is_active` and
:meth:`ReveniumExportHandle.reinstall` still raise, now naming plan 04-04 as
their owner. That is not an oversight and must not be "finished" with a
plausible-looking body: a handle whose ``is_active()`` returns a cheerful ``True``
it did not verify is precisely the silent-success shape this module was written
to reject.

Two shapes here are decisions rather than defaults.

**The entry point is named ``configure_tracing``, and it was ``configure_dual_export``
until 2026-09-09 (supersedes D-04).** D-04 kept the old name on the argument that
renaming a published entry point costs every user an import change. That argument
does not apply: this project's delivery boundary is build artifacts only, nothing
has been published, and there is no external importer to migrate — the same fact
plan 01-05 already recorded when it rated the name one-way. With that cost at
zero, three things were wrong with the old name and a human chose to fix them.

*MLflow owns the term "dual export".*
``MLFLOW_TRACE_ENABLE_OTLP_DUAL_EXPORT`` is a real MLflow environment variable
(``mlflow/environment_variables.py:1017``, consumed at
``mlflow/tracing/provider.py:855``), and this SDK deliberately does not use it —
it attaches its own exporter to the bridged provider, because MLflow's built-in
path drops cache tokens, consumes the process's single OTLP endpoint slot, and
often omits ``gen_ai.provider.name``. So the old name named an MLflow feature
this function *bypasses*, which misleads exactly the reader who knows MLflow
best into thinking the call toggles that flag.

*The old name described half the function.* Two processors are installed below,
not one: the attribution processor that stamps ``revenium.*`` and the batch
exporter that ships spans. "Export" named the second and was silent about the
first.

*The codebase already disagreed with it.* The returned handle exposes
``is_active()`` and ``reinstall()``, and plan 04-04 is titled "processor eviction
and reinstall". Install vocabulary was already the house style everywhere except
the function that does the installing.

``configure_tracing`` specifically, because both installed processors are
tracing-layer concerns, it aligns with the ``tracing`` subpackage this module
lives in, and it cannot be read as covering the sibling ``metering`` subpackage
that Phase 5 fills in with tool events and job outcomes. The three alternatives
were rejected on the record: ``install()`` pairs with ``reinstall()`` but reads
as packaging at module level; ``configure()`` says nothing about scope and turns
ambiguous the moment Phase 5 lands; ``configure_metering()`` collides with the
``metering`` subpackage and claims a scope this function does not have.

**No alias was left behind.** A deprecated ``configure_dual_export = configure_tracing``
would be dead weight against zero installed users, and it would leave two names
for one entry point — both of which then have to be explained, and one of which
still names the MLflow mechanism this SDK bypasses.

The phrase "dual export" survives where it describes the *topology* — one trace,
two destinations — which is what ``tests/unit/test_dual_export_gate.py`` and
``docs/verification/exp-03-dual-export.md`` are about, and remains accurate.

**It returns a typed handle, never ``None`` (CFG-07).** A configure call that
returns nothing leaves an operator with no way to answer "is it actually
installed?", and that question is not academic here: MLflow's ``enable()``,
``disable()`` and ``set_destination()`` rebuild the tracer provider and evict
third-party processors as a side effect. The handle is how CFG-06 gives that
eviction somewhere to be observed and repaired.

**How the Revenium credential rides — a recorded human decision.** Plan 04-01
Task 1 was a ``checkpoint:decision`` with ``gate="blocking-human"``, answered
``recommended`` on 2026-09-07: a single lowercase ``x-api-key`` header, and no
``Authorization: Bearer`` alongside it. The evidence is the installed
``revenium-python-sdk`` 0.7.0 wheel, where every ``/meter/*`` route authenticates
that way — ``revenium_middleware/_metering/_client.py:168`` and ``:387``,
``_core/outcomes.py:35``, ``_core/metering_buffer.py:130``,
``_metering/decorator.py:278`` and ``_core/enforcement.py:355``. The OTLP traces
route shares the ``/meter`` context path and the same metering auth filter. This
remains an inference — PROJECT.md forbids calling ``api.revenium.io`` to check —
and the ``both-headers`` option that would have removed the guess was rejected on
the cost it carries: sending the credential twice doubles the number of places it
appears in any captured traffic, log or proxy record.
"""

from typing import Final as _Final

from opentelemetry.sdk.trace import TracerProvider as _SDKTracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor

# ``_HTTP_PROTOBUF`` is private to :mod:`revenium_mlflow.config`, and importing it
# is deliberate: that module records it as "the one place it is spelled is the one
# place it can be got wrong". Re-spelling the literal here would create the second
# place. In-package only — the private-access wall guards MLflow and
# OpenTelemetry internals, not this package talking to itself.
from revenium_mlflow.config import _HTTP_PROTOBUF as _REQUIRED_OTLP_PROTOCOL
from revenium_mlflow.config import ENVIRONMENT_VARIABLE_NAMES as _ENVIRONMENT_VARIABLE_NAMES
from revenium_mlflow.config import ReveniumConfig
from revenium_mlflow.config import resolve_config as _resolve_config
from revenium_mlflow.errors import ConfigurationError as _ConfigurationError

from .exporter import ReveniumSpanExporter as _ReveniumSpanExporter
from .processor import ReveniumAttributionSpanProcessor as _ReveniumAttributionSpanProcessor

__all__ = ["ReveniumExportHandle", "configure_tracing"]

#: The default bound on :meth:`ReveniumExportHandle.flush`, in seconds. Bounded
#: rather than indefinite on purpose: an unbounded flush against a hung
#: collector turns process shutdown into a hang, and a telemetry side-car that
#: prevents an application from exiting has done more damage than the data it
#: was trying to save is worth.
_DEFAULT_FLUSH_TIMEOUT: float = 5.0

#: The header the Revenium credential rides on, and the only one. See this
#: module's docstring for the decision and the six call sites behind it.
_CREDENTIAL_HEADER: _Final[str] = "x-api-key"

_PHASE_4_04 = (
    "not implemented until plan 04-04 (processor eviction and reinstall). It raises "
    "rather than returning a plausible answer: a handle that reports itself active "
    "without checking would tell an operator the integration is installed at exactly "
    "the moment MLflow's provider rebuild had evicted it."
)


class ReveniumExportHandle:
    """The live handle to an installed Revenium export path (CFG-07).

    Returned by :func:`configure_tracing` so the caller holds something they
    can interrogate and repair, instead of a ``None`` that says nothing. It holds
    the provider it attached to, both processors it attached, and the
    configuration that was resolved — the three things every remaining method in
    Phase 4 needs, gathered at the moment they were true.
    """

    def __init__(
        self,
        *,
        provider: _SDKTracerProvider,
        attribution_processor: _ReveniumAttributionSpanProcessor,
        batch_processor: _BatchSpanProcessor,
        config: ReveniumConfig,
    ) -> None:
        """Record what was attached, and to what.

        Keyword-only for the same reason :class:`ReveniumConfig` is: two
        processors of different types sitting next to each other is exactly the
        argument list a positional call gets backwards, and the resulting handle
        would flush the processor that has nothing to flush.
        """
        self._provider = provider
        self._attribution_processor = attribution_processor
        self._batch_processor = batch_processor
        self._config = config

    @property
    def config(self) -> ReveniumConfig:
        """The configuration this handle was installed with.

        Exposed read-only. :class:`ReveniumConfig` is frozen and redacts both
        credentials in its ``__repr__``, so handing it back cannot leak a key
        into a log line and cannot be mutated behind the exporter's back.
        """
        return self._config

    def is_active(self) -> bool:
        """Whether this SDK's processor is still attached to MLflow's provider.

        The question exists because the answer can change without anyone calling
        this SDK: MLflow rebuilds its tracer provider on ``enable()``,
        ``disable()`` and ``set_destination()``, and the rebuild drops
        third-party processors (CFG-06, measured).
        """
        raise NotImplementedError(f"ReveniumExportHandle.is_active() is {_PHASE_4_04}")

    def reinstall(self) -> None:
        """Re-attach the processor and exporter after a provider rebuild (CFG-06).

        Idempotent by contract once implemented: re-attaching a processor that is
        already attached would double-export every span, and a duplicated model
        call is a wrong invoice rather than a duplicated log line.
        """
        raise NotImplementedError(f"ReveniumExportHandle.reinstall() is {_PHASE_4_04}")

    def flush(self, timeout: float = _DEFAULT_FLUSH_TIMEOUT) -> bool:
        """Force-export anything queued, bounded by ``timeout`` seconds.

        Args:
            timeout: The bound, in seconds. Converted to the milliseconds
                OpenTelemetry's processor API takes.

        Returns:
            Whether the queue drained within the bound. The bound is part of the
            signature rather than an implementation detail so that no caller can
            write a flush that hangs a process against an unreachable collector.

        **Flushed against this SDK's own ``BatchSpanProcessor``, never through
        ``TracerProvider.force_flush`` (T-04-05).** The provider-level flush walks
        every attached processor under one shared deadline and returns ``False``
        the moment it expires, skipping every processor it has not reached yet.
        This SDK's processor is appended last, so it is the first to be starved —
        a flush that returned ``False`` would look like a slow collector and
        actually be a busy neighbour.
        """
        return self._batch_processor.force_flush(int(timeout * 1000))


def configure_tracing(
    *,
    config: ReveniumConfig | None = None,
    otlp_traces_endpoint: str | None = None,
    api_key: str | None = None,
) -> ReveniumExportHandle:
    """Attach Revenium's span processor and exporter to MLflow's tracer provider.

    Two destinations, and nothing is diverted or replaced: the customer's
    Tracking Server keeps receiving every trace, and Revenium receives the same
    traces enriched with attribution.

    Named ``configure_tracing`` because it installs two tracing-layer processors
    — the ``revenium.*`` stamp and the OTLP export. It was called
    ``configure_dual_export`` until 2026-09-09; see this module's docstring for
    the recorded reasoning, including why "dual export" was the wrong name to
    borrow (MLflow owns it, and this SDK bypasses the mechanism it names).

    **This function must never write the process-global OTLP variables**
    (CFG-03). ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` and
    ``OTEL_EXPORTER_OTLP_TRACES_HEADERS`` are single-valued and they belong to
    the customer. Setting them would not merely redirect the customer's own
    collector traffic to Revenium — it would ship the Revenium API key in the
    headers variable to every OTLP destination the customer has configured. The
    Revenium exporter therefore carries its own endpoint and its own headers on
    its own instance, passed as constructor arguments. Measured during planning:
    with an explicit ``endpoint=``, ``OTLPSpanExporter`` resolves it without
    consulting the environment and leaves the variable unchanged.
    ``tests/unit/test_otel_slot_untouched.py`` now asserts that byte-identity
    across this call, in both the previously-unset and previously-set cases, and
    walks every module in the shipped package for such a write.

    **Where a Revenium value does come from (CFG-08).** The Revenium-named
    variables, never the OTEL ones:
    ``REVENIUM_OTLP_TRACES_ENDPOINT`` for the full route,
    ``REVENIUM_METERING_BASE_URL`` for a base the route is composed onto — the
    one variable every other Revenium SDK uses to point at a non-production
    deployment — and ``REVENIUM_METERING_API_KEY`` for the credential.

    The MLflow capability probe runs here rather than at import time (D-12), so
    ``import revenium_mlflow`` stays inert and a capability failure surfaces
    where the caller has the context to act on it. The MLflow import and the
    OTLP exporter import are inside this body for the same reason.

    **Registration order is invocation order, and it is load-bearing.** The
    attribution processor is attached *before* the batch processor, because
    OpenTelemetry invokes processors in the order they were added and a stamp
    written after the batch processor has already taken the span is a stamp
    nobody exported — silently, since the export still succeeds.

    Args:
        config: A fully-formed configuration. When supplied, the environment is
            not read at all — see :func:`revenium_mlflow.config.resolve_config`.
            When ``None``, one is resolved from the arguments, the Revenium-named
            environment variables, and the defaults, in that order per field.
        otlp_traces_endpoint: Overrides the resolved traces endpoint.
        api_key: The metering credential (``rev_mk_``) used for trace ingest.

    Returns:
        A :class:`ReveniumExportHandle` — never ``None`` (CFG-07).

    Raises:
        UnsupportedMLflowError: The installed MLflow lacks a required
            capability. Raised by :func:`revenium_mlflow._compat.probe`.
        ConfigurationError: No metering credential was supplied, the configured
            protocol is not ``http/protobuf``, or MLflow handed back a tracer
            provider with no attachment point.
    """
    # Inside the body, like the MLflow import below and for the same reason
    # (D-12): ``_compat`` imports MLflow when it probes, so importing it at
    # module scope here would make ``import revenium_mlflow`` load MLflow through
    # the ``tracing`` package's own ``__init__``. That is exactly the property
    # ``tests/unit/test_import_purity.py`` asserts in a fresh interpreter.
    from revenium_mlflow import _compat

    _compat.probe()

    # Resolution is CFG-08 and lives in ``revenium_mlflow.config`` — the record
    # and the policy about where its values come from are two things (see that
    # module's docstring). Called once, at the top, so every value below comes
    # from one decision rather than from wherever it was first needed.
    resolved = _resolve_config(
        config=config,
        otlp_traces_endpoint=otlp_traces_endpoint,
        api_key=api_key,
    )

    # CFG-09, asserted rather than assumed. MLflow's own OTLP default is ``grpc``
    # and there is no configuration in which falling through to it is right:
    # Revenium's ingest is HTTP plus application/x-protobuf, and the gRPC
    # exporter is not installed, so the fallthrough raises at provider init in a
    # place that names MLflow rather than this SDK.
    if resolved.otlp_protocol != _REQUIRED_OTLP_PROTOCOL:
        raise _ConfigurationError(
            f"otlp_protocol must be {_REQUIRED_OTLP_PROTOCOL!r}, got "
            f"{resolved.otlp_protocol!r}. Revenium's trace ingest speaks HTTP with "
            "application/x-protobuf; no other protocol reaches it."
        )

    # A missing credential is not a configuration nuance, it is a guaranteed 401
    # that nobody sees: OpenTelemetry's BatchSpanProcessor discards
    # SpanExportResult.FAILURE without telling anyone, so the operator's first
    # evidence would be an invoice missing every model call. Failing here costs a
    # traceback at configure time and saves that.
    if not resolved.api_key:
        raise _ConfigurationError(
            "no metering credential was supplied. Pass api_key= to "
            "configure_tracing(), set ReveniumConfig.api_key, or export "
            f"{_ENVIRONMENT_VARIABLE_NAMES['api_key']} — the same variable the "
            "rest of the Revenium SDKs read. Exporting without one would be "
            "rejected remotely and the rejection would be discarded by the batch "
            "processor, leaving no local signal at all."
        )

    # Inside the body (D-12). ``import revenium_mlflow`` must stay inert.
    import mlflow

    # The public attachment point, and the reason PKG-03 puts the MLflow floor at
    # 3.15.0. ``mlflow.tracing.provider`` is banned by TID251 and would need the
    # ``_compat`` boundary; this needs neither.
    provider = mlflow.tracing.get_bridged_tracer_provider()
    if not isinstance(provider, _SDKTracerProvider):
        raise _ConfigurationError(
            "MLflow returned a tracer provider of type "
            f"{type(provider).__name__!r}, which has no add_span_processor(). "
            "A NoOp provider means MLflow tracing is disabled in this process. "
            "The typed diagnosis and its remedy are plan 04-06; this guard exists "
            "so the failure is a named error rather than an AttributeError."
        )

    # Deferred for the same reason the MLflow import is: it pulls in ``requests``
    # and its transport stack, which has no business loading because somebody
    # typed ``import revenium_mlflow``. Imported from the ``...proto.http...``
    # module by name — the gRPC exporter is never imported anywhere on this path,
    # which is what makes "http/protobuf by construction" true rather than
    # merely configured (CFG-09).
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    otlp_exporter = OTLPSpanExporter(
        endpoint=resolved.otlp_traces_endpoint,
        headers={_CREDENTIAL_HEADER: resolved.api_key},
        timeout=int(resolved.read_timeout),
    )
    batch_processor = _BatchSpanProcessor(
        _ReveniumSpanExporter(
            otlp_exporter,
            environment=resolved.environment,
            region=resolved.region,
        )
    )
    attribution_processor = _ReveniumAttributionSpanProcessor()

    provider.add_span_processor(attribution_processor)
    provider.add_span_processor(batch_processor)

    return ReveniumExportHandle(
        provider=provider,
        attribution_processor=attribution_processor,
        batch_processor=batch_processor,
        config=resolved,
    )
