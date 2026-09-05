"""The tracing package's published shapes, and the reason each one is shaped so.

Three claims live here, and none of them is about behaviour — Phase 1 implements
no MLflow behaviour at all. They are about the *signature*, which is the part
that becomes a published contract the moment anything imports it.

*The 21 explicit keyword parameters (D-03).* Revenium's ingest silently drops
attribute keys it does not recognise: the trace still exports, the request still
succeeds, and the attribution the customer is billed against is quietly wrong.
A ``**kwargs`` signature would accept ``subscriber_emial=`` and lose it with no
error on either side. Twenty-one named, keyword-only parameters turn that typo
into a checker error at author time. The parameter-name assertion below derives
its expectation from :data:`~revenium_mlflow.attributes.REVENIUM_ATTRIBUTE_KEYS`
by the same mechanical rule the module docstring states, so the signature and
the constants cannot drift apart without this test going red.

*Nothing here is a silent no-op (OI-02).* Every unimplemented public callable
raises :class:`NotImplementedError` naming the phase that implements it, and the
processor class cannot be constructed at all. The alternative — a stub that
accepts the call and returns — installs a processor that observes every span and
records nothing, which in a billing path produces a wrong invoice rather than an
error. Tests assert the raise for all of them, message included, because a raise
whose message does not say where the behaviour is coming from is only marginally
better than silence.

*The two halves of the SDK stay disjoint.* The tracing package must not import
the metering package, so the OTLP path stays installable without a Revenium HTTP
credential. That is checked by an AST walk rather than by ``grep``, because a
grep over source text cannot tell an import from the word appearing in a
docstring — and this file's own prose mentions the module path.
"""

import ast
import inspect
from pathlib import Path

import pytest

from revenium_mlflow.attributes import REVENIUM_ATTRIBUTE_KEYS
from revenium_mlflow.tracing import (
    ReveniumAttributionSpanProcessor,
    ReveniumExportHandle,
    attribution,
    configure_dual_export,
)

pytestmark = pytest.mark.unit

#: Resolved from this file rather than the working directory so the AST walk
#: means the same thing run from anywhere.
_TRACING_ROOT = Path(__file__).resolve().parents[2] / "src" / "revenium_mlflow" / "tracing"

#: The prefix every ATTR-07 key carries, stripped to produce a parameter name.
_KEY_PREFIX = "revenium."


def _expected_parameter_names() -> set[str]:
    """Derive the 21 parameter names from the 21 constants, mechanically.

    Deliberately computed rather than written out. A hardcoded list would agree
    with the constants on the day it was typed and silently stop agreeing the
    day a key is added, renamed, or removed — which is exactly the drift this
    test exists to prevent.
    """
    return {key.removeprefix(_KEY_PREFIX).replace(".", "_") for key in REVENIUM_ATTRIBUTE_KEYS}


def _parameters() -> dict[str, inspect.Parameter]:
    """The live signature of ``attribution``.

    ``contextlib.contextmanager`` wraps the generator with ``functools.wraps``,
    so ``inspect.signature`` follows ``__wrapped__`` and reports the parameters
    a caller actually writes rather than the wrapper's ``(*args, **kwds)``.
    """
    return dict(inspect.signature(attribution).parameters)


def test_attribution_takes_exactly_twenty_one_parameters() -> None:
    """One parameter per ATTR-07 key, and no spare."""
    assert len(_parameters()) == len(REVENIUM_ATTRIBUTE_KEYS) == 21


def test_every_attribution_parameter_is_keyword_only() -> None:
    """Positional order must never become part of the contract.

    Twenty-one same-typed parameters passed positionally would make an
    off-by-one at the call site type-check cleanly and attribute the traffic to
    the wrong tenant. Keyword-only removes the possibility rather than warning
    about it.
    """
    kinds = {name: param.kind for name, param in _parameters().items()}
    positional = [
        name for name, kind in kinds.items() if kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert positional == []


def test_attribution_parameter_names_derive_from_the_constants() -> None:
    """The signature and the key constants are one source of truth, not two."""
    assert set(_parameters()) == _expected_parameter_names()


def test_every_attribution_parameter_defaults_to_none() -> None:
    """Attribution is additive: supplying one key must not require the other 20."""
    non_none = {
        name: param.default for name, param in _parameters().items() if param.default is not None
    }
    assert non_none == {}


def test_attribution_accepts_no_variadic_parameters() -> None:
    """No ``**kwargs`` escape hatch (D-03).

    A single ``**kwargs`` would reinstate exactly the silent-drop failure the 21
    explicit parameters exist to eliminate, and it would do so invisibly — the
    call site would look identical.
    """
    variadic = {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}
    assert [name for name, p in _parameters().items() if p.kind in variadic] == []


def test_constructing_the_attribution_context_manager_does_not_raise() -> None:
    """Building the scope is free; only entering it reaches unimplemented code."""
    assert attribution() is not None


def test_entering_attribution_raises_naming_phase_three() -> None:
    """A no-op attribution scope would produce unattributed billing, silently."""
    with pytest.raises(NotImplementedError) as excinfo, attribution(organization_name="acme"):
        pass  # pragma: no cover - the context manager never yields
    assert "Phase 3" in str(excinfo.value)


def test_configure_dual_export_raises_naming_phase_four() -> None:
    """The install entry point must fail loudly, not report a phantom success."""
    with pytest.raises(NotImplementedError) as excinfo:
        configure_dual_export()
    assert "Phase 4" in str(excinfo.value)


def test_configure_dual_export_returns_a_typed_handle_never_none() -> None:
    """CFG-07: returning ``None`` leaves a caller no way to see what was configured."""
    annotation = inspect.signature(configure_dual_export).return_annotation
    assert annotation is ReveniumExportHandle


def test_export_handle_exposes_its_three_methods_and_each_raises() -> None:
    """CFG-06 and CFG-07 name ``is_active``, ``reinstall`` and ``flush`` explicitly."""
    handle = ReveniumExportHandle()
    for method_name in ("is_active", "reinstall", "flush"):
        method = getattr(handle, method_name)
        with pytest.raises(NotImplementedError) as excinfo:
            method()
        assert "Phase 4" in str(excinfo.value), method_name


def test_the_span_processor_cannot_be_constructed() -> None:
    """A constructible stub processor is installable, and would observe silently.

    This is the sharpest edge of OI-02. Every other stub here fails at the point
    of use; a processor that constructs would be attached to MLflow's provider
    and then see every span in the process while recording nothing.
    """
    with pytest.raises(NotImplementedError) as excinfo:
        ReveniumAttributionSpanProcessor()
    assert "Phase 3" in str(excinfo.value)


def test_the_tracing_package_never_imports_the_metering_package() -> None:
    """Keeps the OTLP path installable without a Revenium HTTP credential.

    Parsed rather than grepped: a textual search cannot distinguish an import
    from a docstring that names the module, and this repository's prose names it
    often.
    """
    offenders: list[str] = []
    for source_path in sorted(_TRACING_ROOT.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{source_path.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.startswith("revenium_mlflow.metering")
                ]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                relative_to_metering = node.level > 0 and module.split(".")[0] == "metering"
                if module.startswith("revenium_mlflow.metering") or relative_to_metering:
                    offenders.append(f"{source_path.name}: from {'.' * node.level}{module}")
    assert offenders == []
