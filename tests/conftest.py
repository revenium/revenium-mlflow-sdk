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
