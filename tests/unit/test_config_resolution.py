"""Where configuration values come from, and the order that decides (CFG-08).

Resolution is a *policy* about sources, kept out of :class:`ReveniumConfig`'s
body on purpose: the class is the record, and Phases 5 and 6 both add fields to
the record without touching the policy. These tests pin the policy.

**Precedence is per field, not per source.** A caller who passes only an
endpoint still gets their credential from the environment. The alternative —
"an argument anywhere means the environment is ignored" — reads as tidier and
is the shape that silently drops a credential the operator did set.

**Environment variable names are inherited, not invented.** Counted across the
installed ``revenium-python-sdk`` 0.7.0 wheel: ``REVENIUM_METERING_API_KEY``
(27 uses), ``REVENIUM_TEAM_ID`` (16), ``REVENIUM_METERING_BASE_URL`` (16),
``REVENIUM_OUTCOME_API_KEY`` (9), ``REVENIUM_ENVIRONMENT`` (10),
``REVENIUM_REGION`` (10). A customer already running the house SDK has these
set, and a parallel name would mean their working configuration is silently
ignored by this one. Exactly one name is minted —
``REVENIUM_OTLP_TRACES_ENDPOINT``, for the field no sibling has.

**Why ``REVENIUM_METERING_BASE_URL`` composes rather than being ignored (the
2026-09-09 amendment).** Every other Revenium SDK points at a non-production
deployment with that one variable and composes its own routes onto it
(``revenium_middleware/_metering/_client.py:91-93``). Requiring this SDK's user
to supply the whole path including ``/meter/v2/otlp/v1/traces`` would make it
the only Revenium SDK that works that way, and would put a path they have to
know ahead of a demo. So the composition exists, and
:func:`test_composing_the_house_base_reproduces_the_default_exactly` pins it
against :data:`DEFAULT_OTLP_TRACES_ENDPOINT` so the two cannot drift apart.

**The environment is read, never written.** That is CFG-03's other half and it
is asserted twice: once here as a runtime comparison across the call, and
mechanically over the whole shipped package in
``tests/unit/test_otel_slot_untouched.py``.

Every test passes its own ``environ`` mapping rather than monkeypatching
``os.environ``. Two reasons: the read sites stay countable, and a test that
mutated the process environment would configure whatever ran after it.
"""

import ast
import dataclasses
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from revenium_mlflow.config import (
    DEFAULT_OTLP_TRACES_ENDPOINT,
    ENVIRONMENT_VARIABLE_NAMES,
    METERING_BASE_URL_VARIABLE,
    ReveniumConfig,
    compose_otlp_traces_endpoint,
    resolve_config,
)
from revenium_mlflow.errors import ConfigurationError

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_SOURCE = _REPO_ROOT / "src" / "revenium_mlflow" / "config.py"

#: Shaped like a metering key and unmistakably not one. The distinctive tail is
#: what the redaction assertion actually looks for.
_FAKE_METERING_KEY = "rev_mk_RESOLUTION_SENTINEL"
_FAKE_KEY_SENTINEL = "RESOLUTION_SENTINEL"

#: Loopback, never routable. Used wherever a test needs "an endpoint that is not
#: the default" — pointing a decoy at a real host would be an exfiltration risk
#: in a test whose whole subject is where values come from.
_ARGUMENT_ENDPOINT = "http://127.0.0.1:14318/v1/traces"
_ENVIRONMENT_ENDPOINT = "http://127.0.0.1:14319/v1/traces"
_DECOY_ENDPOINT = "http://127.0.0.1:14320/v1/traces"

#: The sibling's own default base, including the ``/meter/`` it already carries.
#: The TLD differs from this SDK's default and that difference is deliberately
#: not resolved here — see
#: :func:`test_the_config_module_records_the_unresolved_tld_discrepancy`.
_HOUSE_BASE_WITH_SLASH = "https://api.revenium.io/meter/"
_HOUSE_BASE_WITHOUT_SLASH = "https://api.revenium.io/meter"


def _empty_environ() -> Mapping[str, str]:
    """An environment with nothing set. Explicit, so no test inherits a shell."""
    return {}


def test_nothing_set_resolves_the_default_route_and_the_http_protobuf_protocol() -> None:
    """The floor of the precedence chain, and the protocol that is never negotiable.

    MLflow's own OTLP protocol default is ``grpc``, which raises
    ``MlflowException`` without the gRPC exporter installed and is not the route
    Revenium's ingest listens on. Resolution must not reintroduce that
    fallthrough by leaving the field unset.
    """
    resolved = resolve_config(environ=_empty_environ())

    assert resolved.otlp_traces_endpoint == DEFAULT_OTLP_TRACES_ENDPOINT
    assert resolved.otlp_protocol == "http/protobuf"


def test_the_revenium_named_endpoint_variable_alone_resolves_the_endpoint() -> None:
    """Level 2 of the chain: the one environment variable name this plan mints."""
    resolved = resolve_config(
        environ={ENVIRONMENT_VARIABLE_NAMES["otlp_traces_endpoint"]: _ENVIRONMENT_ENDPOINT}
    )

    assert resolved.otlp_traces_endpoint == _ENVIRONMENT_ENDPOINT


def test_the_endpoint_argument_beats_the_endpoint_variable() -> None:
    """Level 1 beats level 2, asserted with both present in one call.

    Asserting the argument alone would pass equally against an implementation
    that ignored the environment entirely, which is the opposite bug.
    """
    resolved = resolve_config(
        otlp_traces_endpoint=_ARGUMENT_ENDPOINT,
        environ={ENVIRONMENT_VARIABLE_NAMES["otlp_traces_endpoint"]: _ENVIRONMENT_ENDPOINT},
    )

    assert resolved.otlp_traces_endpoint == _ARGUMENT_ENDPOINT


def test_the_credential_follows_the_same_three_levels() -> None:
    """Argument over ``REVENIUM_METERING_API_KEY`` over nothing.

    ``REVENIUM_METERING_API_KEY`` and not ``REVENIUM_METERING_KEY``: the former
    is the house name with 27 uses in the sibling wheel, and a customer who
    already has it exported must not have it ignored.
    """
    variable = ENVIRONMENT_VARIABLE_NAMES["api_key"]

    assert variable == "REVENIUM_METERING_API_KEY"
    assert resolve_config(environ=_empty_environ()).api_key is None
    assert resolve_config(environ={variable: _FAKE_METERING_KEY}).api_key == _FAKE_METERING_KEY
    assert (
        resolve_config(
            api_key="rev_mk_FROM_THE_ARGUMENT",
            environ={variable: _FAKE_METERING_KEY},
        ).api_key
        == "rev_mk_FROM_THE_ARGUMENT"
    )


def test_precedence_is_per_field_not_per_source() -> None:
    """An endpoint argument must not suppress the credential in the environment.

    This is the specific failure the per-field rule exists to prevent: a caller
    who overrides one value in code, keeps their credential in the environment
    where it belongs, and would otherwise get a ``ConfigurationError`` naming a
    credential they did set.
    """
    resolved = resolve_config(
        otlp_traces_endpoint=_ARGUMENT_ENDPOINT,
        environ={ENVIRONMENT_VARIABLE_NAMES["api_key"]: _FAKE_METERING_KEY},
    )

    assert resolved.otlp_traces_endpoint == _ARGUMENT_ENDPOINT
    assert resolved.api_key == _FAKE_METERING_KEY


def test_the_inherited_variable_names_resolve_onto_their_fields() -> None:
    """``REVENIUM_TEAM_ID``, ``REVENIUM_ENVIRONMENT``, ``REVENIUM_REGION``, and the outcome key."""
    resolved = resolve_config(
        environ={
            ENVIRONMENT_VARIABLE_NAMES["billing_team_id"]: "team-inherited",
            ENVIRONMENT_VARIABLE_NAMES["environment"]: "staging",
            ENVIRONMENT_VARIABLE_NAMES["region"]: "us-east-1",
            ENVIRONMENT_VARIABLE_NAMES["outcome_api_key"]: "rev_sk_RESOLUTION_SENTINEL",
        }
    )

    assert resolved.billing_team_id == "team-inherited"
    assert resolved.environment == "staging"
    assert resolved.region == "us-east-1"
    assert resolved.outcome_api_key == "rev_sk_RESOLUTION_SENTINEL"


def test_every_mapped_variable_name_is_a_real_field_and_carries_the_house_prefix() -> None:
    """The map cannot name a field that does not exist, or a variable nobody sets.

    Keyed by field name so the mapping is checkable against the dataclass rather
    than against a transcription of it. A typo in a key would otherwise resolve
    nothing and look exactly like an unset variable.
    """
    fields = {field.name for field in dataclasses.fields(ReveniumConfig)}
    assert set(ENVIRONMENT_VARIABLE_NAMES) <= fields

    for variable in (*ENVIRONMENT_VARIABLE_NAMES.values(), METERING_BASE_URL_VARIABLE):
        assert variable.startswith("REVENIUM_"), variable
        assert not variable.startswith("OTEL_"), variable


def test_exactly_one_variable_name_is_minted_and_the_rest_are_inherited() -> None:
    """Reusing the sibling's names is the rule; the traces endpoint is the one exception.

    The sibling wheel has no OTLP traces endpoint at all, so that name has to be
    new. Every other name here is one a customer running the house SDK already
    has exported, and inventing a parallel spelling would mean their working
    configuration is silently ignored by this SDK.
    """
    inherited = {
        "REVENIUM_METERING_API_KEY",
        "REVENIUM_OUTCOME_API_KEY",
        "REVENIUM_TEAM_ID",
        "REVENIUM_ENVIRONMENT",
        "REVENIUM_REGION",
        "REVENIUM_METERING_BASE_URL",
    }
    declared = {*ENVIRONMENT_VARIABLE_NAMES.values(), METERING_BASE_URL_VARIABLE}

    assert declared - inherited == {"REVENIUM_OTLP_TRACES_ENDPOINT"}


# --------------------------------------------------------------------------
# The 2026-09-09 amendment: REVENIUM_METERING_BASE_URL composes.
# --------------------------------------------------------------------------


def test_composing_the_house_base_reproduces_the_default_exactly() -> None:
    """The assertion the amendment asked for by name, and the reason it exists.

    The sibling's base already includes ``/meter/``, and this SDK's default is
    that same context path plus ``/v2/otlp/v1/traces``. So composing the OTLP
    suffix onto a ``/meter/``-terminated base must reproduce the default
    constant *exactly*. Pinned as an assertion rather than a comment: a comment
    cannot notice the day one of the two is edited and the other is not.
    """
    assert compose_otlp_traces_endpoint(_HOUSE_BASE_WITH_SLASH) == DEFAULT_OTLP_TRACES_ENDPOINT


def test_the_trailing_slash_makes_no_difference() -> None:
    """Both spellings of the same base compose to the same endpoint.

    An operator exports whichever they have. A rule that produced
    ``/meter//v2/...`` for one of them would fail at the far end with a 404 that
    named neither the variable nor the slash.
    """
    with_slash = compose_otlp_traces_endpoint(_HOUSE_BASE_WITH_SLASH)
    without_slash = compose_otlp_traces_endpoint(_HOUSE_BASE_WITHOUT_SLASH)

    assert with_slash == without_slash == DEFAULT_OTLP_TRACES_ENDPOINT


@pytest.mark.parametrize(
    "base",
    ["https://dev.revenium.io", "https://dev.revenium.io/", "http://127.0.0.1:8080"],
)
def test_a_base_without_the_meter_context_path_gets_it(base: str) -> None:
    """The sibling normalises a bare host to ``/meter/``; so does this.

    Mirrors ``ReveniumMetering._normalize_base_url``, which adds ``/meter`` when
    it is absent and does not duplicate it when present. An operator who exports
    the bare host of their dev deployment is doing what the house SDK accepts.
    """
    composed = compose_otlp_traces_endpoint(base)

    assert composed.endswith("/meter/v2/otlp/v1/traces")
    assert "/meter/meter" not in composed


def test_the_base_url_variable_composes_the_endpoint_in_resolution() -> None:
    """Level 3 of the chain, which is the whole point of the amendment.

    One variable is what every other Revenium SDK needs to point at a
    non-production deployment. This is that variable, doing that job here.
    """
    resolved = resolve_config(
        environ={METERING_BASE_URL_VARIABLE: "https://dev.revenium.io/meter/"}
    )

    assert resolved.otlp_traces_endpoint == "https://dev.revenium.io/meter/v2/otlp/v1/traces"


def test_the_full_endpoint_variable_beats_the_base_url_variable() -> None:
    """Level 2 beats level 3: a fully-specified route wins over a composed one."""
    resolved = resolve_config(
        environ={
            ENVIRONMENT_VARIABLE_NAMES["otlp_traces_endpoint"]: _ENVIRONMENT_ENDPOINT,
            METERING_BASE_URL_VARIABLE: "https://dev.revenium.io",
        }
    )

    assert resolved.otlp_traces_endpoint == _ENVIRONMENT_ENDPOINT


def test_the_argument_beats_the_base_url_variable_too() -> None:
    """Level 1 beats level 3, asserted directly rather than inferred by transitivity."""
    resolved = resolve_config(
        otlp_traces_endpoint=_ARGUMENT_ENDPOINT,
        environ={METERING_BASE_URL_VARIABLE: "https://dev.revenium.io"},
    )

    assert resolved.otlp_traces_endpoint == _ARGUMENT_ENDPOINT


def test_the_base_url_variable_beats_the_default() -> None:
    """Level 3 beats level 4. Without this the composition would be unreachable."""
    resolved = resolve_config(environ={METERING_BASE_URL_VARIABLE: "https://dev.revenium.io"})

    assert resolved.otlp_traces_endpoint != DEFAULT_OTLP_TRACES_ENDPOINT


@pytest.mark.parametrize(
    "base",
    [
        "https://api.revenium.io/meter/v2/otlp/v1/traces",
        "https://api.revenium.io/meter/v2/otlp/v1/traces/",
        "http://127.0.0.1:4318/v1/traces",
    ],
)
def test_a_base_that_is_already_a_full_endpoint_raises_rather_than_doubling(base: str) -> None:
    """The ``/v1/traces/v1/traces`` case, named rather than papered over.

    Composition is exactly where a double suffix arises. Detecting and
    diagnosing it in general is EXP-05, owned by plan 04-05 — so this raises a
    ``ConfigurationError`` that names the variable and the remedy, and stops.
    What it must never do is produce ``.../v1/traces/v1/traces``, which reaches
    the far end as a 404 that names nothing.
    """
    with pytest.raises(ConfigurationError) as excinfo:
        compose_otlp_traces_endpoint(base)

    message = str(excinfo.value)
    assert METERING_BASE_URL_VARIABLE in message
    assert ENVIRONMENT_VARIABLE_NAMES["otlp_traces_endpoint"] in message


def test_composition_never_doubles_the_traces_suffix() -> None:
    """The negative, asserted over every base any test in this module composes.

    A guard that raises on the cases somebody thought of is worth less than a
    statement about the output of every case that succeeds.
    """
    for base in (
        _HOUSE_BASE_WITH_SLASH,
        _HOUSE_BASE_WITHOUT_SLASH,
        "https://dev.revenium.io",
        "https://dev.revenium.io/",
        "http://127.0.0.1:8080",
    ):
        composed = compose_otlp_traces_endpoint(base)
        assert composed.count("/v1/traces") == 1, composed
        assert composed.count("/v2/otlp") == 1, composed


@pytest.mark.parametrize(
    "base",
    ["https://api.revenium.io/meter/extra", "https://api.revenium.io/meter/v2"],
)
def test_an_ambiguous_meter_segment_raises_instead_of_guessing(base: str) -> None:
    """A ``/meter`` that is not the last segment is not something to guess about.

    The sibling silently truncates everything after it. Truncating is a guess
    with no error attached, and the guess it makes discards path segments the
    operator typed on purpose.
    """
    with pytest.raises(ConfigurationError):
        compose_otlp_traces_endpoint(base)


@pytest.mark.parametrize("base", ["api.revenium.io", "/meter", "dev.revenium.io/meter"])
def test_a_base_without_a_scheme_and_host_raises(base: str) -> None:
    """Composition onto a scheme-less string would produce a path, not a URL.

    Narrow on purpose: full URL well-formedness is EXP-05 and belongs to plan
    04-05. This is only the presence check without which composition has nothing
    to compose onto.
    """
    with pytest.raises(ConfigurationError):
        compose_otlp_traces_endpoint(base)


def test_a_blank_base_url_variable_is_treated_as_unset() -> None:
    """``export REVENIUM_METERING_BASE_URL=`` must not become a composition attempt.

    An exported-but-empty variable is how a shell profile spells "unset" by
    accident. Falling through to the default is right; raising would fail a
    process for a variable the operator believes they never set.
    """
    resolved = resolve_config(environ={METERING_BASE_URL_VARIABLE: "   "})

    assert resolved.otlp_traces_endpoint == DEFAULT_OTLP_TRACES_ENDPOINT


def test_a_blank_credential_variable_is_treated_as_unset() -> None:
    """Same rule for the credential: blank resolves to ``None``, not to ``""``.

    An empty-string credential would pass an ``is not None`` check and then be
    rejected remotely — the silent-401 shape ``configure_tracing`` raises to
    avoid.
    """
    resolved = resolve_config(environ={ENVIRONMENT_VARIABLE_NAMES["api_key"]: ""})

    assert resolved.api_key is None


# --------------------------------------------------------------------------
# A supplied config bypasses the environment.
# --------------------------------------------------------------------------


def test_a_supplied_config_bypasses_environment_resolution_entirely() -> None:
    """A decoy in the environment does not reach a caller's own configuration.

    A caller who builds a ``ReveniumConfig`` has stated every value explicitly.
    Merging the environment into it would mean their code says one thing and the
    process does another, decided by a variable they cannot see from the call
    site.
    """
    supplied = ReveniumConfig(
        otlp_traces_endpoint=_ARGUMENT_ENDPOINT,
        api_key=_FAKE_METERING_KEY,
    )
    resolved = resolve_config(
        config=supplied,
        environ={
            ENVIRONMENT_VARIABLE_NAMES["otlp_traces_endpoint"]: _DECOY_ENDPOINT,
            ENVIRONMENT_VARIABLE_NAMES["api_key"]: "rev_mk_DECOY",
            ENVIRONMENT_VARIABLE_NAMES["region"]: "decoy-region",
            METERING_BASE_URL_VARIABLE: "https://decoy.invalid",
        },
    )

    assert resolved.otlp_traces_endpoint == _ARGUMENT_ENDPOINT
    assert resolved.api_key == _FAKE_METERING_KEY
    assert resolved.region is None


def test_an_argument_still_overrides_a_supplied_config() -> None:
    """The argument is the caller's most local statement, so it wins over both."""
    supplied = ReveniumConfig(otlp_traces_endpoint=_DECOY_ENDPOINT, api_key=_FAKE_METERING_KEY)
    resolved = resolve_config(config=supplied, otlp_traces_endpoint=_ARGUMENT_ENDPOINT)

    assert resolved.otlp_traces_endpoint == _ARGUMENT_ENDPOINT
    assert resolved.api_key == _FAKE_METERING_KEY


def test_resolution_produces_a_new_frozen_instance_and_leaves_the_input_alone() -> None:
    """Frozen in, frozen out, and never the same object.

    ``ReveniumConfig`` is frozen so that "which endpoint did we export to" has a
    stable answer. Resolution that mutated its input would move that answer
    after the fact for every other holder of the object.
    """
    supplied = ReveniumConfig(otlp_traces_endpoint=_DECOY_ENDPOINT, api_key=_FAKE_METERING_KEY)
    resolved = resolve_config(config=supplied, otlp_traces_endpoint=_ARGUMENT_ENDPOINT)

    assert resolved is not supplied
    assert supplied.otlp_traces_endpoint == _DECOY_ENDPOINT
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.api_key = "rev_mk_MUTATED"  # type: ignore[misc]


def test_a_resolved_config_never_echoes_its_credential_in_a_repr() -> None:
    """T-04-11. A config object reaches a log line without anyone deciding it should."""
    rendered = repr(
        resolve_config(environ={ENVIRONMENT_VARIABLE_NAMES["api_key"]: _FAKE_METERING_KEY})
    )

    assert _FAKE_KEY_SENTINEL not in rendered
    assert _FAKE_METERING_KEY not in rendered
    assert "api_key" in rendered


# --------------------------------------------------------------------------
# Resolution reads. It does not write, dial, or import MLflow.
# --------------------------------------------------------------------------


def test_resolution_leaves_the_process_environment_byte_identical() -> None:
    """CFG-03's other half, measured across a call that defaults to ``os.environ``.

    Deliberately run without an explicit ``environ`` so the default read path is
    the one under test. Compared as a full mapping *and* as a key set, because a
    dict comparison alone would pass an implementation that added a key and
    removed another.
    """
    before = dict(os.environ)

    resolve_config()

    after = dict(os.environ)
    assert set(before) == set(after)
    assert before == after


def test_the_config_module_reads_the_environment_through_exactly_one_expression() -> None:
    """One read site, so "where does this value come from" has one answer.

    Counted over the source rather than asserted about behaviour: the claim is
    that the module has a single indirection, and a behavioural test cannot see
    a second one that happens to agree with the first today.
    """
    source = _CONFIG_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_CONFIG_SOURCE))

    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "environ"
    ]
    assert len(reads) == 1, f"expected one os.environ reference, found {len(reads)}"
    for forbidden in ("os.getenv", "getenv("):
        assert forbidden not in source, f"config.py reads the environment via {forbidden!r}"


def test_the_config_module_writes_no_environment_variable() -> None:
    """Asserted by AST, because this module's own prose describes the prohibition.

    A text search for ``os.environ[`` would match the docstring explaining why
    it is never written, so a walk over assignments is the instrument that can
    tell the description from a violation.
    """
    tree = ast.parse(_CONFIG_SOURCE.read_text(encoding="utf-8"), filename=str(_CONFIG_SOURCE))

    writes: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            writes += [
                target.lineno
                for target in node.targets
                if isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "environ"
            ]
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute) and function.attr in {
                "setdefault",
                "update",
                "pop",
                "putenv",
                "unsetenv",
            }:
                root = function.value
                if isinstance(root, ast.Attribute) and root.attr == "environ":
                    writes.append(node.lineno)

    assert writes == [], f"config.py writes the environment at lines {writes}"


def test_resolution_imports_neither_mlflow_nor_any_transport() -> None:
    """Checked in a clean interpreter, because this session imports MLflow elsewhere.

    An in-process ``'mlflow' in sys.modules`` assertion would pass or fail on
    test ordering, which is no assertion at all.
    """
    probe = (
        "import sys; from revenium_mlflow.config import resolve_config; resolve_config(); "
        "print('mlflow' in sys.modules, 'requests' in sys.modules, 'httpx' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )

    assert result.stdout.strip() == "False False False", result.stderr


def test_the_config_module_records_the_unresolved_tld_discrepancy() -> None:
    """The ``.ai``/``.io`` split is recorded for a human, not silently reconciled.

    The sibling SDK defaults to ``api.revenium.ai``; this SDK's default route is
    on ``api.revenium.io``. Whether the two deployments legitimately differ or
    one is stale is not answerable from this repository — the project forbids the
    call that would settle it. So it is written down where a reader of the config
    will find it, and this test is what stops it from being tidied away by
    someone who assumes it was a typo.
    """
    source = _CONFIG_SOURCE.read_text(encoding="utf-8")

    assert "api.revenium.ai" in source
    assert "api.revenium.io" in source
    assert "REVENIUM_METERING_BASE_URL" in source
