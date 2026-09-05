"""The private-access wall, enforced independently of the linter (VER-08).

The shipped package must reach into MLflow's and OpenTelemetry's internals from
exactly one module, ``src/revenium_mlflow/_compat.py``, and at the
``mlflow>=3.15.0,<4`` floor it must not reach into them at all (D-09).

That rule is enforced twice, on purpose (D-06). Ruff's ``SLF001`` and ``TID251``
are the fast half: they fire in an editor and in a pre-commit run, which is
where a breach is cheapest to fix. This file is the slow half. Two reasons it
exists rather than being redundant:

*Lint configuration is easy to loosen in a hurry.* A ``# noqa``, one more entry
in ``per-file-ignores``, a rule quietly dropped from ``select`` — each is a
small diff under deadline pressure. Deleting a failing test is a larger and more
obviously deliberate act.

*The two mechanisms fail differently.* Ruff's ``SLF001`` is root-blind: it flags
``obj._private`` whatever ``obj`` is, so it catches a private read through a
local alias that the scanner below, which resolves attribute chains only back to
an imported name, would miss. The scanner is root-aware: it reports only
accesses rooted at MLflow or OpenTelemetry, so it produces no noise on this
package's own private helpers and stays credible enough to keep. Neither is a
superset of the other, which is the argument for keeping both.

The two helpers are module-level and named plainly because they are reused: plan
01-06's import-purity check and later phases scan the same tree.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: Package root, resolved from this file rather than from the working directory,
#: so the test means the same thing run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_ROOT = _REPO_ROOT / "src" / "revenium_mlflow"

#: The control subject. A clean scan of the package proves nothing unless the
#: same scanner is shown finding what it claims to find.
_PLANTED_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "planted_private_access.py"

#: The one exempt shipped path — the sanctioned boundary itself.
_EXEMPT_MODULE = "_compat.py"

#: Top-level packages whose internals are off limits.
_WALLED_ROOTS = frozenset({"mlflow", "opentelemetry"})


def iter_package_modules(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` file under ``root``, deepest paths included.

    Deliberately not filtered to a hand-maintained list. A module added in a
    later phase is scanned the day it lands, without anyone remembering to
    register it here.
    """
    yield from sorted(root.rglob("*.py"))


def _is_private(name: str) -> bool:
    """A single leading underscore, not a dunder.

    ``__version__`` and friends are ordinary attribute access on any object.
    Reporting them would flood the result with noise and train readers to
    ignore it.
    """
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _attribute_root(node: ast.expr) -> str | None:
    """Resolve an attribute chain back to the name it is rooted at.

    ``mlflow.tracing._active_span_processor`` resolves to ``"mlflow"``. Anything
    not rooted at a plain name — a subscript, a call result — resolves to
    ``None`` and is left to ruff's root-blind ``SLF001``.
    """
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _walled_import_paths(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the dotted paths this import statement brings in, walled ones only.

    Relative imports are skipped: ``from . import errors`` is this package
    talking to itself and can never cross the wall.
    """
    paths: list[str] = []
    if isinstance(node, ast.Import):
        paths = [alias.name for alias in node.names]
    elif node.level == 0 and node.module is not None:
        # The imported name is part of the path for this purpose, so
        # `from mlflow.tracing import _private` is caught as readily as
        # `import mlflow.tracing._private`.
        paths = [f"{node.module}.{alias.name}" for alias in node.names]
    return [path for path in paths if path.split(".")[0] in _WALLED_ROOTS]


def _bound_walled_names(tree: ast.AST) -> set[str]:
    """Collect the local names that refer to MLflow or OpenTelemetry.

    Covers the aliasing forms: ``import mlflow``, ``import mlflow as m``,
    ``import mlflow.tracing`` (which binds ``mlflow``), and
    ``from opentelemetry.sdk import trace as t``. Imports inside function
    bodies count — ``_compat.probe`` imports MLflow inside its own body by
    design, and an exemption for that shape would be a hole the size of the
    rule.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in _WALLED_ROOTS:
                    continue
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                continue
            if node.module.split(".")[0] not in _WALLED_ROOTS:
                continue
            bound.update(alias.asname or alias.name for alias in node.names)
    return bound


def scan_private_access(path: Path) -> list[str]:
    """Report every private MLflow or OpenTelemetry access in one file.

    Two kinds of finding:

    1. An underscore-prefixed attribute read whose chain is rooted at a name
       bound to MLflow or OpenTelemetry.
    2. An import whose dotted path is rooted at MLflow or OpenTelemetry and
       contains an underscore-prefixed component.

    Returns:
        One string per finding, formatted ``path:lineno symbol``, so a failure
        message points at the line rather than at the file.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bound = _bound_walled_names(tree)
    findings: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if _is_private(node.attr) and _attribute_root(node.value) in bound:
                findings.append((node.lineno, node.attr))
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for dotted in _walled_import_paths(node):
                if any(_is_private(part) for part in dotted.split(".")):
                    findings.append((node.lineno, dotted))

    return [f"{path}:{lineno} {symbol}" for lineno, symbol in sorted(findings)]


def test_the_scanner_detects_the_planted_control_subject() -> None:
    """The scanner finds what it claims to find.

    Without this, the two assertions below are satisfied equally well by a
    scanner that returns an empty list for every input — which is the specific
    way a wall like this rots.
    """
    findings = scan_private_access(_PLANTED_FIXTURE)

    assert len(findings) == 2, findings
    for finding in findings:
        path, _, rest = finding.partition(":")
        assert path.endswith("planted_private_access.py")
        assert rest.split()[0].isdigit(), f"no line number in {finding!r}"
    assert any("_active_span_processor" in finding for finding in findings)
    assert any("opentelemetry.util._once" in finding for finding in findings)


def test_no_private_access_outside_the_compat_module() -> None:
    """The wall itself: every shipped module except the one exempt path."""
    modules = [p for p in iter_package_modules(_PACKAGE_ROOT) if p.name != _EXEMPT_MODULE]

    assert modules, f"scanned nothing under {_PACKAGE_ROOT} — the walk is broken"

    breaches = {str(path): scan_private_access(path) for path in modules}
    assert not any(breaches.values()), breaches


def test_the_compat_module_holds_no_private_access_either() -> None:
    """D-09: at this floor the wall starts empty.

    The compat module is *permitted* private access and currently uses none,
    because ``mlflow>=3.15.0,<4`` exposes a public attachment point for a span
    processor. Asserting the empty state is what turns the first genuine breach
    into a visible, deliberate edit to this test rather than one more private
    read disappearing into a module that already has several.
    """
    compat = _PACKAGE_ROOT / _EXEMPT_MODULE

    assert compat.is_file(), f"{compat} is missing — the wall has no boundary module"
    assert scan_private_access(compat) == []
