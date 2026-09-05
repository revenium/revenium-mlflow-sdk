# VER-08 — the private-access wall, shown detecting a real breach

Captured evidence for Phase 01 Plan 03. Every block below is the verbatim stdout and stderr of the
command shown above it, run on this machine in one session against the working tree at the commit
this file is committed in.

**What this file has to prove.** VER-08 asks for a private-access wall around MLflow and
OpenTelemetry internals: everything the SDK ever needs from them confined to
`src/revenium_mlflow/_compat.py`, and nothing anywhere else. At the `mlflow>=3.15.0,<4` floor the
compat module itself reaches for no private name, so the shipped package scans completely clean
(D-09). That is the good outcome and it is also the problem: a clean scan is exactly what a wall
that does not work produces. So the load-bearing sections here are 3 and 4 — each of the two
enforcement mechanisms shown going **red**, on its own, against a private access planted on purpose
in the shipped package and then reverted.

**Scope and boundaries.**

- **No CI has run.** This repository has no CI workflow yet — one is written in plan 01-07. Every
  transcript below was produced by running the command shown, locally. Nothing here should be read
  as a CI result, a release, a publication, or a statement about production readiness.
- No command reads or prints an environment variable, and no credential is set or referenced. The
  output is tool versions, file paths, rule codes, and one assertion failure.
- No command contacts Revenium, a customer environment, or any hosted endpoint. The one command
  that imports MLflow is the test suite, and `tests/conftest.py` disables MLflow's own outbound
  telemetry for the whole session before any test imports it.
- Every command runs under `.venv/bin/python`, the same interpreter `scripts/check.sh` resolves as
  `PY`. The system `python3` on this machine is 3.9.6, below this project's 3.10 floor, so a bare
  PATH lookup would make these transcripts unattributable.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`. ruff 0.16.6.

---

## Why five runs, and why two of them are isolated

`scripts/check.sh` runs under `set -euo pipefail` (D-08), so it aborts at the first non-zero
command, and its lint step precedes its test step. A planted private access fails the lint step —
which means the test step **never executes**, and the failing wall test never appears in the output.

A single aggregate transcript therefore *cannot* contain both findings. This is not a limitation to
work around; it is the gate behaving the way D-08 requires. An acceptance criterion demanding both
findings from one run would leave an author one plausible-looking move: weaken `set -e`, or append
`|| true` to the lint step, so the run continues to the tests. That would destroy the property the
gate exists for, in order to produce a nicer-looking piece of evidence about the gate.

So each mechanism is recorded on its own run, and the aggregate gate gets a third run of its own:

| Section | Command | Proves |
|---|---|---|
| 1 | `bash scripts/check.sh` | The tree is clean before anything is planted. |
| 3 | `.venv/bin/python -m ruff check .` | The **lint half** fires, with a rule code and a `file:line`. |
| 4 | `.venv/bin/python -m pytest tests/unit/test_private_access_wall.py` | The **AST half** fires, independently of ruff. |
| 5 | `bash scripts/check.sh` | The **aggregate gate** goes red, and aborts at the first failure. |
| 6 | `bash scripts/check.sh` | The plant left nothing behind. |

Section 2 is the plant itself and runs no gate. Sections 3 and 4 are the reason sections 1 and 6
are not vacuous.

---

## 1. The wall is green on the clean tree

```console
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
20 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 3 source files
### .venv/bin/python -m pytest -q
................                                                         [100%]
16 passed in 1.12s
### all checks passed
exit status: 0
```

**What this proves.** On the clean tree the lint rules find nothing and all 16 tests pass, three of
them the wall tests. Read alone, this establishes only that the package currently contains no
private access — not that anything would notice if it did.

---

## 2. The planted violation

A real private access was added to `src/revenium_mlflow/__init__.py`: MLflow imported at module
scope, and one underscore-prefixed attribute read off it. `_active_span_processor` is not invented
for this exercise. It is the private OpenTelemetry state MLflow itself reaches into, and the state
Phase 4 will be tempted to read in order to detect processor eviction (recorded as OI-01). The
shipped package `__init__` is the right place to plant it: it is the module a breach would most
plausibly appear in, and it is covered by neither exemption.

```console
### git --no-pager diff -- src/revenium_mlflow/__init__.py
diff --git a/src/revenium_mlflow/__init__.py b/src/revenium_mlflow/__init__.py
index e8df801..1b68261 100644
--- a/src/revenium_mlflow/__init__.py
+++ b/src/revenium_mlflow/__init__.py
@@ -29,3 +29,9 @@ except PackageNotFoundError:  # pragma: no cover - source-tree run without insta
     __version__ = _FALLBACK_VERSION

 __all__ = ["__version__"]
+
+
+# --- PLANTED VIOLATION (VER-08 evidence) — reverted immediately after capture ---
+import mlflow
+
+_PLANTED = mlflow.tracing._active_span_processor
```

That single edit trips both halves of the wall.

---

## 3. The lint half goes red, isolated

```console
### .venv/bin/python -m ruff check .; echo "exit status: $?"
E402 Module level import not at top of file
  --> src/revenium_mlflow/__init__.py:35:1
   |
34 | # --- PLANTED VIOLATION (VER-08 evidence) — reverted immediately after capture ---
35 | import mlflow
   | ^^^^^^^^^^^^^
36 |
37 | _PLANTED = mlflow.tracing._active_span_processor
   |
help: Move module level imports to top of file

SLF001 Private member accessed: `_active_span_processor`
  --> src/revenium_mlflow/__init__.py:37:12
   |
35 | import mlflow
36 |
37 | _PLANTED = mlflow.tracing._active_span_processor
   |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Found 2 errors.
exit status: 1
```

**What this proves.** The declarative half of the wall fires with a non-zero exit status, and the
finding carries what a person needs to act on it: the rule code `SLF001`, the name of the private
member, and the locator `src/revenium_mlflow/__init__.py:37:12`. This is the half that reaches an
author in their editor, before a commit exists.

`E402` is incidental — the plant put an import below other statements. It is left in the transcript
rather than tidied away, because editing captured output to make it read better is the habit this
whole file exists to guard against.

The companion rule `TID251` does not appear here, because this plant is an attribute read rather
than a banned import. It is separately confirmed to fire: `from mlflow.tracing.provider import x`
in a shipped module produces ``TID251 `mlflow.tracing.provider` is banned`` with the message
routing the author to the compat module.

---

## 4. The AST half goes red, isolated and independently

Section 3 stopped at ruff. It says nothing about whether the test can fail, and the test is the
half that matters more over time: a lint rule can be switched off by adding one string to
`select`'s neighbours or one `# noqa`, whereas deleting a failing test is a larger and more
obviously deliberate act.

```console
### .venv/bin/python -m pytest tests/unit/test_private_access_wall.py -q --tb=line; echo "exit status: $?"
.F.                                                                      [100%]
=================================== FAILURES ===================================
E   AssertionError: {'/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py': ['/Users/johnde...an_processor'], '/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/errors.py': []}
    assert not True
     +  where True = any(dict_values([['/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py:37 _active_span_processor'], []]))
     +    where dict_values([['/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py:37 _active_span_processor'], []]) = <built-in method values of dict object at 0x10930a680>()
     +      where <built-in method values of dict object at 0x10930a680> = {'/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py': ['/Users/johnde...an_processor'], '/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/errors.py': []}.values
/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/tests/unit/test_private_access_wall.py:183: AssertionError: {'/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py': ['/Users/johnde...an_processor'], '/Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/errors.py': []}
=========================== short test summary info ============================
FAILED tests/unit/test_private_access_wall.py::test_no_private_access_outside_the_compat_module
1 failed, 2 passed in 0.01s
exit status: 1
```

**What this proves.** `test_no_private_access_outside_the_compat_module` fails by name, with a
non-zero exit status, and the failure message names the offending file and line —
`src/revenium_mlflow/__init__.py:37 _active_span_processor` — rather than reporting only that
something, somewhere, is wrong. The other two wall tests still pass, which is the correct result:
the control test still finds exactly two breaches in the planted fixture, and the compat module
still holds none.

The two halves are not redundant, and this is where that shows. Ruff's `SLF001` is root-blind — it
flags `obj._private` whatever `obj` is, so it catches a private read reached through a local alias
that the AST scanner, which resolves attribute chains back to an imported name, would miss. The
scanner is root-aware — it reports only accesses rooted at MLflow or OpenTelemetry, so it stays
quiet on this package's own private helpers and remains credible enough that nobody is tempted to
delete it. Neither is a superset of the other.

---

## 5. The aggregate gate goes red — and aborts at the first failure

```console
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
20 files already formatted
### .venv/bin/python -m ruff check .
E402 Module level import not at top of file
  --> src/revenium_mlflow/__init__.py:35:1
   |
34 | # --- PLANTED VIOLATION (VER-08 evidence) — reverted immediately after capture ---
35 | import mlflow
   | ^^^^^^^^^^^^^
36 |
37 | _PLANTED = mlflow.tracing._active_span_processor
   |
help: Move module level imports to top of file

SLF001 Private member accessed: `_active_span_processor`
  --> src/revenium_mlflow/__init__.py:37:12
   |
35 | import mlflow
36 |
37 | _PLANTED = mlflow.tracing._active_span_processor
   |            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Found 2 errors.
exit status: 1
```

**What this proves.** The one command a contributor runs fails the whole run on a private access,
exit status 1. It also demonstrates the abort concretely: `mypy` and `pytest` produce no output at
all, because `set -e` ended the script the moment `ruff check` returned non-zero. That absence is
the reason sections 3 and 4 had to be captured separately — the failing wall test physically cannot
appear in this transcript while the lint step is also failing.

---

## 6. The violation is reverted and the wall is green again

```console
### git checkout -- src/revenium_mlflow/__init__.py
### bash scripts/check.sh; echo "exit status: $?"
### .venv/bin/python --version
Python 3.10.20
### .venv/bin/python -m ruff format --check .
20 files already formatted
### .venv/bin/python -m ruff check .
All checks passed!
### .venv/bin/python -m mypy --strict src/revenium_mlflow
Success: no issues found in 3 source files
### .venv/bin/python -m pytest -q
................                                                         [100%]
16 passed in 0.87s
### all checks passed
exit status: 0
```

```console
### git status --porcelain src/revenium_mlflow/__init__.py | wc -l
       0
```

**What this proves.** The plant left nothing behind: the working tree matches the commit again, the
gate returns to exit 0, and all four sub-commands run.

---

## What the five runs establish together

The private-access wall is enforced twice, and both enforcements have been observed firing.

Sections 1 and 6 alone would establish only that the shipped package currently contains no private
MLflow or OpenTelemetry access — a result a scanner that detects nothing produces just as readily.
Section 3 shows the lint half rejecting a real breach with a rule code and a line number. Section 4
shows the AST half rejecting the same breach on its own, by test name, with the offending file and
line in the failure message, and independently of whether ruff ran at all. Section 5 shows the
aggregate gate carrying that rejection through to a non-zero exit, and — by the visible absence of
the type-check and test steps — shows why sections 3 and 4 had to be captured apart.

Two exemptions exist and both are visible in `pyproject.toml`:
`src/revenium_mlflow/_compat.py`, the single sanctioned boundary, and a `tests/**` glob, because
test code may use private APIs freely (OI-01) and this phase's own control fixture is nothing but
private access. The count is asserted by plan 01-03's acceptance criteria, so adding a third
exemption is a diff someone has to write on purpose and defend.

Two things this file deliberately does **not** claim: that the wall will hold against a private
access reached through a route neither mechanism models, and that any of this has run anywhere but
this machine.

---

## Notes

- The compat module is currently *permitted* private access and uses none. That is D-09, and
  `test_the_compat_module_holds_no_private_access_either` asserts it. The first genuine breach —
  Phase 4 must detect processor eviction, which MLflow performs externally on `enable()`,
  `disable()` and `set_destination()` — will therefore require editing that test, which is the
  intent: a breach should be a deliberate, reviewable act rather than one more private read
  disappearing into a module that already has several.
- `ruff format` also checks Python code blocks inside Markdown, so this file is format-gated on the
  same terms as the package. The transcripts above read `20 files already formatted`; a run today
  reads `21`, because this file did not exist when they were captured. Every block here is fenced
  `console`, not `python`, so none of the captured output is subject to reformatting.
- The planted violation was reverted with `git checkout --` on a single named path. No blanket
  working-tree reset and no `git clean` was used at any point.
