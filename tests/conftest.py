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

#: pytest's own per-test bookkeeping variable. Excluded from the session
#: environment comparison below because pytest owns it and rewrites it before
#: every setup and teardown — it is never evidence about a test module's
#: hygiene, which is what that comparison is for. Named as a single exclusion
#: rather than a prefix pattern, so a second one would have to be added
#: deliberately.
_PYTEST_BOOKKEEPING = frozenset({"PYTEST_CURRENT_TEST"})


def _environment_without_pytest_bookkeeping() -> dict[str, str]:
    """The process environment, minus the variables pytest itself manages."""
    return {name: value for name, value in os.environ.items() if name not in _PYTEST_BOOKKEEPING}


@pytest.fixture(scope="session", autouse=True)
def _the_session_leaves_the_environment_as_it_found_it() -> Iterator[None]:
    """Assert the whole process environment is unchanged across the session.

    Added by plan 04-02. Several test modules in Phase 4 set, clear and restore
    environment variables — ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` most
    consequentially, because MLflow reads it at provider initialisation and a
    leaked value silently reconfigures every module that runs afterwards. Each of
    those modules restores what it touched in its own fixture, which is the right
    place for it. This is the check that the restoration actually happened.

    **Defined first in this file on purpose.** Session-scoped autouse fixtures
    finalise in reverse order of setup, so declaring this one before the two
    mutating fixtures below means it snapshots before they change anything and
    compares after they have put it back. Declared last, it would compare
    against their mutations and pass while measuring nothing.

    The failure surfaces as a teardown error naming the variables that differ,
    which is a worse report than a failing test and still far better than the
    alternative: a suite whose results depend on module collection order, which
    is how plan 04-01 spent a cycle on
    ``tests/unit/test_on_start_not_on_end.py``.

    **It was shown able to fail on its first run**, which is worth recording
    because a green environment check is otherwise indistinguishable from a
    check that compares nothing: it reported
    ``Changed: {'PYTEST_CURRENT_TEST': (...)}``. That variable is pytest's own
    per-test bookkeeping and is excluded by
    :func:`_environment_without_pytest_bookkeeping`; nothing else differed.
    """
    before = _environment_without_pytest_bookkeeping()
    yield
    after = _environment_without_pytest_bookkeeping()

    added = {name: after[name] for name in after.keys() - before.keys()}
    removed = sorted(before.keys() - after.keys())
    changed = {
        name: (before[name], after[name])
        for name in before.keys() & after.keys()
        if before[name] != after[name]
    }
    assert (added, removed, changed) == ({}, [], {}), (
        "the test session did not leave the environment as it found it. "
        f"Added: {added}. Removed: {removed}. Changed: {changed}. "
        "Some module's fixture set a variable without restoring it, and every "
        "module that ran after it was configured by that leak."
    )


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
