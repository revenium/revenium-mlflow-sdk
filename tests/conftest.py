"""pytest configuration root.

This file exists so pytest roots the test session at the repository root and
``tests`` imports resolve as a package. Shared fixtures — the fake OTLP
collector, the ``respx`` router, the socket guard — arrive with the plans that
need them.
"""

import os
from collections.abc import Iterator

import pytest

#: MLflow performs its own outbound telemetry and prints an agent hint on
#: import. This project forbids network calls to any hosted endpoint during
#: development or testing, and that prohibition covers calls made on MLflow's
#: behalf as much as calls this SDK makes itself. Both variables are set before
#: any test imports MLflow, which holds because nothing imports MLflow at module
#: scope — ``_compat.probe()`` imports it inside the function body (D-12), so
#: the first import happens during test execution, after this fixture has run.
_MLFLOW_QUIET_ENV = {
    "MLFLOW_DISABLE_TELEMETRY": "true",
    "MLFLOW_DISABLE_AGENT_HINT": "1",
}


#: The prefix every Revenium-named configuration variable carries. Cleared for
#: the whole session by the fixture below.
_REVENIUM_ENV_PREFIX = "REVENIUM_"


@pytest.fixture(scope="session", autouse=True)
def _clear_revenium_environment() -> Iterator[None]:
    """Remove every ``REVENIUM_*`` variable for the session, and restore it after.

    Added by plan 04-02, when ``configure_tracing`` began resolving its endpoint
    and credential from the environment (CFG-08). Two things that fixes:

    *Determinism.* A developer running this suite with their own
    ``REVENIUM_METERING_API_KEY`` exported would otherwise change what several
    tests measure — most sharply
    ``test_configure_tracing_refuses_to_install_without_a_credential``, which
    would stop testing the refusal and start testing their shell.

    *Credential safety.* A real key in a developer's environment must not be
    reachable by any test in a suite whose collectors capture and print request
    headers. Nothing here needs a live credential and nothing here should be able
    to find one.

    Session-scoped and autouse, so it is established before the first test rather
    than depending on any test remembering to ask. Restored exactly on teardown,
    including the case where a variable was set to the empty string.

    Tests that need a Revenium variable set supply it explicitly — the
    resolution tests pass their own ``environ`` mapping and never touch the
    process environment at all.
    """
    removed = {
        name: value for name, value in os.environ.items() if name.startswith(_REVENIUM_ENV_PREFIX)
    }
    for name in removed:
        del os.environ[name]
    try:
        yield
    finally:
        os.environ.update(removed)


@pytest.fixture(scope="session", autouse=True)
def _disable_mlflow_telemetry() -> Iterator[None]:
    """Silence MLflow's outbound telemetry for the whole session.

    Session-scoped and autouse so it is established once, before the first
    test runs, rather than depending on any test remembering to request it.
    The previous values are restored on teardown so the fixture leaves the
    environment exactly as it found it.
    """
    previous = {name: os.environ.get(name) for name in _MLFLOW_QUIET_ENV}
    os.environ.update(_MLFLOW_QUIET_ENV)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
