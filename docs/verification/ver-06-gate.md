# VER-06 — formatting, linting, and strict type checking, behind a gate that can fail

Captured evidence for Phase 01 Plan 02. Every block below is the verbatim stdout and stderr of the
command shown above it, run on this machine in one session against the working tree at the commit
this file is committed in.

**What this file has to prove.** VER-06 asks for proof that linting, formatting, and type checking
pass. A green transcript alone does not establish that, because a check configured so it cannot fail
also produces a green transcript. D-08 was chosen against exactly that shape: the sibling CI this
repository inherits its conventions from runs its substantive lint invocation with `--exit-zero`,
and never invokes its type checker at all. So the load-bearing artifact here is section 3 — the gate
going **red**, with a non-zero exit status, against a violation planted on purpose and then
reverted.

**Scope and boundaries.**

- **No CI has run.** This repository has no CI workflow yet — one is written in plan 01-07. Every
  transcript below was produced by running `bash scripts/check.sh` locally. Nothing here should be
  read as a CI result, a release, or a publication.
- No command reads or prints an environment variable, and no credential is set or referenced. The
  output is tool versions, file paths, and rule codes.
- No command invokes bare `python3`. The system `python3` on this machine is 3.9.6, **below** the
  project floor of 3.10, so the gate resolves its interpreter as `.venv/bin/python` and runs every
  tool through it in module form. Each transcript opens with that interpreter printing its own
  version, so the interpreter every subsequent line ran under is part of the evidence rather than an
  assumption.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`.

---

## 0. Toolchain and the source assertions on the gate itself

The first two commands establish which tool versions produced everything below. The rest assert
properties of `scripts/check.sh` and `pyproject.toml` mechanically rather than by reading them —
that the gate aborts on the first failure, that no tool escapes the pinned interpreter, and that no
second configuration file exists anywhere that could shadow the settings in `pyproject.toml`.

```console
### .venv/bin/ruff --version
ruff 0.16.6
### .venv/bin/mypy --version
mypy 2.3.1 (compiled: yes)
### test -x scripts/check.sh && head -5 scripts/check.sh | grep -c 'set -euo pipefail'
1
### grep -cE '"\$PY" -m (ruff|mypy|pytest)' scripts/check.sh
4
### grep -vE '^[[:space:]]*#' scripts/check.sh | grep -nE '^[[:space:]]*(ruff|mypy|pytest)([[:space:]]|$)' | wc -l
       0
### grep -Ec '^\[tool\.(black|isort|flake8)\]' pyproject.toml
0
### test ! -e setup.cfg && test ! -e .flake8 && test ! -e mypy.ini && test ! -e ruff.toml && echo NO_STRAY_CONFIG
NO_STRAY_CONFIG
```

**What this proves.** `set -euo pipefail` is present within the first five lines, so any non-zero
exit aborts the whole run. All four tools — the format check, the lint run, the type check, and the
test run — are invoked as `"$PY" -m …`, and the fourth command shows that, once comment lines are
filtered out, **zero** statements in the script begin with a bare `ruff`, `mypy`, or `pytest` PATH
lookup. That matters because `bash scripts/check.sh` is called from roughly fifteen verify commands
across this phase without `.venv` ever being activated; a PATH lookup would resolve to whatever
global tool the machine carries, the type checker could run under an interpreter other than the 3.10
that `python_version = "3.10"` declares, and this file would become unattributable. The last two
commands show the toolchain is ruff plus mypy and nothing else (D-05): no `[tool.black]`,
`[tool.isort]`, or `[tool.flake8]` table, and no `setup.cfg`, `.flake8`, `mypy.ini`, or `ruff.toml`
that could shadow the settings the gate reads.

---

## 1. The gate is green on the clean tree

```console
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
13 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 1 source file
### .venv/bin/python -m pytest -q
.....                                                                    [100%]
5 passed in 0.01s
### all checks passed
exit status: 0
```

**What this proves.** One command runs the format check, the lint run, the strict type check, and
the test suite, in that order, under Python 3.10.20, and exits 0. All four sub-commands are visible
in the output, so none was skipped. This is the "linting, formatting, and type checking pass" half
of VER-06 — and on its own it is worth very little, which is what sections 2 and 3 exist to fix.

---

## 2. The gate goes red — the format check

A violation was planted on purpose in `src/revenium_mlflow/__init__.py`: the assignment to
`_FALLBACK_VERSION` was respaced so the formatter would rewrite it, and `__version__` was annotated
`int` while still being assigned a `str`, which strict type checking must reject.

```console
### git --no-pager diff -- src/revenium_mlflow/__init__.py
-_FALLBACK_VERSION = "0.1.0"
+_FALLBACK_VERSION   =    "0.1.0"

 try:
-    __version__ = _version("revenium-mlflow")
+    __version__: int = _version("revenium-mlflow")
```

```console
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
unformatted: File would be reformatted
  --> src/revenium_mlflow/__init__.py:24:19
   |
23 | #: ``tests/unit/test_package_metadata.py`` whenever a distribution is present.
   - _FALLBACK_VERSION   =    "0.1.0"
24 + _FALLBACK_VERSION = "0.1.0"
   |

1 file would be reformatted, 12 files already formatted
exit status: 1
```

**What this proves.** The gate **fails the run**: exit status 1, not 0. It also proves the abort is
immediate — the lint run, the type check, and the test suite never executed, because `set -e` ended
the script at the first non-zero exit. This is the specific behaviour D-08 requires and that
`--exit-zero` destroys.

---

## 3. The gate goes red — the strict type check, independently

The first red run stopped at the format check, so it says nothing about whether the type check can
fail. To isolate that, the formatting violation was corrected with `ruff format` while the
contradictory annotation was left in place, and the gate was run again.

```console
### .venv/bin/python -m ruff format src/revenium_mlflow/__init__.py
1 file reformatted
### git --no-pager diff -- src/revenium_mlflow/__init__.py
 try:
-    __version__ = _version("revenium-mlflow")
+    __version__: int = _version("revenium-mlflow")
```

```console
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
13 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
src/revenium_mlflow/__init__.py:27: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]
src/revenium_mlflow/__init__.py:29: error: Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]
Found 2 errors in 1 file (checked 1 source file)
exit status: 1
```

**What this proves.** The strict type check fails the run on its own, with a non-zero exit status,
after the format check and the lint run have both passed. Both halves of the gate are therefore
independently armed — a single red transcript from the first failing tool could not have shown that.
It also confirms mypy is genuinely running in strict mode against this package: the annotation
contradicts an inferred `str` at both assignment sites and both are reported.

---

## 4. The violation is reverted and the gate is green again

```console
### git checkout -- src/revenium_mlflow/__init__.py
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
13 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 1 source file
### .venv/bin/python -m pytest -q
.....                                                                    [100%]
5 passed in 0.01s
### all checks passed
exit status: 0
```

```console
### git status --porcelain src/revenium_mlflow/__init__.py | wc -l
       0
```

**What this proves.** The planted violation left nothing behind: the working tree matches the commit
again, and the gate returns to exit 0 with all four sub-commands running. Read together, sections 1
through 4 are a green/red/green cycle, which is the only sequence that establishes both halves of
what VER-06 asks — that the checks pass, *and* that passing means something.

---

## Notes

- The gate surfaced two findings in code written in plan 01-01 the first time it ran: an unsorted
  import block in `src/revenium_mlflow/__init__.py` (`I001`) and a Yoda condition in
  `tests/unit/test_package_metadata.py` (`SIM300`). Both were fixed with `ruff check --fix` and are
  part of the same commit as this gate. They are recorded here because a gate whose first run is
  green on code written before it existed would be suspicious, not reassuring.
- `mypy --strict` needed no per-module override and no `ignore_missing_imports`. The package imports
  only `importlib.metadata` from the standard library today. When it begins importing `mlflow` and
  `opentelemetry`, any distribution that ships no type information must be handled with the
  narrowest possible per-module override, named here at that time — never by relaxing this package's
  own strictness.
- **`ruff format` counts Markdown files too, so the file count in these transcripts is one lower
  than a re-run will show.** ruff 0.16 formats Python code blocks embedded in Markdown, and this
  evidence file is Markdown — it did not exist when sections 1 through 4 were captured, so those
  transcripts read `13 files already formatted` while a run today reads `14`. Verified directly: a
  scratch Markdown file containing a fenced `python` block with `x  =  1` makes
  `ruff format --check` report `1 file would be reformatted` and exit 1. The practical consequence
  is that Python examples inside documentation are format-gated on the same terms as the package
  itself. The blocks in this file are fenced `console`, not `python`, so none of the captured
  command output is reformatted.
- The test suite is included in the gate deliberately. VER-06 covers formatting, linting, and type
  checking, but a single command that runs three of the four things a contributor must not break is
  a command people learn to trust incompletely.
