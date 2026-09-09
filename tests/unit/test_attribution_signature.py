"""The tracing package's published shapes, and the reason each one is shaped so.

Three claims live here. They are about the *signature* and the shape of the
package — the parts that become a published contract the moment anything imports
them — rather than about what the tracing path does with a span, which is the
subject of ``tests/unit/test_attribution_scope.py`` and everything after it.

*The 21 explicit keyword parameters (D-03).* Revenium's ingest silently drops
attribute keys it does not recognise: the trace still exports, the request still
succeeds, and the attribution the customer is billed against is quietly wrong.
A ``**kwargs`` signature would accept ``subscriber_emial=`` and lose it with no
error on either side. Twenty-one named, keyword-only parameters turn that typo
into a checker error at author time. The parameter-name assertion below derives
its expectation from :data:`~revenium_mlflow.attributes.REVENIUM_ATTRIBUTE_KEYS`
by the same mechanical rule the module docstring states, so the signature and
the constants cannot drift apart without this test going red.

*Nothing here is a silent no-op (OI-02).* Every *still*-unimplemented public
callable raises :class:`NotImplementedError` naming the phase that implements it.
The alternative — a stub that accepts the call and returns — installs a processor
that observes every span and records nothing, which in a billing path produces a
wrong invoice rather than an error. Tests assert the raise for all of them,
message included, because a raise whose message does not say where the behaviour
is coming from is only marginally better than silence.

Two of those assertions changed shape in plan 03-01 rather than being deleted,
and the distinction matters. ``attribution()`` and
``ReveniumAttributionSpanProcessor`` are implemented now, so the tests that
asserted their raise assert their *behaviour* instead — that entering the scope
sets state, and that the processor constructs and exposes all four
``SpanProcessor`` methods. The rationale each one carried is what survives:
deleting them would have removed the only assertions in this file standing
between "implemented" and "accepts the call and returns", which is the exact
shape OI-02 names. ``configure_tracing`` and ``ReveniumExportHandle`` are
Phase 4 and still raise.

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
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from revenium_mlflow.attributes import REVENIUM_ATTRIBUTE_KEYS
from revenium_mlflow.config import ENVIRONMENT_VARIABLE_NAMES, ReveniumConfig
from revenium_mlflow.errors import ConfigurationError
from revenium_mlflow.tracing import (
    ReveniumAttributionSpanProcessor,
    ReveniumExportHandle,
    _scope,
    attribution,
    configure_tracing,
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
    """Building the scope is free; nothing happens until it is entered.

    ``@contextlib.contextmanager`` does not run the generator body until
    ``__enter__``, which is what let Phase 1 publish a signature a type checker
    could check against a body that raised. The property outlived that body and
    is still worth pinning: constructing a scope must not touch the
    ``ContextVar``, or a scope built in one task and entered in another would
    attribute the wrong traffic.
    """
    assert attribution() is not None
    assert dict(_scope.current()) == {}


def test_entering_attribution_sets_state_rather_than_yielding_silently() -> None:
    """A no-op attribution scope would produce unattributed billing, silently.

    That sentence is why this test existed in Phase 1, when it asserted the
    ``NotImplementedError``, and it is why the test is rewritten here rather than
    deleted. Plan 03-01 implemented the scope, so the raise it pinned is gone —
    but the failure the raise was standing guard against is not. A scope that
    entered, yielded, and recorded nothing is indistinguishable from a working
    one at every call site and produces spans that look attributed and are not.

    Asserted against the snapshot rather than against a span on purpose: this is
    the seam between the writer and the reader, and the reader's half is proved
    end to end in ``tests/unit/test_attribution_scope.py``. Reading
    ``_scope.current()`` here is what would catch a writer that set some *other*
    module's ``ContextVar`` — the one failure that a span-level assertion and a
    scope-level assertion cannot both miss.
    """
    assert dict(_scope.current()) == {}
    with attribution(organization_name="acme"):
        assert dict(_scope.current()) == {"organization_name": "acme"}
    assert dict(_scope.current()) == {}


class _RecordingBatchProcessor(BatchSpanProcessor):
    """A ``BatchSpanProcessor`` that records the bound it was flushed with.

    Subclassed rather than duck-typed so the handle's type annotation stays
    honest, and constructed with no exporter argument at all — nothing here
    exports, and a real exporter would open a socket this test has no use for.
    """

    def __init__(self) -> None:
        """Record into an empty list. The base initialiser is deliberately not run.

        ``BatchSpanProcessor.__init__`` starts a worker thread and allocates a
        queue. This stub answers one method and is never attached to a provider,
        so starting that machinery would be cost with no observation attached.
        """
        self.flushed_with: list[int] = []

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Record the bound and report success."""
        self.flushed_with.append(timeout_millis)
        return True


def _stub_handle(*, batch_processor: BatchSpanProcessor | None = None) -> ReveniumExportHandle:
    """A handle constructed without configuring anything.

    ``configure_tracing`` attaches to the *process-global* bridged provider
    and ``add_span_processor`` cannot be undone, so a test about the handle's own
    methods builds one directly rather than installing one it would then have to
    live with for the rest of the session.
    """
    return ReveniumExportHandle(
        provider=TracerProvider(),
        attribution_processor=ReveniumAttributionSpanProcessor(),
        batch_processor=batch_processor
        if batch_processor is not None
        else _RecordingBatchProcessor(),
        config=ReveniumConfig(),
    )


def test_configure_tracing_refuses_to_install_without_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install entry point must fail loudly, not report a phantom success.

    That sentence is why this test existed in Phase 1, when it asserted the
    ``NotImplementedError``, and it is why the test is rewritten here rather than
    deleted — the same treatment the scope test above got when plan 03-01
    replaced its raise. Plan 04-01 implemented ``configure_tracing``, so the
    Phase 1 raise is gone; the failure it stood guard against is not.

    The shape survives intact in the credential path, and it is the sharpest
    remaining instance of it. Installing with no ``api_key`` would attach a fully
    working pipeline whose every export is rejected remotely — and
    OpenTelemetry's ``BatchSpanProcessor`` discards ``SpanExportResult.FAILURE``
    without telling anyone, so the 401s reach no caller, no log and no metric.
    The operator's first evidence would be an invoice missing every model call.
    A ``ConfigurationError`` at configure time is the same "fail loudly rather
    than report a phantom success" claim, made where it now applies.

    **The credential variable is deleted explicitly**, even though
    ``tests/conftest.py`` clears the whole ``REVENIUM_*`` namespace for the
    session. Plan 04-02 made ``configure_tracing`` resolve its credential from
    the environment (CFG-08), so from that point on this assertion's meaning
    depends on a variable being absent. Depending on a session fixture for that
    would make the strongest "fails loudly" claim in the suite quietly
    conditional on setup that lives in another file.
    """
    monkeypatch.delenv(ENVIRONMENT_VARIABLE_NAMES["api_key"], raising=False)

    with pytest.raises(ConfigurationError) as excinfo:
        configure_tracing(otlp_traces_endpoint="http://127.0.0.1:1/v1/traces")
    assert "api_key" in str(excinfo.value)


def test_configure_tracing_returns_a_typed_handle_never_none() -> None:
    """CFG-07: returning ``None`` leaves a caller no way to see what was configured."""
    annotation = inspect.signature(configure_tracing).return_annotation
    assert annotation is ReveniumExportHandle


def test_export_handle_still_exposes_its_three_methods() -> None:
    """CFG-06 and CFG-07 name ``is_active``, ``reinstall`` and ``flush`` explicitly.

    All three are still present; what changed in plan 04-01 is which of them
    answer. Asserted for presence here, because the surface is the contract —
    behaviour belongs to the tests below and to
    ``tests/unit/test_dual_export_gate.py``.
    """
    handle = _stub_handle()
    for method_name in ("is_active", "reinstall", "flush"):
        assert callable(getattr(handle, method_name)), method_name


def test_the_unimplemented_handle_methods_raise_and_name_their_owner() -> None:
    """``is_active`` and ``reinstall`` belong to plan 04-04, and say so.

    They raise rather than returning a plausible answer, which is the same
    property Phase 1 asserted of all three. It matters most for ``is_active``: a
    handle that reported itself active without checking would say the integration
    is installed at exactly the moment MLflow's provider rebuild had evicted it —
    the one question CFG-07 created the handle to be able to answer honestly.
    """
    handle = _stub_handle()
    for method_name in ("is_active", "reinstall"):
        with pytest.raises(NotImplementedError) as excinfo:
            getattr(handle, method_name)()
        assert "04-04" in str(excinfo.value), method_name


def test_flush_is_implemented_and_bounded_against_this_sdks_own_processor() -> None:
    """T-04-05: the flush the handle performs is this SDK's, not the provider's.

    ``TracerProvider.force_flush`` walks every attached processor under one
    shared deadline and abandons the rest the moment it expires. This SDK's
    processor is appended last and is therefore first to be starved, so a
    provider-level flush would report ``False`` for a queue that was never
    reached. The stub processor below returns a value no provider-level flush
    would produce, which is what makes the delegation observable rather than
    assumed.
    """
    processor = _RecordingBatchProcessor()
    handle = _stub_handle(batch_processor=processor)
    assert handle.flush(2.5) is True
    assert processor.flushed_with == [2500]


def test_the_span_processor_constructs_and_exposes_the_four_processor_methods() -> None:
    """A constructible stub processor is installable, and would observe silently.

    That was the sharpest edge of OI-02 and the reason Phase 1 made this
    constructor raise: every other stub fails at the point of use, while a
    processor that merely constructs gets attached to MLflow's provider and then
    sees every span in the process while recording nothing. Plan 03-01 made it
    construct, so this test now asserts the four things the base class will
    actually call on it — a processor missing one of them fails at a callback
    OpenTelemetry invokes rather than at the line that registered it, which is
    the same deferred, far-from-the-cause failure the original raise existed to
    prevent.

    The four methods are checked for being callable, not for what they do:
    ``on_start``'s behaviour is ``tests/unit/test_attribution_scope.py``,
    ``on_end``'s deliberate emptiness is ``tests/unit/test_on_start_not_on_end.py``
    and plan 03-06's AST guard.
    """
    processor = ReveniumAttributionSpanProcessor()
    for method_name in ("on_start", "on_end", "shutdown", "force_flush"):
        assert callable(getattr(processor, method_name)), method_name
    assert processor.force_flush() is True


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
