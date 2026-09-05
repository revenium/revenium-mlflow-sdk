"""The single sanctioned boundary between this SDK and MLflow's internals.

MLflow renames its internals without ceremony, and correctly so — it treats them
as internal. It needed a ``try/except AttributeError`` in its own span processor
to survive an OpenTelemetry *patch* release. An SDK layered on top inherits that
instability and multiplies it, so every private access this package ever needs
is confined to this module and nowhere else (CFG-12). Two independent mechanisms
keep it that way: ruff's private-member and banned-import rules, and an AST walk
in ``tests/unit/test_private_access_wall.py`` that scans every other module.

**At the ``mlflow>=3.15.0,<4`` floor this module contains no private access at
all.** 3.15.0 is the first release exposing a public attachment point for a
custom span processor, so the happy path needs nothing internal, and the wall
starts empty (D-09). That is the point of building it now: the first genuine
breach — Phase 4 must detect processor *eviction*, which MLflow performs
externally — becomes a deliberate, reviewable edit to this file rather than one
private read among many.

Two properties of this module are load-bearing and easy to destroy by accident:

**The MLflow import lives inside the function body, never at module scope**
(D-12). ``import revenium_mlflow`` must stay inert — no MLflow load, no MLflow
telemetry, no configuration read, no raise. The probe belongs to configure time,
where a failure is actionable and in context.

**Acceptance is capability-based, never version-based** (D-10). Nothing here
compares ``__version__`` to decide anything; the version is recorded and quoted
in messages only. Version strings lie — forks, Databricks builds and dev builds
all carry them — and hard-failing outside a tested range would break working
installs the day MLflow ships a patch. A build carrying the public API this SDK
depends on is accepted whatever it calls itself; one that does not is rejected
by name.
"""

# Imported under private aliases so this module's public surface is exactly the
# three names in ``__all__``. That set is asserted mechanically, and a module
# whose declared and actual surfaces disagree is a module whose boundary claims
# have to be taken on trust.
import dataclasses as _dataclasses
import types as _types

from . import errors as _errors

__all__ = ["REQUIRED_CAPABILITIES", "MLflowCapabilities", "probe"]

#: Recorded when the module reports no version of its own. Never inferred from
#: behaviour, and never compared against anything.
_UNKNOWN_VERSION = "unknown"

#: Quoted in the failure message as the remedy. It is the dependency this
#: package declares, restated where a person reading a traceback will see it.
_SUPPORTED_SPECIFIER = "mlflow>=3.15.0,<4"

_GENAI_SEMCONV_ENV = "MLFLOW_ENABLE_OTEL_GENAI_SEMCONV"
_ISOLATED_ID_GENERATOR_ENV = "MLFLOW_TRACE_USE_ISOLATED_RANDOM_ID_GENERATOR"

#: Maps each capability to the public symbol whose presence it detects, so the
#: failure message can name something a person can look up.
_CAPABILITY_SYMBOLS = {
    "has_bridged_tracer_provider": "mlflow.tracing.get_bridged_tracer_provider()",
    "has_genai_semconv_env": _GENAI_SEMCONV_ENV,
    "has_isolated_id_generator_env": _ISOLATED_ID_GENERATOR_ENV,
}


@_dataclasses.dataclass(frozen=True)
class MLflowCapabilities:
    """What the installed MLflow can actually do, as observed rather than assumed.

    Frozen because it is a record of one observation. A caller that wants a
    fresh reading calls :func:`probe` again; mutating a stale record in place
    would make the observation untraceable to the moment it was taken.
    """

    #: ``mlflow.__version__`` as reported, or ``"unknown"``. Recorded for
    #: diagnostics and quoted in error messages — never used to decide anything.
    mlflow_version: str

    #: Whether ``mlflow.tracing.get_bridged_tracer_provider`` is present and
    #: callable. This is the only public route to attach a custom span
    #: processor, so its absence is fatal.
    has_bridged_tracer_provider: bool

    #: Whether MLflow exposes the GenAI semantic-convention toggle. Recorded for
    #: the Phase 4 install path and Phase 6 diagnostics; not gated here.
    has_genai_semconv_env: bool

    #: Whether MLflow exposes the isolated random ID generator toggle. Recorded
    #: for the duplicate-span-ID diagnostics; not gated here.
    has_isolated_id_generator_env: bool


#: The capabilities whose absence is fatal at this floor. The other fields on
#: :class:`MLflowCapabilities` are observed and reported, deliberately not
#: gated: a missing diagnostic toggle must not stop a working install from
#: configuring, and widening this tuple is how a capability graduates from
#: "recorded" to "required".
REQUIRED_CAPABILITIES: tuple[str, ...] = ("has_bridged_tracer_provider",)

#: Populated on the first successful default probe, never at import — see D-12.
#: Only the default probe is cached; an explicitly supplied module is a
#: different question and is answered afresh every time.
_cached_capabilities: MLflowCapabilities | None = None


def probe(mlflow_module: _types.ModuleType | None = None) -> MLflowCapabilities:
    """Observe what the installed MLflow provides, or fail by name.

    Args:
        mlflow_module: The module to inspect. Defaults to importing ``mlflow``
            inside this call. Tests pass a duck-typed stand-in — anything the
            ``getattr`` probes below can read — rather than monkeypatching the
            real module, which would leave it broken for everything that runs
            after.

    Returns:
        A record of every capability observed, required or not.

    Raises:
        UnsupportedMLflowError: A capability named in
            :data:`REQUIRED_CAPABILITIES` is absent. The message names the
            capability, the observed version and the remedy.
    """
    global _cached_capabilities

    module: _types.ModuleType
    if mlflow_module is None:
        if _cached_capabilities is not None:
            return _cached_capabilities
        # Inside the function body on purpose (D-12). Hoisting this to module
        # scope would make ``import revenium_mlflow._compat`` load MLflow, and
        # any later import of this module from the package ``__init__`` would
        # then make merely importing the SDK do it too.
        import mlflow

        module = mlflow
    else:
        module = mlflow_module

    environment_variables = getattr(module, "environment_variables", None)
    capabilities = MLflowCapabilities(
        mlflow_version=str(getattr(module, "__version__", _UNKNOWN_VERSION)),
        has_bridged_tracer_provider=callable(
            getattr(getattr(module, "tracing", None), "get_bridged_tracer_provider", None)
        ),
        has_genai_semconv_env=hasattr(environment_variables, _GENAI_SEMCONV_ENV),
        has_isolated_id_generator_env=hasattr(environment_variables, _ISOLATED_ID_GENERATOR_ENV),
    )

    missing = [name for name in REQUIRED_CAPABILITIES if not getattr(capabilities, name, False)]
    if missing:
        raise _errors.UnsupportedMLflowError(
            _unsupported_message(missing, capabilities.mlflow_version)
        )

    if mlflow_module is None:
        _cached_capabilities = capabilities
    return capabilities


def _unsupported_message(missing: list[str], observed_version: str) -> str:
    """Compose a failure a person can act on without reading this source."""
    named = ", ".join(f"{name} ({_CAPABILITY_SYMBOLS.get(name, name)})" for name in missing)
    return (
        f"The installed MLflow is missing a capability this SDK requires: {named}. "
        f"Observed mlflow.__version__ is {observed_version!r}. "
        f"Remedy: install a release satisfying {_SUPPORTED_SPECIFIER}. "
        "That floor is where the bridged tracer provider first appears, and it is the "
        "only public way to attach a span processor to MLflow's tracing pipeline. "
        "This check reads capabilities, not version numbers, so the report above is "
        "what is genuinely absent rather than a complaint about how the build is named."
    )
