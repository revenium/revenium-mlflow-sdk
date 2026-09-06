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

import re
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

# The prose claim about MLflow's JSON encoding, assembled from fragments rather
# than written as one string literal. The fragmentation is load-bearing, not
# fastidiousness: a scanner whose own source matched its pattern would itself
# become a further statement of the claim it polices, which would make every
# count over the tree off by one and make a plain `grep` for the sentence
# disagree with the test that owns it. Do not tidy this back into a literal.
_QUOTING_CLAIM_PHRASE = " ".join(("characters", "longer", "than", "it", "looks"))

# The count word held here as this file's own independent copy, rather than
# imported or derived from any module under test, so the prose and the check
# cannot be moved together in a single edit.
_EXPECTED_QUOTE_COUNT_WORD = "two"

# The word immediately preceding the claim is what the check reads.
_QUOTING_CLAIM_PATTERN = re.compile(r"(\w+) " + _QUOTING_CLAIM_PHRASE)

# The non-vacuity floor: the three docstrings that state the claim today. A
# fourth statement agreeing with the assertion is not a failure; a disagreeing
# one is, and a scan that reached nothing at all is.
_QUOTING_CLAIM_MINIMUM = 3

# Scanned by name rather than by walking the whole repository root, which would
# reach `.venv`. No directory is excluded from either tree.
_QUOTING_CLAIM_TREES = ("src", "tests")


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


@pytest.mark.unit
def test_every_statement_of_the_quoting_arithmetic_agrees_with_the_assertion() -> None:
    """Prose here is read as specification, so an arithmetic claim in it is checked.

    The same factual claim about MLflow's JSON-encoded wire form was stated with
    one figure in three files -- the module docstrings of
    ``src/revenium_mlflow/tracing/_spanattrs.py`` and ``tests/fixtures/spans.py``
    and the docstring of ``test_the_fixture_carries_mlflows_json_encoding`` --
    and asserted with a different one in a fourth,
    ``test_the_encoded_form_is_two_characters_longer_than_the_bare_form`` in
    ``tests/unit/test_spanattrs.py``, which is the one that is right. It was
    wrong in the single paragraph explaining the most load-bearing decode
    behaviour in the phase, and it was presented as arithmetic. This check reds
    if a further copy disagrees with the assertion again.

    The minimum-match assertion is the non-vacuity control this repository's
    house style requires: a scan that reached no file satisfies the agreement
    assertion exactly as well as a tree carrying no disagreement does.
    """
    offenders: list[str] = []
    matches = 0
    for tree in _QUOTING_CLAIM_TREES:
        for path in sorted((REPO_ROOT / tree).rglob("*.py")):
            body = path.read_text(encoding="utf-8")
            for match in _QUOTING_CLAIM_PATTERN.finditer(body):
                matches += 1
                word = match.group(1)
                if word != _EXPECTED_QUOTE_COUNT_WORD:
                    line = body.count("\n", 0, match.start()) + 1
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}:{word}")

    assert not offenders, (
        "statements of the quoting arithmetic disagree with "
        f"{_EXPECTED_QUOTE_COUNT_WORD!r}: {sorted(offenders)}"
    )
    assert matches >= _QUOTING_CLAIM_MINIMUM, (
        f"found {matches} statements of the quoting claim, expected at least "
        f"{_QUOTING_CLAIM_MINIMUM}; a scan that reaches nothing proves nothing"
    )
