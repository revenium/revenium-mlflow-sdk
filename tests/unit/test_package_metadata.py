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
from email.message import Message
from importlib.metadata import (
    PackageNotFoundError,
    metadata,
    packages_distributions,
    version,
)
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

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


# --- PKG-01: distribution name, import package name, product name -----------

IMPORT_PACKAGE_NAME = "revenium_mlflow"
PRODUCT_NAME = "Revenium MLflow SDK"

REPO_ROOT = Path(__file__).resolve().parents[2]


def _installed_metadata() -> Message:
    """Metadata of the installed distribution, or skip when it is absent."""
    try:
        return metadata(DISTRIBUTION_NAME)
    except PackageNotFoundError:  # pragma: no cover - only without an install
        pytest.skip(f"{DISTRIBUTION_NAME} is not installed in this environment")


@pytest.mark.unit
def test_declared_distribution_name_is_revenium_mlflow() -> None:
    """``pyproject.toml`` and the installed distribution agree on the name.

    Asserting the constant against itself would be a tautology, so both sides
    come from artifacts: the declaration and the install.
    """
    assert _pyproject()["project"]["name"] == DISTRIBUTION_NAME
    assert _installed_metadata()["Name"] == DISTRIBUTION_NAME


@pytest.mark.unit
def test_import_package_is_revenium_mlflow() -> None:
    """The importable package is ``revenium_mlflow`` and it belongs to this dist.

    ``packages_distributions`` reads the installed environment rather than the
    source tree, so a package that shipped under some other top-level name — or
    that resolves from a stray directory on ``sys.path`` rather than from this
    distribution — fails here.
    """
    assert revenium_mlflow.__name__ == IMPORT_PACKAGE_NAME
    owners = packages_distributions().get(IMPORT_PACKAGE_NAME)
    if owners is None:  # pragma: no cover - only without an install
        pytest.skip(f"{IMPORT_PACKAGE_NAME} is not installed in this environment")
    assert DISTRIBUTION_NAME in owners


@pytest.mark.unit
def test_product_name_is_documented_in_readme_and_shipped_metadata() -> None:
    """The documented product name is "Revenium MLflow SDK", and it ships.

    The README heading is where a reader meets the name; the installed long
    description is where an installer does. Both are asserted because a rename
    that reaches only one of them is exactly the drift worth catching.

    The assertion is on the *first ATX heading*, not on line 1. The Revenium
    Labs banner image and status badges sit above the title, matching the
    sibling Labs repositories. That is a layout fact, not a rename, and the
    drift this test exists to catch is a rename — so the check follows the
    heading rather than pinning a line number. Anything that precedes the
    heading must still be non-heading markup: the first ``# `` line in the
    file is the one asserted, so a second title inserted above would fail.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    headings = [line.strip() for line in readme.splitlines() if line.startswith("# ")]
    assert headings, "README.md contains no top-level heading"
    assert headings[0] == f"# {PRODUCT_NAME}"
    assert PRODUCT_NAME in (_installed_metadata()["Description"] or "")


# --- PKG-07: positioning ships in the distribution metadata -----------------

# Matched case-insensitively against the shipped Summary and long description.
# Deliberately narrow: "not part of" and "endorsed" together are the specific
# disclaimer the requirement names, not a generic mention of MLflow.
_SUPPORTED_PATTERN = re.compile(r"revenium[- ]supported", re.IGNORECASE)
_DISCLAIMER_PATTERNS = (
    re.compile(r"neither part of,? nor endorsed by,? the MLflow project", re.IGNORECASE),
)


@pytest.mark.unit
def test_shipped_summary_positions_the_sdk_as_revenium_supported() -> None:
    """The one-line Summary that PyPI and ``pip show`` display carries both claims.

    Asserted against installed metadata rather than the README source: the
    requirement is about what ships, and a README-only claim never reaches an
    installer.
    """
    summary = _installed_metadata()["Summary"] or ""
    assert _SUPPORTED_PATTERN.search(summary), summary
    assert any(p.search(summary) for p in _DISCLAIMER_PATTERNS), summary


@pytest.mark.unit
def test_shipped_long_description_disclaims_mlflow_endorsement() -> None:
    """The long description shipped in the distribution carries the disclaimer."""
    description = _installed_metadata()["Description"] or ""
    assert description.strip(), "the distribution ships no long description"
    assert any(p.search(description) for p in _DISCLAIMER_PATTERNS), description[:400]


# --- PKG-06: declared dependency specifiers ---------------------------------

# Requirement string -> the floor (and ceiling) the stack research locked in.
# Compared as parsed `SpecifierSet`s, so `>=3.15.0,<4` and `<4,>=3.15.0` are the
# same declaration and a reordering is not a failure.
REQUIRED_DEPENDENCIES = {
    "mlflow": SpecifierSet(">=3.15.0"),
    "opentelemetry-api": SpecifierSet(">=1.30.0,<2"),
    "opentelemetry-sdk": SpecifierSet(">=1.30.0,<2"),
    "opentelemetry-exporter-otlp-proto-http": SpecifierSet(">=1.30.0,<2"),
    "revenium-python-sdk": SpecifierSet(">=0.7.0,<1"),
    "httpx": None,  # presence only; PROJECT.md fixes no floor for it
}

# Declarations that must be absent. Substring matching cannot express these:
# `opentelemetry-exporter-otlp` is a prefix of the exporter that IS declared, so
# a grep for it reports a violation that does not exist. Names are compared
# canonicalised, after parsing.
FORBIDDEN_DEPENDENCIES = {
    # Co-installs against a user's mlflow-skinny, splices the mlflow/ package
    # tree, and degrades GenAI semconv to a silent no-op.
    "mlflow-tracing",
    # The meta-package drags in the gRPC exporter and grpcio; Revenium's route
    # is HTTP + application/x-protobuf.
    "opentelemetry-exporter-otlp",
}


def _declared_dependencies() -> dict[str, Requirement]:
    """Runtime dependencies from ``pyproject.toml``, keyed by canonical name."""
    parsed = [Requirement(raw) for raw in _pyproject()["project"]["dependencies"]]
    return {canonicalize_name(req.name): req for req in parsed}


@pytest.mark.unit
def test_requires_python_floor_is_310() -> None:
    """``requires-python`` admits 3.10 and excludes 3.9."""
    specifier = SpecifierSet(_pyproject()["project"]["requires-python"])
    assert specifier.contains("3.10")
    assert not specifier.contains("3.9")


@pytest.mark.unit
def test_build_requires_setuptools_77_or_newer() -> None:
    """PEP 639 ``license = "MIT"`` needs setuptools>=77; 76.1.0 fails to build."""
    requires = _pyproject()["build-system"]["requires"]
    by_name = {canonicalize_name(Requirement(raw).name): Requirement(raw) for raw in requires}
    setuptools = by_name.get("setuptools")
    assert setuptools is not None, requires
    assert not setuptools.specifier.contains("76.1.0")
    assert setuptools.specifier.contains("77.0.1")


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(REQUIRED_DEPENDENCIES))
def test_required_dependency_is_declared_with_the_locked_bounds(name: str) -> None:
    """Each locked dependency is declared, by parsed name, with its bounds.

    Names are compared after parsing and canonicalisation rather than by
    substring: `opentelemetry-exporter-otlp` is a substring of
    `opentelemetry-exporter-otlp-proto-http`, so a textual check cannot tell the
    banned meta-package from the exporter that is required.
    """
    declared = _declared_dependencies()
    requirement = declared.get(canonicalize_name(name))
    assert requirement is not None, f"{name} is not declared; found {sorted(declared)}"
    expected = REQUIRED_DEPENDENCIES[name]
    if expected is None:
        return
    # Every clause the research locked in must be present verbatim in the
    # declaration. Extra clauses (a tighter ceiling) are allowed; a missing or
    # loosened floor is not.
    declared_clauses = {str(spec) for spec in requirement.specifier}
    missing = {str(spec) for spec in expected} - declared_clauses
    assert not missing, f"{name} declares {requirement.specifier}, missing {sorted(missing)}"


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(FORBIDDEN_DEPENDENCIES))
def test_forbidden_distribution_is_not_declared(name: str) -> None:
    """Neither `mlflow-tracing` nor the OTLP exporter meta-package is declared."""
    assert canonicalize_name(name) not in _declared_dependencies()


@pytest.mark.unit
def test_opentelemetry_sdk_is_not_pinned_exactly() -> None:
    """An exact pin on `opentelemetry-sdk` conflicts with the OTLP exporter.

    The exporter requires a compatible-release match (`~=1.44.0`), so `==` or
    `===` here makes the tree unresolvable on the next exporter upgrade.
    """
    requirement = _declared_dependencies()[canonicalize_name("opentelemetry-sdk")]
    operators = {spec.operator for spec in requirement.specifier}
    assert not operators & {"==", "==="}, str(requirement.specifier)
