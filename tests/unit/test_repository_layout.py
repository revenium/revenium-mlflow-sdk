"""The repository carries the community files the sibling convention requires.

Presence alone is a weak check — an empty ``SECURITY.md`` satisfies a file
existence test and helps nobody — so every entry is asserted non-empty, and the
licence is asserted to actually be MIT rather than merely present.

Existence is resolved by listing the parent directory rather than by
``Path.is_file()``. On a case-insensitive filesystem (the default on macOS)
``is_file()`` accepts ``readme.md`` for ``README.md``, which would pass here and
fail on the case-sensitive filesystem CI runs on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# `tomllib` entered the standard library in 3.11; this project's floor is 3.10.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
)

REQUIRED_DIRECTORIES = ("docs", "examples", "tests")

# Clauses unique enough to distinguish MIT from Apache-2.0, BSD, and the GPLs,
# all of which would satisfy a "LICENSE exists and mentions a licence" check.
MIT_MARKERS = (
    "MIT License",
    "Permission is hereby granted, free of charge",
    "without restriction, including without limitation the rights",
    'THE SOFTWARE IS PROVIDED "AS IS"',
)

# Text that would mean the file is some other licence wearing an MIT filename.
NON_MIT_MARKERS = (
    "Apache License",
    "GNU GENERAL PUBLIC LICENSE",
    "Mozilla Public License",
)


def _entries(directory: Path) -> set[str]:
    """Names in ``directory``, read case-sensitively."""
    return {entry.name for entry in directory.iterdir()}


def _pyproject() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_community_file_is_present_and_non_empty(name: str) -> None:
    """The file exists under exactly this name and carries content."""
    assert name in _entries(REPO_ROOT), f"{name} is missing from the repository root"
    path = REPO_ROOT / name
    assert path.is_file(), f"{name} exists but is not a regular file"
    assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_DIRECTORIES)
def test_convention_directory_is_present_and_populated(name: str) -> None:
    """The directory exists and holds at least one file.

    An empty ``examples/`` is the failure mode this catches: the convention is
    that the directory carries something, not that it can be created.
    """
    assert name in _entries(REPO_ROOT), f"{name}/ is missing from the repository root"
    directory = REPO_ROOT / name
    assert directory.is_dir(), f"{name} exists but is not a directory"
    files = [p for p in directory.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert files, f"{name}/ contains no files"


@pytest.mark.unit
def test_license_file_is_the_mit_license() -> None:
    """LICENSE is MIT in substance, not merely a file named LICENSE."""
    text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    missing = [marker for marker in MIT_MARKERS if marker not in text]
    assert not missing, f"LICENSE is missing MIT clauses: {missing}"
    present = [marker for marker in NON_MIT_MARKERS if marker in text]
    assert not present, f"LICENSE contains non-MIT licence text: {present}"


@pytest.mark.unit
def test_declared_license_agrees_with_the_license_file() -> None:
    """``pyproject.toml`` declares MIT, matching the file that ships with it."""
    assert _pyproject()["project"]["license"] == "MIT"
