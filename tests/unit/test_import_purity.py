"""PKG-09: importing this package touches no network and installs no global tracing state.

A telemetry side-car that phones home or mutates the process tracer provider at
import time is a dependency nobody can safely add. Research found exactly that
failure in a sibling SDK, which logs at ERROR on import when a metering key is
unset. D-12 answers it by deferring the MLflow capability probe to configure
time. This file is the evidence that the answer holds.

**Why a subprocess, and why one launched with ``PYTHONPATH``.** A socket guard
installed in this interpreter would stay installed for the rest of the session
and change the behaviour of every other test. More importantly, this session has
already imported MLflow elsewhere, so an in-process ``"mlflow" in sys.modules``
assertion would report test ordering rather than import purity. The probe
therefore runs in a fresh interpreter whose ``PYTHONPATH`` points at
``tests/import_purity``, which is what makes CPython import the ``sitecustomize``
module in that directory automatically at start-up — before ``revenium_mlflow``
is even located on the path.

**Why the probe prints ``guard_live``.** A socket guard that silently failed to
install would make the whole proof vacuous: the import would touch no network
because nothing stopped it from doing so, and the transcript would look
identical. The probe therefore attempts a loopback connection itself and reports
whether the guard's distinctive error was raised. ``guard_live=True`` is the line
that turns "no network call was observed" into "a network call was impossible".

**Why the probe prints ``provider_kind``.** An empty ``provider_processors`` list
is satisfied by two different states: no processor is registered on the global
tracer provider, or the defensive attribute chain used to read the processor
collection did not resolve on that provider object. Printing the provider's class
name makes the disambiguation part of the evidence rather than leaving an
unattributable ``[]`` in the record. Both outcomes pass — either is a correct
proof that importing installs nothing — but the transcript has to say which one
it observed.

``tests/unit/test_public_surface.py`` carries a cheaper, unguarded version of the
``sys.modules`` half of this claim. That is deliberate duplication, not an
oversight: the cheap guard fails in the same commit that would break the
property, and this file proves the property comprehensively.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_private_access_wall import iter_package_modules

pytestmark = pytest.mark.unit

#: Resolved from this file rather than from the working directory, so the test
#: means the same thing run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBE_DIR = _REPO_ROOT / "tests" / "import_purity"
_PROBE = _PROBE_DIR / "check_import.py"
_TRANSCRIPT = _REPO_ROOT / "docs" / "verification" / "pkg-09-import-purity.md"
_PACKAGE_ROOT = _REPO_ROOT / "src" / "revenium_mlflow"

#: The five keys the probe prints, in the order it must print them. Asserting
#: the sequence — not just the presence of each key — is what makes "exactly
#: five lines in this order" a mechanical property rather than a description.
_EXPECTED_KEYS = (
    "mlflow_imported",
    "compat_imported",
    "provider_kind",
    "provider_processors",
    "guard_live",
)


def _run_probe() -> subprocess.CompletedProcess[str]:
    """Run the probe in a fresh interpreter under the socket guard.

    ``PYTHONPATH`` is the whole mechanism: it puts the guard directory on the
    child's ``sys.path`` before start-up, which is what makes ``site`` import
    ``sitecustomize`` from it. Passing the guard any later — a ``-c`` preamble,
    a conftest fixture — would leave a window in which an import-time socket
    call could still succeed.
    """
    env = {**os.environ, "PYTHONPATH": str(_PROBE_DIR)}
    # Fixed argv, no shell, no interpolated input.
    return subprocess.run(
        [sys.executable, str(_PROBE)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
        check=False,
    )


@pytest.fixture(scope="module")
def probe() -> subprocess.CompletedProcess[str]:
    """One subprocess run, shared by every assertion below.

    Module-scoped because the probe is a pure observation: running it six times
    would produce six identical transcripts and prove nothing extra.
    """
    return _run_probe()


@pytest.fixture(scope="module")
def probe_facts(probe: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """The probe's stdout parsed into ``key -> value``."""
    return dict(line.split("=", 1) for line in probe.stdout.strip().splitlines())


def test_the_probe_exits_zero_and_prints_its_five_facts_in_order(
    probe: subprocess.CompletedProcess[str],
) -> None:
    """OI-02 and T-01-34: the import raises nothing, under a guard that blocks it.

    A package whose import can raise breaks every application that merely
    depends on it, which is why D-12 moved the capability probe to configure
    time.
    """
    assert probe.returncode == 0, probe.stderr

    keys = tuple(line.split("=", 1)[0] for line in probe.stdout.strip().splitlines())
    assert keys == _EXPECTED_KEYS, probe.stdout


def test_the_import_loads_neither_mlflow_nor_the_compat_module(
    probe_facts: dict[str, str],
) -> None:
    """D-12 and T-01-35.

    MLflow performs its own outbound telemetry on import. Keeping it out of
    ``sys.modules`` means installing this SDK cannot give that telemetry a
    chance to fire, and means the capability probe has not run.
    """
    assert probe_facts["mlflow_imported"] == "False"
    assert probe_facts["compat_imported"] == "False"


def test_the_import_installs_no_global_span_processor(probe_facts: dict[str, str]) -> None:
    """T-01-33: the process-global tracer provider is untouched.

    That provider is single-valued and process-wide, so anything registered on
    it at import time affects every other library in the process — without the
    host ever having opted in.
    """
    assert probe_facts["provider_processors"] == "[]"


def test_the_empty_processor_list_is_attributable_to_a_named_provider(
    probe_facts: dict[str, str],
) -> None:
    """The empty list above cannot pass for the wrong reason.

    Without the provider's class name in the record, ``[]`` is equally
    consistent with a defensive attribute chain that failed to resolve. With it,
    a reader can tell which of the two states the transcript captured.
    """
    assert probe_facts["provider_kind"], "the probe emitted no provider kind"


def test_the_socket_guard_is_proven_live_rather_than_assumed(
    probe_facts: dict[str, str],
) -> None:
    """T-01-32: the guard is shown blocking, so a clean import is not vacuous."""
    assert probe_facts["guard_live"] == "True"


def test_the_transcript_records_the_probe_output(
    probe: subprocess.CompletedProcess[str],
) -> None:
    """The captured evidence says the same thing this run just said.

    A transcript that has drifted from the behaviour it documents is worse than
    no transcript, because it is read as current.
    """
    assert _TRANSCRIPT.is_file(), f"{_TRANSCRIPT} is missing"
    transcript = _TRANSCRIPT.read_text(encoding="utf-8")

    for line in probe.stdout.strip().splitlines():
        assert line in transcript, f"transcript is missing {line!r}"
    assert f"return code: {probe.returncode}" in transcript


# ---------------------------------------------------------------------------
# The structural half of PKG-09: no code path could install global tracing
# state, whether or not an import runs to completion.
#
# The subprocess probe above shows the state is clean after a *completed*
# import. That is not the same claim. A partially-completed import is a real
# state an application can observe — an interpreter shutting down mid-import, an
# ImportError caught by a caller, a KeyboardInterrupt — and a transcript taken
# after the fact cannot speak to it. Proving that no module-level registration
# call exists anywhere in the package is the stronger statement, because it
# holds at every point during an import rather than at one point after it.
# ---------------------------------------------------------------------------

#: A registration call at plain module scope. The call is on line 6 of the
#: string below, counting the leading newline as line 1.
_DIRTY_MODULE_SCOPE = """
from opentelemetry.sdk.trace import TracerProvider

provider = TracerProvider()

provider.add_span_processor(object())
"""

#: The same call, deferred into a function body — the D-12 design, and what
#: Phase 4's real ``configure_dual_export`` will look like.
_CLEAN_DEFERRED = """
from opentelemetry.sdk.trace import TracerProvider


def configure() -> None:
    provider = TracerProvider()
    provider.add_span_processor(object())


class Installer:
    def install(self) -> None:
        provider = TracerProvider()
        provider.add_span_processor(object())
"""

#: Registration hidden inside module-scope ``if`` and ``try`` blocks. Both
#: bodies execute at import time; only the indentation differs from the naive
#: case.
_DIRTY_CONDITIONAL = """
import os

from opentelemetry import trace

if os.environ.get("SOMETHING"):
    trace.set_tracer_provider(object())

try:
    import revenium_mlflow

    revenium_mlflow.configure_dual_export()
except ImportError:
    pass
"""


def test_no_module_in_the_package_registers_global_state_at_import() -> None:
    """The claim itself, across every shipped module."""
    modules = list(iter_package_modules(_PACKAGE_ROOT))

    assert modules, f"scanned nothing under {_PACKAGE_ROOT} — the walk is broken"

    findings = {str(path): scan_module_level_registration(path) for path in modules}
    assert not any(findings.values()), findings


def test_the_scanner_detects_a_module_scope_registration_call(tmp_path: Path) -> None:
    """The scanner finds what it claims to find.

    Without this, the assertion above is satisfied equally well by a function
    that returns an empty list for every input.
    """
    subject = tmp_path / "dirty_module_scope.py"
    subject.write_text(_DIRTY_MODULE_SCOPE, encoding="utf-8")

    findings = scan_module_level_registration(subject)

    assert len(findings) == 1, findings
    path, _, rest = findings[0].partition(":")
    assert path.endswith("dirty_module_scope.py")
    lineno, _, symbol = rest.partition(" ")
    assert lineno == "6", findings
    assert symbol == "add_span_processor", findings


def test_the_scanner_ignores_a_deferred_registration_call(tmp_path: Path) -> None:
    """A deferred call is the D-12 design, not a violation.

    A scanner that flagged it would fire on the real Phase 4 implementation of
    ``configure_dual_export``, and would be deleted rather than fixed.
    """
    subject = tmp_path / "clean_deferred.py"
    subject.write_text(_CLEAN_DEFERRED, encoding="utf-8")

    assert scan_module_level_registration(subject) == []


def test_a_conditional_registration_cannot_hide_from_the_scanner(tmp_path: Path) -> None:
    """Module-scope ``if`` and ``try`` bodies still execute at import time.

    This is the shape a registration would actually take if one were ever added
    — guarded by a capability check or wrapped in a ``try`` — so a scanner that
    only read the top-level statement list would miss the realistic case and
    catch only the naive one.
    """
    subject = tmp_path / "dirty_conditional.py"
    subject.write_text(_DIRTY_CONDITIONAL, encoding="utf-8")

    findings = scan_module_level_registration(subject)

    assert len(findings) == 2, findings
    assert all("dirty_conditional.py" in finding for finding in findings)
    assert [finding.rsplit(" ", 1)[1] for finding in findings] == [
        "set_tracer_provider",
        "configure_dual_export",
    ], findings
