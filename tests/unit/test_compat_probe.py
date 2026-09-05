"""The capability probe behind the ``_compat`` wall (CFG-12).

These tests encode four claims that together define the probe's contract:

1. Against the installed MLflow it returns a typed record, not a boolean.
2. Against a module missing a required capability it raises a *named* error
   that says what is missing and what to do about it — never a warning, never a
   silent degrade. Partial correctness is worse than a clean failure when the
   output is money (Pitfall 11, rule 4).
3. Acceptance is capability-based, never version-based (D-10). A module
   reporting an absurd version but carrying the real public API is accepted.
   Version strings lie: forks, Databricks builds and dev builds all carry them.
4. Importing the package pulls in neither MLflow nor this module (D-12).

The synthetic modules below are built with :class:`types.SimpleNamespace` rather
than by monkeypatching the real ``mlflow``. Patching a shared module makes the
"missing capability" case indistinguishable from a test that broke the module
for everything that runs after it.
"""

import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from revenium_mlflow.errors import ReveniumMLflowError, UnsupportedMLflowError

from revenium_mlflow import _compat

pytestmark = pytest.mark.unit


def _fake_environment_variables(*, genai: bool = True, isolated_id: bool = True) -> SimpleNamespace:
    """Build a stand-in for the public ``mlflow.environment_variables`` module."""
    namespace: dict[str, Any] = {}
    if genai:
        namespace["MLFLOW_ENABLE_OTEL_GENAI_SEMCONV"] = object()
    if isolated_id:
        namespace["MLFLOW_TRACE_USE_ISOLATED_RANDOM_ID_GENERATOR"] = object()
    return SimpleNamespace(**namespace)


def _fake_mlflow(*, version: str, bridged: bool = True) -> SimpleNamespace:
    """Build a stand-in for the top-level ``mlflow`` module."""
    tracing = SimpleNamespace()
    if bridged:
        tracing.get_bridged_tracer_provider = lambda: None
    return SimpleNamespace(
        __version__=version,
        tracing=tracing,
        environment_variables=_fake_environment_variables(),
    )


def test_probe_against_installed_mlflow_returns_a_capability_record() -> None:
    """The happy path: the real dependency satisfies the floor's capability."""
    capabilities = _compat.probe()

    assert isinstance(capabilities, _compat.MLflowCapabilities)
    assert capabilities.has_bridged_tracer_provider is True
    assert capabilities.mlflow_version != "unknown"
    # Recorded for the Phase 4 and Phase 6 diagnostics, deliberately not gated
    # here — their absence must not stop a working install from configuring.
    assert isinstance(capabilities.has_genai_semconv_env, bool)
    assert isinstance(capabilities.has_isolated_id_generator_env, bool)


def test_missing_required_capability_raises_the_named_error() -> None:
    """A missing required capability is fatal, and fatal by name."""
    downgraded = _fake_mlflow(version="3.14.0", bridged=False)

    with pytest.raises(UnsupportedMLflowError):
        _compat.probe(downgraded)


def test_the_error_message_names_the_capability_the_version_and_the_remedy() -> None:
    """The message has to be actionable on its own, without a traceback reader."""
    downgraded = _fake_mlflow(version="3.14.0", bridged=False)

    with pytest.raises(UnsupportedMLflowError) as caught:
        _compat.probe(downgraded)

    message = str(caught.value)
    assert "has_bridged_tracer_provider" in message
    assert "3.14.0" in message
    assert "mlflow>=3.15.0,<4" in message


def test_an_unknown_future_version_with_the_capability_is_accepted() -> None:
    """D-10: capability-based acceptance, so a newer MLflow keeps working.

    A version comparison would reject this module. Nothing about it is broken —
    it carries the exact public API the SDK depends on.
    """
    futuristic = _fake_mlflow(version="9.9.9")

    capabilities = _compat.probe(futuristic)

    assert capabilities.mlflow_version == "9.9.9"
    assert capabilities.has_bridged_tracer_provider is True


def test_required_capabilities_is_the_single_gated_set() -> None:
    """The gate is one named capability at this floor, not a version range."""
    assert _compat.REQUIRED_CAPABILITIES == ("has_bridged_tracer_provider",)
    for name in _compat.REQUIRED_CAPABILITIES:
        assert hasattr(_compat.MLflowCapabilities, "__dataclass_fields__")
        assert name in _compat.MLflowCapabilities.__dataclass_fields__


def test_a_missing_version_string_is_recorded_as_unknown_not_inferred() -> None:
    """An absent ``__version__`` is reported, never guessed at."""
    anonymous = SimpleNamespace(
        tracing=SimpleNamespace(get_bridged_tracer_provider=lambda: None),
        environment_variables=_fake_environment_variables(),
    )

    assert _compat.probe(anonymous).mlflow_version == "unknown"


def test_the_error_hierarchy_is_rooted_in_one_exception() -> None:
    """One root means callers can catch everything this SDK raises with one name."""
    assert issubclass(UnsupportedMLflowError, ReveniumMLflowError)
    assert issubclass(ReveniumMLflowError, Exception)


def test_importing_the_package_loads_neither_mlflow_nor_the_compat_module() -> None:
    """D-12: ``import revenium_mlflow`` stays inert.

    Run in a subprocess because this test module has already imported
    ``_compat``, so an in-process ``sys.modules`` check would assert nothing.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import revenium_mlflow, sys; "
            "print('mlflow' in sys.modules, "
            "'revenium_mlflow._compat' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False False"
