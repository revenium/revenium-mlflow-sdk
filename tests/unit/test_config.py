"""The public :class:`ReveniumConfig` dataclass and its locked defaults (D-02).

Phase 1 publishes this type and nothing else about it. It performs no
environment resolution, no endpoint normalisation, no credential-scope detection
and no validation — those are CFG-08, EXP-05 and JOB-05, in Phases 4 and 5. What
these tests pin is therefore narrow and deliberately so: the *defaults*, the
*immutability*, and the *redaction*.

Three of those claims are worth stating plainly, because each one is a specific
failure this project already knows about:

*The protocol default.* MLflow's own OTLP protocol default is ``grpc``
(``otlp.py:124``), which raises ``MlflowException`` without the gRPC exporter
installed and is not the route Revenium's ingest listens on. Falling through to
it is a startup failure at best and a wrong destination at worst, so the HTTP
protobuf literal is set explicitly here and asserted here (T-01-22).

*The redaction.* ``__repr__`` must not echo key material. Both key fields are
``None`` today, which is exactly why the habit is established now: the first
commit where a real key can reach the object is the wrong place to start
thinking about it. The test plants a structurally-plausible but obviously fake
value and asserts it does not survive into the repr (T-01-19).

*The inertness.* Constructing this object opens no socket and reads no
environment variable. The endpoint default is a string constant that nothing in
this phase dials — the standing project prohibition on calling the hosted route
covers tests as much as it covers code (T-01-24).
"""

import dataclasses
import os
from pathlib import Path
from typing import Any

import pytest

from revenium_mlflow.config import DEFAULT_OTLP_TRACES_ENDPOINT, ReveniumConfig

pytestmark = pytest.mark.unit

#: Structurally shaped like a metering key so the redaction is exercised against
#: something a real one would resemble, and unmistakably not one. No live
#: credential exists anywhere in this repository.
_FAKE_METERING_KEY = "rev_mk_NOT_A_REAL_KEY"

#: The distinctive substring whose absence from the repr is the actual claim.
_FAKE_KEY_SENTINEL = "NOT_A_REAL_KEY"

_CONFIG_SOURCE = Path(__file__).resolve().parents[2] / "src" / "revenium_mlflow" / "config.py"


def test_the_dataclass_constructs_with_no_arguments() -> None:
    """Every field carries a default, so a caller can start from the defaults."""
    config = ReveniumConfig()

    assert isinstance(config, ReveniumConfig)
    assert dataclasses.is_dataclass(config)


def test_the_endpoint_default_is_the_composed_backend_route() -> None:
    """The route composed in PROJECT.md: /meter context + /v2/otlp + /v1/traces."""
    assert DEFAULT_OTLP_TRACES_ENDPOINT == "https://api.revenium.io/meter/v2/otlp/v1/traces"
    assert ReveniumConfig().otlp_traces_endpoint == DEFAULT_OTLP_TRACES_ENDPOINT


def test_the_protocol_default_is_http_protobuf_and_never_grpc() -> None:
    """MLflow's own default is gRPC, which raises at provider init (T-01-22)."""
    assert ReveniumConfig().otlp_protocol == "http/protobuf"
    assert ReveniumConfig().otlp_protocol != "grpc"


def test_the_credential_fields_default_to_none_and_are_separate() -> None:
    """Metering scope and write scope are two fields, not one (JOB-04)."""
    config = ReveniumConfig()

    assert config.api_key is None
    assert config.outcome_api_key is None
    field_names = {field.name for field in dataclasses.fields(config)}
    assert {"api_key", "outcome_api_key"} <= field_names


def test_the_billing_tenant_defaults_to_none() -> None:
    """Never inferred from an API-key prefix; it has to be stated (CFG-05)."""
    assert ReveniumConfig().billing_team_id is None


def test_the_completion_fallback_flag_defaults_to_disabled() -> None:
    """Off by default: the fallback can double-count what the OTLP path exported."""
    assert ReveniumConfig().enable_completion_fallback is False


def test_the_failure_mode_defaults_to_fail_open() -> None:
    """Telemetry must not take the application down with it (HTTP-08)."""
    assert ReveniumConfig().fail_open is True


def test_the_timeouts_are_explicit_positive_floats() -> None:
    """Every request carries explicit connect and read timeouts (HTTP-01)."""
    config = ReveniumConfig()

    assert isinstance(config.connect_timeout, float)
    assert isinstance(config.read_timeout, float)
    assert config.connect_timeout > 0
    assert config.read_timeout > 0


def test_the_environment_and_region_default_to_none() -> None:
    """Optional enrichment, absent unless the caller supplies it."""
    config = ReveniumConfig()

    assert config.environment is None
    assert config.region is None


def test_the_instance_is_frozen() -> None:
    """Assigning to any field raises, so a resolved config cannot drift in place."""
    config = ReveniumConfig()

    for field in dataclasses.fields(config):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(config, field.name, None)


def test_the_dataclass_is_keyword_only() -> None:
    """Positional construction is refused, so field order is not a public contract."""
    with pytest.raises(TypeError):
        ReveniumConfig("https://example.invalid/v1/traces")  # type: ignore[misc]


def test_the_repr_redacts_a_planted_api_key() -> None:
    """The key material must not survive into a log line or a traceback (T-01-19)."""
    rendered = repr(ReveniumConfig(api_key=_FAKE_METERING_KEY))

    assert _FAKE_KEY_SENTINEL not in rendered
    assert _FAKE_METERING_KEY not in rendered
    assert "api_key" in rendered


def test_the_repr_redacts_a_planted_outcome_key() -> None:
    """Both credential fields are redacted, not just the one used more often."""
    rendered = repr(ReveniumConfig(outcome_api_key="rev_sk_NOT_A_REAL_KEY"))

    assert _FAKE_KEY_SENTINEL not in rendered
    assert "outcome_api_key" in rendered


def test_the_repr_still_shows_the_non_secret_fields() -> None:
    """Redaction that hides everything makes the repr useless for diagnostics."""
    rendered = repr(ReveniumConfig(environment="staging"))

    assert "staging" in rendered
    assert DEFAULT_OTLP_TRACES_ENDPOINT in rendered


def test_construction_reads_no_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment resolution is CFG-08 in Phase 4, deliberately not here."""
    observed: list[str] = []
    real_environ_get = os.environ.get

    def _recording_get(key: str, default: Any = None) -> Any:
        observed.append(key)
        return real_environ_get(key, default)

    # Planted first, and only then is the recorder installed: ``setenv`` reads
    # ``os.environ.get`` itself to save the value it will restore, so recording
    # across it would attribute pytest's own bookkeeping to the constructor.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://example.invalid/v1/traces")
    monkeypatch.setattr(os.environ, "get", _recording_get)
    observed.clear()

    config = ReveniumConfig()

    assert observed == []
    assert config.otlp_traces_endpoint == DEFAULT_OTLP_TRACES_ENDPOINT


def test_the_module_source_opens_no_socket_and_builds_no_client() -> None:
    """Nothing in this module dials the endpoint constant it defines (T-01-24).

    **Narrowed by plan 04-02, deliberately.** This test also asserted that
    ``config.py`` contained no ``os.environ`` at all — the right assertion while
    Phase 1's module performed no resolution, and the wrong one now that CFG-08
    has landed there. The prohibition it stood for did not go away; it moved to
    ``tests/unit/test_config_resolution.py``, which pins the *count* of read
    sites at one and asserts by AST walk that the module writes none. Rewritten
    rather than deleted, following the precedent set in this repository when
    plan 03-01 replaced the scope's raise and plan 04-01 replaced the install
    stub's.

    What stays here is what this test was always about: this module builds no
    HTTP client and opens no socket, so the endpoint constant it defines is a
    string and nothing more.
    """
    source = _CONFIG_SOURCE.read_text(encoding="utf-8")

    for forbidden in ("import httpx", "import socket", "import requests", "urlopen"):
        assert forbidden not in source, f"config.py references {forbidden!r}"
