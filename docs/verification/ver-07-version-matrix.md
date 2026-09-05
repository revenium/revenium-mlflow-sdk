# VER-07 — the version matrix, run across four interpreter-and-MLflow combinations

Captured evidence for Phase 01 Plan 07. Every block below is the verbatim stdout and stderr of the
command shown above it, run on this machine in one session against the working tree at the commit
this file is committed in.

**What this file has to prove.** VER-07 asks that the suite run against more than one MLflow and
more than one interpreter, with the resolved version printed on each leg. The research that fixed
the `mlflow>=3.15.0` floor bisected twenty releases for the presence of one symbol but never
exercised 3.15.1 or 3.15.2 end to end, and paired the package only with Python 3.10 through 3.12.
This matrix closes both gaps and keeps them closed as MLflow ships.

A matrix is unusually prone to a false pass. A leg that silently skips, resolves a different
interpreter than it names, or reuses a cached environment will print a version and report success
while testing nothing — and three false passes have already been caught in this phase, every one of
them by a deliberate plant rather than by reading code. So sections 3 and 4 are load-bearing: the
matrix shown going **red** against two planted faults, each reverted afterwards.

**Scope and boundaries.**

- **No continuous-integration service has executed anything in this project.** The workflow file at
  `.github/workflows/version-matrix.yml` was added by this same plan as provision for a future push,
  and it has never been executed here. Every transcript below was produced by running the command
  shown, locally. Nothing in this document is a statement about a hosted build, a package index, a
  tag, or readiness for deployment. The delivery boundary for this project is build artifacts only.
- No command in any leg sets an endpoint or a credential variable for Revenium, for a customer
  environment, or for any hosted service, and none is printed. Asserted mechanically in section 0.
- No leg contacts Revenium or a customer environment. Every leg sets `MLFLOW_DISABLE_TELEMETRY` and
  `MLFLOW_DISABLE_AGENT_HINT`, so no leg makes an outbound call on MLflow's behalf either. The only
  network traffic a leg generates is package download from the index uv is configured to use.
- No leg invokes bare `python3`. The system `python3` on this machine is 3.9.6, below this project's
  3.10 floor, so an inherited interpreter would make the floor leg test the wrong runtime. Every leg
  pins its interpreter through `uv venv --python` and prints the interpreter it actually ran under.

**Environment.** macOS, arm64. uv 0.11.17. Matrix run started `2026-09-05T01:53:08Z`.

---

## 0. What the runner is, and the assertions on the runner itself

`scripts/version_matrix.sh` is the single definition of the matrix (D-13). The CI workflow file
invokes it rather than restating it in YAML, so a hosted run and a local run cannot describe
different matrices. The assertions below are mechanical rather than a reading of the file.

```console
### test -x scripts/version_matrix.sh && head -5 scripts/version_matrix.sh | grep -c 'set -euo pipefail'
1
### grep -Eic 'REVENIUM_.*KEY|api\.revenium\.io' scripts/version_matrix.sh
0
### grep -c 'scripts/version_matrix.sh' .github/workflows/version-matrix.yml
3
```

The first says the runner fails hard: any non-zero command aborts it, and an unset variable is an
error rather than an empty string. The second says the runner names no credential and no hosted
endpoint. The third says the workflow file calls this script instead of duplicating it — three
matching lines, of which one is the `run:` invocation and two are the header comments explaining why
the workflow is a caller rather than a second definition of the matrix.

### How a leg proves it ran against what it claims

Each leg does four things, in this order, and every one of them appears in the transcript:

| Printed | Why it is there |
|---|---|
| `interpreter` and `sys.executable` | Names the interpreter the leg actually ran under, and the throwaway environment it came from. A leg that inherited the ambient interpreter would show a different path. |
| `mlflow.__version__` and `mlflow.__file__` | Read from the running interpreter, not from the pin that was requested. The file path shows the install came from this leg's own environment. |
| test suite result | 85 tests, the same suite `scripts/check.sh` runs. |
| capability probe record | `_compat.probe()` on a real installation — the record, not a boolean. |

Two of those are also **asserted**, not merely printed: the leg exits non-zero if the interpreter's
minor version or the resolved `mlflow.__version__` is not the one the leg exists to test. That is
what makes a silently substituted version a failure rather than a line of text nobody compares.
Section 4 shows that assertion firing.

Each leg's environment is created fresh under a `mktemp -d` root with `uv venv --clear`, and deleted
when the leg ends, so no leg can inherit another leg's resolution.

---

## 1. Resolved pins

Three MLflow pins are resolved before any leg runs and echoed, so a future reader knows which
releases were actually exercised on the run date (D-15). Only the floor is a literal — the floor is
a claim this project makes in `pyproject.toml`, not an observation about what the index holds. The
middle pin is the **median** release at or above the floor and below 4, so it moves as MLflow ships
rather than being frozen at whatever was newest the day this was written.

```console
### bash scripts/version_matrix.sh
### resolving mlflow pins
3.15.0 3.15.1 3.15.2 3.16.0
pin floor   mlflow 3.15.0   (literal — the floor this project declares)
pin middle  mlflow 3.15.2   (resolved: median 3.x at or above the floor)
pin newest  mlflow 3.16.0   (resolved: newest 3.x on the index)
```

The first line is the full candidate list the pins were drawn from, printed on stderr. On this run
the index held four installable final 3.x releases at or above the floor, and the median landed on
**3.15.2** — one of the two releases the research bisection recorded as never individually exercised
end to end. The other, 3.15.1, is the release section 4 plants as a substitution.

---

## 2. The four legs

Four legs (D-16): three MLflow versions on the Python 3.10 floor, plus the newest MLflow on Python
3.14. That guards both risky edges — the oldest supported syntax against the most constrained
resolver target, and an interpreter three minors ahead of the floor — without paying for a full
cross-product.

### 2.1 Leg `floor` — mlflow 3.15.0 on Python 3.10

```console
===========================================================================
=== leg floor: mlflow 3.15.0 on Python 3.10
===========================================================================
--- interpreter and resolved mlflow version
interpreter         Python 3.10.20
sys.executable      /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T//mlflow-version-matrix.6JqHg8/floor/venv/bin/python
mlflow.__version__  3.15.0
resolved            mlflow 3.15.0 on Python 3.10.20
mlflow.__file__     /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.6JqHg8/floor/venv/lib/python3.10/site-packages/mlflow/__init__.py
--- test suite
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.74s
--- capability probe
revenium_mlflow.__file__  /Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py
MLflowCapabilities(mlflow_version='3.15.0', has_bridged_tracer_provider=True, has_genai_semconv_env=True, has_isolated_id_generator_env=True)
--- leg floor: PASSED
```

**What this leg proves.** The floor this package declares in `pyproject.toml` is installable, and
the capability the floor exists for is genuinely present on it: `has_bridged_tracer_provider=True`
on a real 3.15.0 installation, not on a duck-typed stand-in. `mlflow.tracing.get_bridged_tracer_provider()`
is the only public route to attach a span processor to MLflow's tracing pipeline, so a floor that did
not carry it would be a floor in name only. The whole suite passes on the oldest supported
interpreter, and `revenium_mlflow.__file__` points at the working tree, so the leg exercised this
SDK's source rather than a previously built copy.

### 2.2 Leg `middle` — mlflow 3.15.2 on Python 3.10

```console
===========================================================================
=== leg middle: mlflow 3.15.2 on Python 3.10
===========================================================================
--- interpreter and resolved mlflow version
interpreter         Python 3.10.20
sys.executable      /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T//mlflow-version-matrix.6JqHg8/middle/venv/bin/python
mlflow.__version__  3.15.2
resolved            mlflow 3.15.2 on Python 3.10.20
mlflow.__file__     /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.6JqHg8/middle/venv/lib/python3.10/site-packages/mlflow/__init__.py
--- test suite
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.71s
--- capability probe
revenium_mlflow.__file__  /Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py
MLflowCapabilities(mlflow_version='3.15.2', has_bridged_tracer_provider=True, has_genai_semconv_env=True, has_isolated_id_generator_env=True)
--- leg middle: PASSED
```

**What this leg proves.** 3.15.2 is one of the two patch releases the research bisection recorded as
never individually exercised end to end; this is the first time it has been. Together with the leg
below, it substantiates D-10: the probe's acceptance is capability-based and never compares a
version, and here the same record comes back true across three different MLflow releases without any
version comparison anywhere in the path. Because the pin is a resolved median rather than a literal,
this leg will keep moving into releases nobody has exercised as MLflow ships.

### 2.3 Leg `newest` — mlflow 3.16.0 on Python 3.10

```console
===========================================================================
=== leg newest: mlflow 3.16.0 on Python 3.10
===========================================================================
--- interpreter and resolved mlflow version
interpreter         Python 3.10.20
sys.executable      /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T//mlflow-version-matrix.6JqHg8/newest/venv/bin/python
mlflow.__version__  3.16.0
resolved            mlflow 3.16.0 on Python 3.10.20
mlflow.__file__     /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.6JqHg8/newest/venv/lib/python3.10/site-packages/mlflow/__init__.py
--- test suite
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.66s
--- capability probe
revenium_mlflow.__file__  /Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py
MLflowCapabilities(mlflow_version='3.16.0', has_bridged_tracer_provider=True, has_genai_semconv_env=True, has_isolated_id_generator_env=True)
--- leg newest: PASSED
```

**What this leg proves.** The newest MLflow on the index carries every capability the floor does, so
the `<4` upper bound in `pyproject.toml` is not currently masking a break. This is the second half of
the real-installation capability-probe criterion: the probe returns a typed record on the floor and
on the newest release alike, with no version comparison distinguishing them.

### 2.4 Leg `newest-py314` — mlflow 3.16.0 on Python 3.14

```console
===========================================================================
=== leg newest-py314: mlflow 3.16.0 on Python 3.14
===========================================================================
--- interpreter and resolved mlflow version
interpreter         Python 3.14.7
sys.executable      /private/var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.6JqHg8/newest-py314/venv/bin/python
mlflow.__version__  3.16.0
resolved            mlflow 3.16.0 on Python 3.14.7
mlflow.__file__     /private/var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.6JqHg8/newest-py314/venv/lib/python3.14/site-packages/mlflow/__init__.py
--- test suite
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.79s
--- capability probe
revenium_mlflow.__file__  /Users/johndemic/Development/projects/revenium/revenium-mlflow-sdk/src/revenium_mlflow/__init__.py
MLflowCapabilities(mlflow_version='3.16.0', has_bridged_tracer_provider=True, has_genai_semconv_env=True, has_isolated_id_generator_env=True)
--- leg newest-py314: PASSED
```

**What this leg proves.** Whether MLflow and its dependency tree resolve on Python 3.14 was not known
in advance — the plan for this work said so explicitly, and instructed that a failure here be
recorded as a genuine finding rather than dropped. It resolved. The package, its floors, and the
whole suite work on an interpreter three minor versions above the declared floor, which is what
justifies the `Programming Language :: Python :: 3.14` classifier in `pyproject.toml`.

### 2.5 Summary line

```console
===========================================================================
### summary: 4 of 4 legs passed
### every attempted leg passed
```

Exit status `0`. The summary counts legs **attempted**, not legs defined, so a subset run says so,
and a leg that failed to resolve is still counted as attempted rather than vanishing from the
denominator.

---

## 3. Negative control A — a leg that cannot resolve is recorded, not dropped

A matrix that quietly drops an unresolvable leg reports "everything passed" while testing less than
it claims (threat T-01-40). To show that cannot happen here, the floor pin was temporarily changed
from `3.15.0` to `3.15.99`, a release that does not exist on the index, and the floor leg run.

```console
### sed -i '' 's/^FLOOR_MLFLOW="3.15.0"$/FLOOR_MLFLOW="3.15.99"/' scripts/version_matrix.sh
### bash scripts/version_matrix.sh --legs floor
### resolving mlflow pins
3.16.0
pin floor   mlflow 3.15.99   (literal — the floor this project declares)
pin middle  mlflow 3.16.0   (resolved: median 3.x at or above the floor)
pin newest  mlflow 3.16.0   (resolved: newest 3.x on the index)

===========================================================================
=== leg floor: mlflow 3.15.99 on Python 3.10
===========================================================================
--- FAILED: uv pip install mlflow==3.15.99 (verbatim output)
  × No solution found when resolving dependencies:
  ╰─▶ Because there is no version of mlflow==3.15.99 and you require
      mlflow==3.15.99, we can conclude that your requirements are
      unsatisfiable.
--- leg floor: FAILED

===========================================================================
### summary: 0 of 1 legs passed
### failed legs: floor
PLANT A EXIT=1
```

The resolver's own output is reproduced verbatim under the leg banner, the leg is named in the failed
list, the summary reads `0 of 1` rather than `1 of 1`, and the run exits `1`. The candidate list on
the second line also shrank to a single entry, which is the pin resolution correctly reporting that
nothing at or above the planted floor exists apart from 3.16.0.

---

## 4. Negative control B — a leg that runs a version other than the one it claims fails

This is the more dangerous shape, and it is the exact one that produced a false pass earlier in this
phase: the machinery works, the output looks right, and the number printed is not the number that
was tested. The install line was temporarily changed to install `mlflow==3.15.1` while the leg
continued to claim `3.15.0` everywhere else — a silent substitution (threat T-01-SC).

```console
### sed -i '' 's|"mlflow==${mlflow_pin}"|"mlflow==3.15.1"|' scripts/version_matrix.sh
### bash scripts/version_matrix.sh --legs floor
pin floor   mlflow 3.15.0   (literal — the floor this project declares)
pin middle  mlflow 3.15.2   (resolved: median 3.x at or above the floor)
pin newest  mlflow 3.16.0   (resolved: newest 3.x on the index)

===========================================================================
=== leg floor: mlflow 3.15.0 on Python 3.10
===========================================================================
--- interpreter and resolved mlflow version
interpreter         Python 3.10.20
sys.executable      /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T//mlflow-version-matrix.thXel5/floor/venv/bin/python
mlflow.__version__  3.15.1
resolved            mlflow 3.15.1 on Python 3.10.20
mlflow.__file__     /var/folders/t8/bqr6zkhx5xdd9dd33l9zs64w0000gn/T/mlflow-version-matrix.thXel5/floor/venv/lib/python3.10/site-packages/mlflow/__init__.py
LEG MISMATCH: expected mlflow 3.15.0, resolved 3.15.1
--- FAILED: the leg did not run under the interpreter and mlflow it claims
--- leg floor: FAILED

===========================================================================
### summary: 0 of 1 legs passed
### failed legs: floor
PLANT B EXIT=1
```

Note what the banner still says: `leg floor: mlflow 3.15.0 on Python 3.10`. Every label in the run is
unchanged, and the substitution is visible only because the version is read back **from the running
interpreter** and compared. Without that comparison this leg would have printed `85 passed`,
reported `1 of 1`, and exited `0` while never touching 3.15.0. The same assertion covers the
interpreter minor version, which is what stops the floor leg from silently running under the
machine's 3.9.6 or 3.14.7 (threat T-01-42).

---

## 5. The plants are reverted

```console
### diff /tmp/version_matrix.sh.orig scripts/version_matrix.sh && echo "REVERTED: identical to pre-plant"
REVERTED: identical to pre-plant
### grep -n 'FLOOR_MLFLOW=' scripts/version_matrix.sh | head -2
64:FLOOR_MLFLOW="3.15.0"
### grep -n 'mlflow==\${mlflow_pin}' scripts/version_matrix.sh
233:    if ! uv pip install --quiet --python "$py" "mlflow==${mlflow_pin}" >"$log" 2>&1; then
234:        echo "--- FAILED: uv pip install mlflow==${mlflow_pin} (verbatim output)"
```

Section 2 was run after both plants were reverted, against the file committed here.

---

## 6. Findings

**The pins exercised on this run date.** `3.15.0` (floor, literal), `3.15.2` (middle, resolved
median), `3.16.0` (newest, resolved). The full candidate list the middle and newest pins were drawn
from was `3.15.0 3.15.1 3.15.2 3.16.0`. A reader comparing this document against a later run should
expect the middle and newest pins to have moved; that is the design, and the floor is the only pin
that should still read `3.15.0`.

**No leg failed.** All four attempted legs passed, on four independently resolved environments.
Nothing is being omitted from this document.

**Python 3.14 works and was not assumed to.** The plan for this work flagged that MLflow's support
for 3.14 was unknown and required a failure there to be recorded rather than dropped. MLflow 3.16.0
and its dependency tree resolved on CPython 3.14.7 and the whole suite passed.

**3.15.1 and 3.15.2 are no longer unexercised.** The research bisection that fixed the floor tested
twenty releases for the presence of one symbol but never ran anything end to end on these two.
3.15.2 is now covered by the middle leg, and 3.15.1 was installed and imported during negative
control B. Because the middle pin is a resolved median rather than a literal, coverage of
intermediate releases continues without further edits.

**One deviation from the plan as written.** The plan specified `uv pip index versions mlflow` for
resolving the newest and middle pins. That subcommand does not exist in uv 0.11.17, the version this
project is developed against:

```console
### uv pip index versions mlflow
error: unrecognized subcommand 'index'
```

The release list is therefore read from the package index's JSON metadata under a uv-provisioned
interpreter (`uv run --no-project --python 3.10`) using only the standard library. uv still drives
the matrix and no dependency was added (D-14); every install is still performed by uv, and every
leg still reads its version back from the interpreter that ran it rather than trusting the pin.

**The lockfile question, settled.** An untracked `uv.lock` had sat at the repository root since
before plan 01-03, uncovered by `.gitignore` because the upstream template ships its `uv.lock` entry
commented out. It is now **ignored**, deliberately and with the entry enabled rather than left
ambiguous. The reasoning is specific to this matrix: this distribution is a library whose
correctness claim is that anything inside its declared floors resolves and works, and this matrix
substantiates that claim by resolving four times independently. A tracked lockfile records one
resolution on one platform and would stand as a standing invitation to pin exactly the thing the
matrix must vary — and a leg that quietly installed a locked MLflow would report a pass while
testing nothing, which is the failure this whole document is written against. Nothing pins a leg
today, because the legs install through uv's pip interface, which does not read a lockfile; the
ignore entry is what keeps a future rewrite onto `uv sync` from changing that silently. Consumers
get reproducibility from their own lockfile resolved over this package's floors, which is the
property a library owes them.

**On the workflow file.** `.github/workflows/version-matrix.yml` was added by this plan. It invokes
this same script, so a hosted run and a local run cannot describe different matrices. It has never
been executed in this project, it is provision for a future push and nothing more, and the
authoritative VER-07 evidence is this document. It carries no step that uploads an artifact, creates
a release, pushes a tag, or merges a branch, and it references no credential.

---

*Phase: 01-packaging-typed-api-surface-and-the-compat-wall, Plan 07*
*Captured: 2026-09-05*
