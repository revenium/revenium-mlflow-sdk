#!/usr/bin/env bash
set -euo pipefail
# ---------------------------------------------------------------------------
# scripts/version_matrix.sh — the VER-07 version matrix, and the single source
# of truth for it.
#
# `.github/workflows/version-matrix.yml` invokes this script instead of
# restating the matrix in YAML (D-13). One definition means a CI run and a
# local run cannot drift, and it means the matrix is runnable — and therefore
# auditable — on a developer's machine today, which a workflow file alone is
# not. The authoritative VER-07 evidence is the captured local transcript at
# docs/verification/ver-07-version-matrix.md. No CI has executed in this
# project.
#
# Four legs (D-16): three MLflow versions on the 3.10 floor interpreter, plus
# the newest MLflow on 3.14. That guards both risky edges — the oldest
# supported syntax and the most constrained resolver target, and an interpreter
# well ahead of the floor — without paying for a full cross-product.
#
# The MLflow pins are resolved at run time rather than hardcoded (D-15). Only
# the floor is a literal, because the floor is a claim this project makes in
# pyproject.toml rather than an observation about what the index holds. The
# middle leg is the median release at or above the floor and below 4, so it
# moves as MLflow ships; today it reaches into 3.15.1 and 3.15.2, which the
# research bisection recorded as never individually exercised end to end.
#
# Interpreters are pinned through `uv venv --python`, never inherited. The
# system python3 on the development machine is 3.9.6, below this project's
# floor, so an unpinned floor leg would silently test a different runtime than
# the one it claims (threat T-01-42). Each leg prints the interpreter it
# actually ran under, and asserts that both the interpreter minor version and
# the resolved mlflow.__version__ are the ones the leg exists to test. A leg
# that resolved something else fails rather than reporting a version it did not
# run — a matrix leg that silently drops or silently substitutes is the whole
# failure mode this file is written against (threat T-01-40, T-01-SC).
#
# Every leg runs in a throwaway environment under a fresh mktemp root, created
# with --clear and deleted when the leg ends, so no leg can inherit another's
# resolution. No leg sets an endpoint or a credential variable for Revenium,
# for a customer environment, or for any hosted service. Every leg disables
# MLflow's own outbound telemetry and its agent hint, so no leg makes an
# outbound call on MLflow's behalf. The only network traffic a leg generates is
# package download from the index uv is configured to use.
#
# The lockfile at the repository root is deliberately untracked and ignored
# (see .gitignore). That is load-bearing here: the legs resolve against the
# floors declared in pyproject.toml, which is exactly what this matrix exists
# to exercise. `uv pip install` does not read a lockfile, so a stale one cannot
# pin a leg today — but a future rewrite onto `uv sync` would, and would turn
# four independent resolutions into four copies of one.
#
# Usage:
#   bash scripts/version_matrix.sh                      # all four legs
#   bash scripts/version_matrix.sh --legs floor         # one leg
#   bash scripts/version_matrix.sh --legs floor,newest  # a subset
#
# Exit status is non-zero if any attempted leg failed.
# ---------------------------------------------------------------------------

cd "$(dirname "${BASH_SOURCE[0]}")/.."

FLOOR_PYTHON="3.10"
LATEST_PYTHON="3.14"
FLOOR_MLFLOW="3.15.0"

ALL_LEGS=(floor middle newest newest-py314)

usage() {
    cat >&2 <<USAGE
usage: bash scripts/version_matrix.sh [--legs NAME[,NAME...]]

legs: ${ALL_LEGS[*]}
  floor         mlflow ${FLOOR_MLFLOW} on Python ${FLOOR_PYTHON}
  middle        the median mlflow 3.x at or above the floor, on Python ${FLOOR_PYTHON}
  newest        the newest mlflow 3.x, on Python ${FLOOR_PYTHON}
  newest-py314  the newest mlflow 3.x, on Python ${LATEST_PYTHON}
USAGE
}

SELECTED=()
while [ $# -gt 0 ]; do
    case "$1" in
        --legs)
            [ $# -ge 2 ] || { echo "version_matrix: --legs needs a value" >&2; usage; exit 2; }
            IFS=',' read -r -a SELECTED <<<"$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "version_matrix: unrecognised argument '$1'" >&2
            usage
            exit 2
            ;;
    esac
done

if [ ${#SELECTED[@]} -eq 0 ]; then
    SELECTED=("${ALL_LEGS[@]}")
fi

for name in "${SELECTED[@]}"; do
    known=0
    for candidate in "${ALL_LEGS[@]}"; do
        [ "$name" = "$candidate" ] && known=1
    done
    if [ "$known" -ne 1 ]; then
        echo "version_matrix: unknown leg '$name'" >&2
        usage
        exit 2
    fi
done

command -v uv >/dev/null 2>&1 || {
    echo "version_matrix: uv is not on PATH. This matrix is uv-driven (D-14)." >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Resolve the three MLflow pins before any leg runs, and echo them, so the
# transcript records which releases were actually exercised on the run date.
#
# The pins are read from the package index's release list. `uv pip index
# versions` does not exist in uv 0.11.17 — the version this project is
# developed against — so the enumeration runs under a uv-provisioned
# interpreter with `uv run --no-project` and the standard library, adding no
# dependency (D-14). Only the resolution *list* comes from here; every actual
# install below is performed by uv, and every leg re-reads the version from the
# interpreter that ran it.
# ---------------------------------------------------------------------------

echo "### resolving mlflow pins"

PIN_LINES=$(uv run --no-project --python "$FLOOR_PYTHON" --quiet python - "$FLOOR_MLFLOW" <<'PY'
import json
import re
import sys
import urllib.request

INDEX_URL = "https://pypi.org/pypi/mlflow/json"
FINAL_3X = re.compile(r"3\.\d+\.\d+")

floor_literal = sys.argv[1]
floor_parts = tuple(int(part) for part in floor_literal.split("."))

with urllib.request.urlopen(INDEX_URL, timeout=60) as response:
    payload = json.load(response)

candidates = []
for raw, files in payload["releases"].items():
    # A release with no files, or one whose every file is yanked, is not
    # installable; pinning to it would fail the leg for a reason that has
    # nothing to do with this SDK.
    if not FINAL_3X.fullmatch(raw) or not files:
        continue
    if all(entry.get("yanked") for entry in files):
        continue
    parts = tuple(int(part) for part in raw.split("."))
    if parts >= floor_parts:
        candidates.append((parts, raw))

if not candidates:
    sys.exit(f"version_matrix: the index holds no installable mlflow 3.x at or above {floor_literal}")

candidates.sort()
print(floor_literal)
print(candidates[len(candidates) // 2][1])
print(candidates[-1][1])
print(" ".join(raw for _, raw in candidates), file=sys.stderr)
PY
) || {
    echo "version_matrix: could not resolve the mlflow release list from the index" >&2
    exit 1
}

MIDDLE_MLFLOW=$(echo "$PIN_LINES" | sed -n '2p')
NEWEST_MLFLOW=$(echo "$PIN_LINES" | sed -n '3p')

if [ -z "$MIDDLE_MLFLOW" ] || [ -z "$NEWEST_MLFLOW" ]; then
    echo "version_matrix: pin resolution returned an incomplete result" >&2
    exit 1
fi

echo "pin floor   mlflow ${FLOOR_MLFLOW}   (literal — the floor this project declares)"
echo "pin middle  mlflow ${MIDDLE_MLFLOW}   (resolved: median 3.x at or above the floor)"
echo "pin newest  mlflow ${NEWEST_MLFLOW}   (resolved: newest 3.x on the index)"
echo

MATRIX_TMP=$(mktemp -d "${TMPDIR:-/tmp}/mlflow-version-matrix.XXXXXX")
cleanup() { rm -rf "$MATRIX_TMP"; }
trap cleanup EXIT

ATTEMPTED=0
PASSED=0
FAILED_LEGS=()

# run_leg NAME PYTHON_VERSION MLFLOW_PIN
#
# Returns non-zero on any failure, having printed the failing command's output
# verbatim under the leg banner. The caller records the failure and continues
# to the remaining legs: a leg that cannot resolve is a finding, not a reason
# to abandon the run.
run_leg() {
    local name="$1" python_version="$2" mlflow_pin="$3"
    local leg_root="$MATRIX_TMP/$name"
    local venv="$leg_root/venv"
    local py="$venv/bin/python"
    local log="$leg_root/install.log"
    local status=0

    mkdir -p "$leg_root"

    echo "==========================================================================="
    echo "=== leg ${name}: mlflow ${mlflow_pin} on Python ${python_version}"
    echo "==========================================================================="

    if ! uv venv --python "$python_version" --clear "$venv" >"$log" 2>&1; then
        echo "--- FAILED: uv venv --python ${python_version} --clear (verbatim output)"
        cat "$log"
        rm -rf "$leg_root"
        return 1
    fi

    if ! uv pip install --quiet --python "$py" -e ".[dev]" >"$log" 2>&1; then
        echo "--- FAILED: uv pip install -e \".[dev]\" (verbatim output)"
        cat "$log"
        rm -rf "$leg_root"
        return 1
    fi

    if ! uv pip install --quiet --python "$py" "mlflow==${mlflow_pin}" >"$log" 2>&1; then
        echo "--- FAILED: uv pip install mlflow==${mlflow_pin} (verbatim output)"
        cat "$log"
        rm -rf "$leg_root"
        return 1
    fi

    # The leg's environment. `env -u` strips the ambient virtualenv and import
    # path so nothing outside this leg's own interpreter can satisfy an import.
    # The two MLflow variables silence its outbound telemetry and its agent
    # hint. An explicit tracking URI is set because MLflow's file store raises
    # unless it is opted into; pointing it at this leg's throwaway directory
    # keeps a stray write inside the temporary root. No endpoint or credential
    # for any hosted service is set anywhere in this function.
    local leg_env=(
        env -u VIRTUAL_ENV -u PYTHONPATH -u PYTHONHOME
        MLFLOW_DISABLE_TELEMETRY=true
        MLFLOW_DISABLE_AGENT_HINT=1
        MLFLOW_TRACKING_URI="sqlite:///${leg_root}/tracking.db"
    )

    echo "--- interpreter and resolved mlflow version"
    if ! "${leg_env[@]}" "$py" - "$python_version" "$mlflow_pin" <<'PY'
import sys

import mlflow

expected_python, expected_mlflow = sys.argv[1], sys.argv[2]
observed_python = ".".join(str(part) for part in sys.version_info[:2])

print(f"interpreter         Python {sys.version.split()[0]}")
print(f"sys.executable      {sys.executable}")
print(f"mlflow.__version__  {mlflow.__version__}")
print(f"resolved            mlflow {mlflow.__version__} on Python {sys.version.split()[0]}")
print(f"mlflow.__file__     {mlflow.__file__}")

# The leg asserts what it claims. Without this, an environment that resolved a
# different interpreter or a different MLflow would print a version and report
# success, and the transcript would document a run that never happened.
if observed_python != expected_python:
    sys.exit(f"LEG MISMATCH: expected Python {expected_python}, ran under {observed_python}")
if mlflow.__version__ != expected_mlflow:
    sys.exit(f"LEG MISMATCH: expected mlflow {expected_mlflow}, resolved {mlflow.__version__}")
PY
    then
        echo "--- FAILED: the leg did not run under the interpreter and mlflow it claims"
        status=1
    fi

    if [ "$status" -eq 0 ]; then
        echo "--- test suite"
        if ! "${leg_env[@]}" "$py" -m pytest -q; then
            echo "--- FAILED: the test suite did not pass on this leg"
            status=1
        fi
    fi

    if [ "$status" -eq 0 ]; then
        echo "--- capability probe"
        if ! "${leg_env[@]}" "$py" - <<'PY'
import revenium_mlflow
from revenium_mlflow import _compat

# Printed so the transcript records which copy of this SDK the leg exercised.
# The legs install the working tree as an editable, so this path is the source
# under test rather than a previously built copy.
print(f"revenium_mlflow.__file__  {revenium_mlflow.__file__}")
record = _compat.probe()
print(repr(record))
PY
        then
            echo "--- FAILED: the capability probe raised on this leg"
            status=1
        fi
    fi

    rm -rf "$leg_root"
    return "$status"
}

for name in "${SELECTED[@]}"; do
    case "$name" in
        floor)        leg_python="$FLOOR_PYTHON";  leg_mlflow="$FLOOR_MLFLOW" ;;
        middle)       leg_python="$FLOOR_PYTHON";  leg_mlflow="$MIDDLE_MLFLOW" ;;
        newest)       leg_python="$FLOOR_PYTHON";  leg_mlflow="$NEWEST_MLFLOW" ;;
        newest-py314) leg_python="$LATEST_PYTHON"; leg_mlflow="$NEWEST_MLFLOW" ;;
        *)            echo "version_matrix: unhandled leg '$name'" >&2; exit 2 ;;
    esac

    ATTEMPTED=$((ATTEMPTED + 1))
    if run_leg "$name" "$leg_python" "$leg_mlflow"; then
        PASSED=$((PASSED + 1))
        echo "--- leg ${name}: PASSED"
    else
        FAILED_LEGS+=("$name")
        echo "--- leg ${name}: FAILED"
    fi
    echo
done

echo "==========================================================================="
echo "### summary: ${PASSED} of ${ATTEMPTED} legs passed"
if [ ${#FAILED_LEGS[@]} -gt 0 ]; then
    echo "### failed legs: ${FAILED_LEGS[*]}"
    exit 1
fi
echo "### every attempted leg passed"
