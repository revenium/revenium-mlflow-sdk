"""Packaging metadata is internally consistent.

These assertions are cheap and they catch a specific, easy-to-miss failure: the
version drifting apart across the three places it is written down. ``__version__``
is resolved from installed distribution metadata, so comparing it to that metadata
alone would be a tautology — the check that bites is comparing both against the
``version`` literal in ``pyproject.toml``, which is what the build actually stamps
into the artifact.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pytest

import revenium_mlflow

# `tomllib` entered the standard library in 3.11; this project's floor is 3.10,
# where the parser is `tomli` (installed with the `dev` extra, via `build`).
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib  # type: ignore[no-redef]

DISTRIBUTION_NAME = "revenium-mlflow"

# PEP 440 public version, which is all this package uses. Deliberately not the
# full grammar: a local or dev segment appearing here would be a packaging bug
# worth failing on.
PEP440_PUBLIC = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?$")


def _pyproject() -> dict[str, Any]:
    """Parse the repository's ``pyproject.toml``, or skip outside a source tree."""
    path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not path.is_file():
        pytest.skip("not running from a source checkout; pyproject.toml is unavailable")
    with path.open("rb") as handle:
        return tomllib.load(handle)


@pytest.mark.unit
def test_dunder_version_matches_installed_distribution() -> None:
    """``revenium_mlflow.__version__`` agrees with the installed distribution."""
    try:
        installed = version(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - only without an install
        pytest.skip(f"{DISTRIBUTION_NAME} is not installed in this environment")
    assert revenium_mlflow.__version__ == installed


@pytest.mark.unit
def test_declared_version_matches_installed_distribution() -> None:
    """The ``pyproject.toml`` literal is what got stamped into the install.

    This is the assertion that actually catches drift: a stale editable install,
    or a version bump made in one place and not the other.
    """
    declared = _pyproject()["project"]["version"]
    try:
        installed = version(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - only without an install
        pytest.skip(f"{DISTRIBUTION_NAME} is not installed in this environment")
    assert declared == installed


@pytest.mark.unit
def test_source_tree_fallback_matches_declared_version() -> None:
    """The no-install fallback in ``__init__`` matches the declared version.

    Without this, the fallback silently rots: it is only ever exercised when the
    distribution is absent, which is exactly when nobody is looking.
    """
    declared = _pyproject()["project"]["version"]
    assert declared == revenium_mlflow._FALLBACK_VERSION


@pytest.mark.unit
def test_version_is_pep440() -> None:
    """The version string is a PEP 440 public version."""
    assert PEP440_PUBLIC.match(revenium_mlflow.__version__), revenium_mlflow.__version__


@pytest.mark.unit
def test_py_typed_marker_is_installed() -> None:
    """PEP 561: the marker ships alongside the imported package.

    Present in the built artifacts *and* resolvable from the imported package is
    the pair that matters — a marker in the wheel that does not land next to the
    installed module leaves type checkers ignoring the package's annotations.
    """
    package_dir = Path(revenium_mlflow.__file__).parent
    assert (package_dir / "py.typed").is_file()
