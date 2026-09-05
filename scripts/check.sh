#!/usr/bin/env bash
set -euo pipefail
# ---------------------------------------------------------------------------
# scripts/check.sh — the single hard gate for this repository.
#
# It runs, in order: format check, lint, strict type check, test suite. Any
# non-zero exit aborts the whole run. That is deliberate and it is the point.
#
# D-08: this gate is allowed to fail. The sibling CI this repository inherits
# its conventions from runs its substantive lint invocation with `--exit-zero`
# and never invokes its type checker at all, so neither can ever fail a build.
# A check that cannot go red proves nothing. `docs/verification/ver-06-gate.md`
# records this gate going red against a deliberately planted violation, which
# is the evidence that distinguishes it from that shape. Do not add
# `--exit-zero`, `|| true`, or `continue-on-error` to anything below.
#
# Every tool runs as `"$PY" -m <tool>` rather than by PATH lookup. That is
# load-bearing, not stylistic: this script is invoked as `bash scripts/check.sh`
# from roughly fifteen verify commands across this phase, always without
# activating `.venv`. A PATH lookup would resolve to whatever global tool the
# machine happens to carry, so the type checker could run under an interpreter
# other than the 3.10 that `python_version = "3.10"` in pyproject.toml declares,
# and the captured evidence would become unattributable. The system interpreter
# on the development machine is 3.9.6 — below this project's floor — so a bare
# lookup is not merely imprecise, it is potentially wrong.
#
# Override the interpreter with PY=/path/to/python. A relative override is
# resolved against the repository root, which this script cd's to first so the
# `.venv/bin/python` default holds no matter where it is invoked from.
# ---------------------------------------------------------------------------

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PY="${PY:-.venv/bin/python}"

if [ ! -x "$PY" ]; then
    echo "check.sh: no interpreter at '$PY'." >&2
    echo "check.sh: create it with 'uv venv --python 3.10 --clear .venv' then" >&2
    echo "check.sh: 'uv pip install --python .venv/bin/python -e \".[dev]\"'," >&2
    echo "check.sh: or point PY at an interpreter with the dev extra installed." >&2
    exit 1
fi

echo "### $PY --version"
"$PY" --version

echo "### $PY -m ruff format --check ."
"$PY" -m ruff format --check .

echo "### $PY -m ruff check ."
"$PY" -m ruff check .

echo "### $PY -m mypy --strict src/revenium_mlflow"
"$PY" -m mypy --strict src/revenium_mlflow

echo "### $PY -m pytest -q"
"$PY" -m pytest -q

echo "### all checks passed"
