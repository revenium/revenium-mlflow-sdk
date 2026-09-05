# PKG-09 — importing the SDK touches no network and installs no global tracing state

Captured evidence for Phase 01 Plan 06. Every block below is the verbatim stdout and stderr of the
command shown above it, run on this machine in one session against the working tree at the commit
this file is committed in.

**What this file has to prove.** PKG-09 asks that `import revenium_mlflow` be inert: no telemetry
beacon, no version check, no credential validation, no endpoint reachability probe, and no mutation
of the process-global OpenTelemetry tracer provider. The host application never opted into anything
the import itself does, and the tracer provider is single-valued and process-wide, so whatever is
registered there affects every other library in the process. D-12 is the design answer — the MLflow
capability probe runs inside `configure_dual_export()`, not at import — and this is the evidence
that the answer holds.

**Why a clean result is not automatically a proof.** A transcript showing "no network call was
observed" is produced equally well by an import that is genuinely inert and by a guard that silently
failed to install. An empty span-processor list is produced equally well by a provider that holds no
processors and by an attribute lookup that did not resolve. Sections 3 through 5 exist because of
that: each is one of the two halves of this proof shown reporting the *bad* answer, on demand.

**Scope and boundaries.**

- **No CI has run.** This repository has no CI workflow yet — one is written in plan 01-07. Every
  transcript below was produced by running the command shown, locally. Nothing here should be read
  as a CI result, a release, a publication, or a statement about production readiness.
- **No command contacts Revenium, a customer environment, or any hosted endpoint.** The only
  connection attempts anywhere in this document target `127.0.0.1:9` — the loopback discard port on
  this machine. In sections 1, 2 and 3 the socket guard raises before any syscall is made. In
  sections 4 and 5, where the guard is deliberately absent, the attempt is refused locally by the
  operating system. No name is resolved and no packet leaves the host.
- No command reads or prints an environment variable's value, and no credential is set or
  referenced. The output is booleans, class names, tool versions, and one traceback.
- Every command runs under `.venv/bin/python`, the same interpreter `scripts/check.sh` resolves as
  `PY`. The system `python3` on this machine is 3.9.6, below this project's 3.10 floor, so a bare
  PATH lookup would make these transcripts unattributable.

**Environment.** macOS, arm64. Interpreter `Python 3.10.20` at `.venv/bin/python`. pytest 9.1.1,
ruff 0.16.6, `opentelemetry-sdk` 1.44.0.

---

## How the guard is installed, and why it has to be `sitecustomize`

CPython's `site` module imports a module named `sitecustomize` at interpreter start-up if it can
find one on `sys.path`. `tests/import_purity/sitecustomize.py` uses that hook to replace
`socket.socket.connect`, `socket.socket.connect_ex` and `socket.create_connection` with functions
that raise `RuntimeError`, and the probe subprocess is launched with `PYTHONPATH` pointing at that
directory.

This is the only hook that fires *before* `revenium_mlflow` is located on the path, let alone
executed. A guard installed any later — in a `-c` preamble, in a pytest fixture, at the top of the
probe body — would leave a window in which an import-time socket call could still succeed, and the
proof would have a hole exactly the size of the thing it is meant to exclude.

The replacements raise `RuntimeError` rather than `OSError` on purpose. An `OSError` is
indistinguishable from an ordinary connection failure, so a package that swallowed it would produce a
clean transcript while genuinely having tried to reach the network. The `RuntimeError` carries a
single searchable token, `REVENIUM_IMPORT_PURITY_SOCKET_GUARD`, so any block is attributable to this
guard and to nothing else.

The probe is a separate process for a second reason: this repository's own test session imports
MLflow elsewhere, so an in-process `"mlflow" in sys.modules` assertion would report test ordering
rather than import purity.

## What the five sections prove

| Section | Command | Proves |
|---|---|---|
| 1 | `check_import.py` under the guard | The import is inert, and the guard was live while it happened. |
| 2 | `pytest tests/unit/test_import_purity.py` | The assertions that read section 1 pass. |
| 3 | The same probe with a module-level connection planted in the shipped package | The probe detects a real PKG-09 breach and exits non-zero. |
| 4 | The same probe under a guard that loads but installs nothing | `guard_live` can report `False`; it is not a constant. |
| 5 | The same probe with no guard directory on `PYTHONPATH` | The probe refuses to measure anything when the guard never loaded. |

---

## 1. The clean run

```
$ PYTHONPATH=tests/import_purity .venv/bin/python tests/import_purity/check_import.py
mlflow_imported=False
compat_imported=False
provider_kind=ProxyTracerProvider
provider_processors=[]
guard_live=True
return code: 0
```

Reading the five lines:

**`mlflow_imported=False`** — importing this SDK does not drag MLflow in (D-12). MLflow performs its
own outbound telemetry on import, so this line also means installing this SDK cannot give that
telemetry a chance to fire (T-01-35).

**`compat_imported=False`** — `revenium_mlflow._compat` is absent, so the capability probe has not
run. That is D-12 stated as an observation rather than as an intention.

**`provider_kind=ProxyTracerProvider`** — this is the line that makes the next one mean something,
and it records the **stronger** of the two passing outcomes. `provider_processors=[]` is satisfied by
two different states: a real `TracerProvider` that holds no span processors, or a global provider
that was never initialised at all. `ProxyTracerProvider` is OpenTelemetry's API-level placeholder,
returned by `get_tracer_provider()` when nothing has installed an SDK provider. So the result here is
not merely "our processor is absent from the global provider" — it is "no global provider was ever
built". The distinction cannot be read out of `[]` alone, which is why the class name is printed.

**`provider_processors=[]`** — no span processor is registered on the process-global tracer provider
after the import (T-01-33). The probe reads the processor collection through a defensive `getattr`
chain, which on a `ProxyTracerProvider` resolves to nothing and yields the empty list.

**`guard_live=True`** — the probe attempted a loopback connection itself, through both
`socket.create_connection` and `socket.socket.connect`, and got the guard's own error back from both.
Without this line the four above would be consistent with a guard that never installed (T-01-32).
Section 4 shows this line reporting `False`.

**`return code: 0`** — the import raised nothing. A package whose import can raise breaks every
application that merely depends on it, which is the whole reason D-12 moved the capability probe to
configure time (T-01-34, OI-02).

## 2. The assertions that read it

```
$ .venv/bin/python -m pytest tests/unit/test_import_purity.py -q
......                                                                   [100%]
6 passed in 0.05s
```

## 3. A real breach, planted and reverted

A module-level outbound connection was appended to `src/revenium_mlflow/diagnostics.py` — a shipped
module, reached from `__init__.py`, so the call executes during a plain `import revenium_mlflow`:

```python
import socket as _planted_socket

_planted_socket.create_connection(("127.0.0.1", 9), timeout=0.01)
```

```
$ PYTHONPATH=tests/import_purity .venv/bin/python tests/import_purity/check_import.py
Traceback (most recent call last):
  File "/…/tests/import_purity/check_import.py", line 54, in <module>
    import revenium_mlflow  # noqa: E402
  File "/…/src/revenium_mlflow/__init__.py", line 71, in <module>
    from .diagnostics import ConnectionDiagnostics, validate_connection
  File "/…/src/revenium_mlflow/diagnostics.py", line 113, in <module>
    _planted_socket.create_connection(("127.0.0.1", 9), timeout=0.01)
  File "/…/tests/import_purity/sitecustomize.py", line 38, in _blocked
    raise RuntimeError(_MESSAGE)
RuntimeError: REVENIUM_IMPORT_PURITY_SOCKET_GUARD: an outbound connection was attempted while the import-purity guard was installed
return code: 1
```

Note what the traceback establishes beyond the non-zero exit: the guard raised **inside the import
statement**, from `sitecustomize._blocked`. The connection was refused before any syscall, so even
the planted breach reached no network. And the failure is attributable — the token in the message
names this guard rather than leaving a bare `ConnectionRefusedError` that could have come from
anywhere.

The suite went red on the same tree:

```
$ .venv/bin/python -m pytest tests/unit/test_import_purity.py -q
=========================== short test summary info ============================
FAILED tests/unit/test_import_purity.py::test_the_probe_exits_zero_and_prints_its_five_facts_in_order
FAILED tests/unit/test_import_purity.py::test_the_import_loads_neither_mlflow_nor_the_compat_module
FAILED tests/unit/test_import_purity.py::test_the_import_installs_no_global_span_processor
FAILED tests/unit/test_import_purity.py::test_the_empty_processor_list_is_attributable_to_a_named_provider
FAILED tests/unit/test_import_purity.py::test_the_socket_guard_is_proven_live_rather_than_assumed
FAILED tests/unit/test_import_purity.py::test_the_transcript_records_the_probe_output
6 failed in 0.06s
```

The planted lines were then removed. `git status --short src/` reports no modification, and section 1
was re-run afterwards and reproduced byte-for-byte.

## 4. The guard reporting its own absence

`guard_live=True` is only worth printing if it can be `False`. Here the probe runs against a
`sitecustomize` that loads and defines the token but installs no replacements — the exact
silent-failure scenario the line exists to exclude:

```python
"""A guard that loads but installs nothing — the silent-failure scenario."""

GUARD_TOKEN = "REVENIUM_IMPORT_PURITY_SOCKET_GUARD"
```

```
$ PYTHONPATH=<scratch-dir> .venv/bin/python tests/import_purity/check_import.py
mlflow_imported=False
compat_imported=False
provider_kind=ProxyTracerProvider
provider_processors=[]
guard_live=False
return code: 0
```

The first four lines are byte-identical to section 1. That is precisely the point: an inert import
and an unguarded import are indistinguishable on those four lines alone, and `guard_live` is the only
thing separating them. `test_the_socket_guard_is_proven_live_rather_than_assumed` fails on this
output.

The loopback attempt here was not intercepted, so it reached the operating system and was refused
locally — an `OSError`, which the probe deliberately counts as *not blocked*. No packet left the
host.

## 5. The probe refusing to measure nothing

If the guard directory is not on `PYTHONPATH` at all, the probe exits before importing the subject
rather than emitting a clean-looking transcript that measures an unguarded import:

```
$ env -u PYTHONPATH .venv/bin/python tests/import_purity/check_import.py
import-purity guard was not loaded at start-up: 'sitecustomize' is absent from sys.modules. Launch this probe with PYTHONPATH=tests/import_purity.
return code: 1
```

---

## What this does and does not establish

**Established.** On this machine, on this tree: a complete `import revenium_mlflow` performs no
outbound connection through `socket.create_connection`, `socket.socket.connect` or
`socket.socket.connect_ex`; it loads neither `mlflow` nor `revenium_mlflow._compat`; it leaves the
OpenTelemetry global tracer provider as an uninitialised `ProxyTracerProvider` carrying no span
processors; and it raises nothing. Both halves of that proof are shown reporting the bad answer on
demand, so neither is a constant.

**Not established by this document.** That the property holds at every point *during* an import
rather than only after a completed one — an import interrupted partway is a state an application can
observe, and a transcript taken after the fact cannot speak to it. That gap is closed structurally by
the module-level registration scan in section 6, which reasons about the source rather than about one
completed run.

**Also not established.** Anything about a released, published, or CI-verified artifact. None of
those exist.
