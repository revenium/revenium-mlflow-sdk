"""The published surface of ``revenium_mlflow``: what it carries, and what it costs.

``__all__`` is the most expensive artefact in this repository. Under the
project's own delivery boundary nothing is published yet, so today it costs
nothing — but the day it ships, every name in it becomes something a user may
import forever, and D-02 records the surface being chosen deliberately rather
than accumulated. These tests pin the choice.

*Flat imports (D-01).* All six callables must resolve directly from the
top-level package. The internal split into an OTLP package and a Revenium-HTTP
package exists so that structure can change later without changing any user's
import line; a test that imported from the submodules would quietly make the
internal layout part of the contract it was supposed to protect.

*Completeness in both directions.* A name in ``__all__`` that does not resolve
turns ``from revenium_mlflow import *`` into an ``AttributeError`` at import
time — so every listed name is fetched. And a callable missing from the list is
invisible to a wildcard import and to most tooling — so each required group is
checked for presence. Both directions are derived from the source of truth
(``REVENIUM_ATTRIBUTE_KEYS``, ``errors.__all__``) rather than restated here,
because a hand-written expectation is one more thing that can drift.

*Import purity (PKG-09, D-12).* Importing this package must load neither MLflow
nor the compatibility probe. That claim is checked in a **subprocess**: this test
session imports MLflow elsewhere, so an in-process ``'mlflow' in sys.modules``
assertion would pass or fail depending on test ordering, which is no assertion at
all. Plan 01-06 proves the property comprehensively; this is the cheap guard that
fails in the same commit that would break it.
"""

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import revenium_mlflow
from revenium_mlflow import errors
from revenium_mlflow.attributes import REVENIUM_ATTRIBUTE_KEYS

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_METERING_ROOT = _REPO_ROOT / "src" / "revenium_mlflow" / "metering"

#: The six callables PROJECT.md names as the public API.
_PUBLIC_CALLABLES = (
    "configure_dual_export",
    "attribution",
    "ReveniumAttributionSpanProcessor",
    "meter_tool_span",
    "report_job_outcome",
    "validate_connection",
)

#: The named types and constants D-02 puts on the surface alongside them, plus
#: ``ConnectionDiagnostics``, which DIAG-01 forces: ``validate_connection`` may
#: not return a bare boolean, so its result type has to be nameable by anyone
#: annotating a call to it.
_PUBLISHED_TYPES = (
    "ReveniumExportHandle",
    "ReveniumConfig",
    "ConnectionDiagnostics",
    "DEFAULT_OTLP_TRACES_ENDPOINT",
)


def _expected_constant_names() -> set[str]:
    """Derive the 21 constant names from the 21 keys, by the documented rule.

    ``attributes.py`` states the rule — dotted suffix, uppercased, dots to
    underscores, ``REVENIUM_`` prefix — and this recomputes it rather than
    trusting a transcription.
    """
    return {
        "REVENIUM_" + key.removeprefix("revenium.").replace(".", "_").upper()
        for key in REVENIUM_ATTRIBUTE_KEYS
    }


def test_the_six_public_callables_import_flat_from_the_package() -> None:
    """D-01: the published import path is the top-level package, not a submodule."""
    # Imported here rather than at module scope: the import statement itself is
    # what this test asserts, and at module scope a failure would be a
    # collection error rather than a named failing test.
    from revenium_mlflow import (
        ReveniumAttributionSpanProcessor,
        attribution,
        configure_dual_export,
        meter_tool_span,
        report_job_outcome,
        validate_connection,
    )

    assert all(
        obj is not None
        for obj in (
            configure_dual_export,
            attribution,
            ReveniumAttributionSpanProcessor,
            meter_tool_span,
            report_job_outcome,
            validate_connection,
        )
    )


def test_every_name_in_all_resolves_on_the_package() -> None:
    """An unresolvable entry breaks ``import *`` at import time, for everyone."""
    missing = [name for name in revenium_mlflow.__all__ if not hasattr(revenium_mlflow, name)]
    assert missing == []


def test_all_contains_no_duplicates() -> None:
    """A duplicate is harmless at runtime and a reliable sign of a bad merge."""
    listed = list(revenium_mlflow.__all__)
    duplicates = sorted({name for name in listed if listed.count(name) > 1})
    assert duplicates == []


def test_all_carries_the_six_callables_and_the_published_types() -> None:
    """D-02's surface, stated as membership rather than as a count."""
    listed = set(revenium_mlflow.__all__)
    assert set(_PUBLIC_CALLABLES) <= listed
    assert set(_PUBLISHED_TYPES) <= listed
    assert "__version__" in listed


def test_all_carries_the_whole_exception_hierarchy() -> None:
    """Derived from ``errors.__all__`` so a seventh exception cannot be forgotten."""
    assert set(errors.__all__) <= set(revenium_mlflow.__all__)


def test_all_carries_the_twenty_one_attribute_key_constants() -> None:
    """Users must never hand-type a key string the backend would silently drop."""
    expected = _expected_constant_names()
    assert len(expected) == 21
    listed = set(revenium_mlflow.__all__)
    assert expected <= listed
    assert {"REVENIUM_ATTRIBUTE_KEYS", "ATTRIBUTE_CAPS"} <= listed


def test_wildcard_import_binds_exactly_the_names_in_all() -> None:
    """A real wildcard import, not ``__all__`` read back to itself.

    Reading the list twice would prove only that a list equals itself. Executing
    the import is what proves the list and the module agree.
    """
    namespace: dict[str, Any] = {}
    # ``exec`` on a fixed literal, which is the only way to run a wildcard
    # import inside a function and observe exactly what it bound.
    exec("from revenium_mlflow import *", namespace)
    bound = set(namespace) - {"__builtins__"}
    assert bound == set(revenium_mlflow.__all__)


def test_importing_the_package_loads_neither_mlflow_nor_the_compat_module() -> None:
    """PKG-09 and D-12, checked in a clean interpreter rather than this one."""
    probe = (
        "import sys; import revenium_mlflow; "
        "print('mlflow' in sys.modules, 'revenium_mlflow._compat' in sys.modules)"
    )
    # Fixed argv, no shell, no interpolated input.
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    assert result.stdout.strip() == "False False", result.stderr


def test_the_metering_package_never_imports_the_tracing_package() -> None:
    """The other direction of the separation asserted in the tracing tests.

    Parsed rather than grepped, for the same reason: these modules' docstrings
    describe the rule, and a textual search cannot tell the description from a
    violation.
    """
    offenders: list[str] = []
    for source_path in sorted(_METERING_ROOT.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{source_path.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("revenium_mlflow.tracing")
                ]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                relative_to_tracing = node.level > 0 and module.split(".")[0] == "tracing"
                if module.startswith("revenium_mlflow.tracing") or relative_to_tracing:
                    offenders.append(f"{source_path.name}: from {'.' * node.level}{module}")
    assert offenders == []
