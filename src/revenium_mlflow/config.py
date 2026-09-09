"""The public configuration object, and where its values come from.

**The record and the policy are two things, kept apart.**
:class:`ReveniumConfig` is the record: a frozen, slotted, keyword-only
dataclass whose construction opens no socket, reads no environment variable and
dials nothing. :func:`resolve_config` is the policy: it decides which source a
value comes from. They are separated because Phases 5 and 6 both add fields to
the record without changing the policy, and because a record that read the
environment in its own constructor could never be built from literals in a test.

Frozen because a configuration that can drift after resolution turns "which
endpoint did we export to" into a question with no stable answer. Keyword-only
because field order would otherwise become a public contract that reordering
breaks.

**What still is not here.** Endpoint well-formedness validation and
double-suffix diagnosis are EXP-05, plan 04-05. Credential-scope detection is
JOB-05, Phase 5. :func:`compose_otlp_traces_endpoint` raises on the cases where
proceeding would silently produce a wrong URL, and names 04-05 for the rest.

**Environment variable names are inherited, not invented (CFG-08).** Counted
across the installed ``revenium-python-sdk`` 0.7.0 wheel:
``REVENIUM_METERING_API_KEY`` (27 uses), ``REVENIUM_TEAM_ID`` (16),
``REVENIUM_METERING_BASE_URL`` (16), ``REVENIUM_OUTCOME_API_KEY`` (9),
``REVENIUM_ENVIRONMENT`` (10), ``REVENIUM_REGION`` (10). A customer already
running the house SDK has these exported; a parallel spelling would mean their
working configuration is silently ignored here. Exactly one name is minted:
``REVENIUM_OTLP_TRACES_ENDPOINT``, for the field no sibling has.

**This module reads the environment and never writes it (CFG-03).** It writes no
variable at all, and in particular never
``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` or ``OTEL_EXPORTER_OTLP_TRACES_HEADERS``:
both are process-global and single-valued, so writing the Revenium credential
into the headers variable would ship it to every OTLP destination the customer
has configured, and writing the endpoint variable changes which processors
MLflow builds — measured, it *replaces* the Tracking Server export rather than
adding to it. ``tests/unit/test_otel_slot_untouched.py`` enforces that
mechanically over every module in this package.

.. warning::

   **Unresolved and routed to a human: ``api.revenium.ai`` versus
   ``api.revenium.io``.** The sibling ``revenium-python-sdk`` defaults its
   metering base URL to ``https://api.revenium.ai/meter/``
   (``revenium_middleware/_metering/_client.py:93``). This SDK's
   :data:`DEFAULT_OTLP_TRACES_ENDPOINT` is on ``api.revenium.io``, source-verified
   from the backend and never runtime-verified. Different top-level domain.
   Whether the two deployments legitimately differ, or one of the two values is
   stale, is not answerable from this repository — the project forbids the call
   that would settle it. Until a human settles it, an operator pointing at a
   non-production deployment should set ``REVENIUM_METERING_BASE_URL``
   explicitly rather than relying on either default.
"""

import dataclasses
import os
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from revenium_mlflow.errors import ConfigurationError

__all__ = [
    "DEFAULT_OTLP_TRACES_ENDPOINT",
    "ENVIRONMENT_VARIABLE_NAMES",
    "METERING_BASE_URL_VARIABLE",
    "ReveniumConfig",
    "compose_otlp_traces_endpoint",
    "resolve_config",
]

#: The Revenium OTLP traces route, composed from the backend source recorded in
#: PROJECT.md: the ``/meter`` context path, the ``/v2/otlp`` mapping, and the
#: ``/v1/traces`` POST advertised in ``MeteringAuthOpenApiCustomizer.kt``.
#:
#: Source-verified, **not** runtime-verified — this project makes no call to
#: ``api.revenium.io`` during development or testing. It remains overridable
#: (CFG-08); this is the default, not a constraint.
DEFAULT_OTLP_TRACES_ENDPOINT: Final[str] = "https://api.revenium.io/meter/v2/otlp/v1/traces"

#: The OTLP protocol Revenium's ingest speaks. Named as a constant so the one
#: place it is spelled is the one place it can be got wrong.
_HTTP_PROTOBUF: Final[str] = "http/protobuf"

#: Stands in for either credential in :meth:`ReveniumConfig.__repr__`. A fixed
#: marker rather than a length-preserving mask: echoing the length of a secret
#: is still echoing something about the secret.
_REDACTED: Final[str] = "***redacted***"

#: Conservative transport defaults (HTTP-01). Explicit on every request, because
#: a client with no timeout turns a slow Revenium into a hung application — and
#: telemetry is the one subsystem that must never do that.
_DEFAULT_CONNECT_TIMEOUT: Final[float] = 5.0
_DEFAULT_READ_TIMEOUT: Final[float] = 30.0

#: Which environment variable supplies which :class:`ReveniumConfig` field.
#:
#: Keyed by *field name* rather than by variable name, so the map can be checked
#: against :func:`dataclasses.fields` instead of against a transcription of it —
#: a typo in a key would otherwise resolve nothing and look exactly like an
#: unset variable. Read-only, so a caller cannot re-point a name at runtime and
#: leave two answers to "where did this value come from".
#:
#: Every name but one is inherited from the sibling ``revenium-python-sdk``; see
#: this module's docstring for the occurrence counts.
#: ``REVENIUM_OTLP_TRACES_ENDPOINT`` is the single minted name, because no
#: sibling has an OTLP traces route.
ENVIRONMENT_VARIABLE_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "otlp_traces_endpoint": "REVENIUM_OTLP_TRACES_ENDPOINT",
        "api_key": "REVENIUM_METERING_API_KEY",
        "outcome_api_key": "REVENIUM_OUTCOME_API_KEY",
        "billing_team_id": "REVENIUM_TEAM_ID",
        "environment": "REVENIUM_ENVIRONMENT",
        "region": "REVENIUM_REGION",
    }
)

#: The house base-URL variable, held separately because it does not map onto a
#: field: it supplies a *base* that :func:`compose_otlp_traces_endpoint` turns
#: into ``otlp_traces_endpoint``.
#:
#: This is the variable an operator sets to point at a non-production Revenium
#: deployment, and it is the one every other Revenium SDK already honours
#: (``revenium_middleware/_metering/_client.py:91-93``). Without it, this SDK
#: would be the only one requiring the caller to know the whole
#: ``/meter/v2/otlp/v1/traces`` path.
METERING_BASE_URL_VARIABLE: Final[str] = "REVENIUM_METERING_BASE_URL"

#: The Revenium metering context path, as one path segment. The sibling's
#: ``_normalize_base_url`` adds it when absent and does not duplicate it when
#: present; this module follows that rule so the same base string means the same
#: deployment in both SDKs.
_METER_PATH_SEGMENT: Final[str] = "meter"

#: The OTLP traces route composed onto the metering base, as path segments.
#: Spelled as segments rather than as the string ``"/v2/otlp/v1/traces"`` so the
#: double-suffix check below can compare segment lists — a substring comparison
#: would treat ``/metering`` as a ``/meter`` match.
_OTLP_TRACES_PATH_SEGMENTS: Final[tuple[str, ...]] = ("v2", "otlp", "v1", "traces")

#: The tail that identifies a string as an OTLP traces *endpoint* rather than a
#: base. The OTLP HTTP specification fixes this path, so any base ending in it
#: was already a full endpoint and composing onto it is the ``/v1/traces/v1/traces``
#: bug (EXP-05, plan 04-05).
_TRACES_ENDPOINT_TAIL: Final[tuple[str, ...]] = ("v1", "traces")


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class ReveniumConfig:
    """Every setting the SDK reads, resolved once and then immutable.

    Phase 1 defines the fields and their defaults only. Nothing here validates,
    resolves, or contacts anything.
    """

    #: Where traces are POSTed. Defaults to
    #: :data:`DEFAULT_OTLP_TRACES_ENDPOINT` and is overridable by argument, and
    #: from Phase 4 by environment variable (CFG-08).
    otlp_traces_endpoint: str = DEFAULT_OTLP_TRACES_ENDPOINT

    #: The OTLP wire protocol, always ``http/protobuf`` (CFG-09).
    #:
    #: Explicit and never optional, for a specific reason: MLflow's own default
    #: is ``grpc``, and falling through to it raises ``MlflowException`` at
    #: provider init without the gRPC exporter installed — while Revenium's
    #: ingest is HTTP plus ``application/x-protobuf`` regardless. There is no
    #: configuration in which the fallthrough is the right answer, so the value
    #: is stated here rather than inherited from anywhere.
    otlp_protocol: str = _HTTP_PROTOBUF

    #: The metering credential (``rev_mk_``), used for telemetry ingest.
    #:
    #: Separate from :attr:`outcome_api_key` because the two carry different
    #: scopes. That split is an inherited design decision in the Revenium
    #: platform, not a defect this SDK papers over: a metering key sent to a
    #: write endpoint is rejected remotely with a message that says nothing
    #: about scope, which is why Phase 5 checks it locally and raises
    #: :class:`~revenium_mlflow.errors.CredentialScopeError` first (JOB-05).
    api_key: str | None = None

    #: The write-scope credential (``rev_sk_``), used for job outcomes and tool
    #: events. See :attr:`api_key` for why this is a second field (JOB-04).
    outcome_api_key: str | None = None

    #: The Revenium billing tenant this process reports against.
    #:
    #: Required explicitly and never inferred from an API-key prefix. Inferring
    #: it would mean a key rotation could silently re-tenant a customer's
    #: traffic, and the resulting invoice would be wrong in a way no error
    #: message points at.
    billing_team_id: str | None = None

    #: Connect timeout, in seconds, on every outbound request (HTTP-01).
    connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT

    #: Read timeout, in seconds, on every outbound request (HTTP-01).
    read_timeout: float = _DEFAULT_READ_TIMEOUT

    #: Whether a telemetry failure is swallowed rather than raised (HTTP-08).
    #:
    #: Defaults to ``True``, the telemetry default: a side-car that takes the
    #: application down with it has made the outage worse than the missing
    #: data. Operators who would rather fail loudly set this ``False``.
    fail_open: bool = True

    #: Whether the completion-fallback metering path is enabled (FB-01).
    #:
    #: Defaults to ``False``. The fallback can meter a call the OTLP path has
    #: already exported, and double-counting a model call is a billing error
    #: rather than a monitoring gap, so it is opt-in.
    enable_completion_fallback: bool = False

    #: Optional deployment environment recorded on exported spans.
    environment: str | None = None

    #: Optional deployment region recorded on exported spans.
    region: str | None = None

    def __repr__(self) -> str:
        """Render every field, with both credentials replaced by a fixed marker.

        Hand-written rather than relying on per-field ``repr=False``, because
        the goal is that the credential *fields* stay visible — a reader has to
        be able to tell "set" from "unset" — while their values never are.

        Both fields are ``None`` at this point in the project and this method
        still redacts them. That is the point: the redaction has to be in place
        before the first key can reach the object, not added in the commit that
        first puts one there. A configuration object reaches a log line or a
        traceback frame without anyone deciding that it should (T-01-19).
        """
        rendered: list[str] = []
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if field.name in _REDACTED_FIELDS and value is not None:
                rendered.append(f"{field.name}={_REDACTED}")
            else:
                rendered.append(f"{field.name}={value!r}")
        return f"{type(self).__name__}({', '.join(rendered)})"


#: The fields :meth:`ReveniumConfig.__repr__` never echoes. Defined after the
#: class so it can be read as the answer to "which of those fields are secret".
_REDACTED_FIELDS: Final[frozenset[str]] = frozenset({"api_key", "outcome_api_key"})


def compose_otlp_traces_endpoint(base_url: str) -> str:
    """Compose the Revenium OTLP traces route onto a metering base URL.

    Args:
        base_url: A Revenium metering base, with or without its ``/meter``
            context path and with or without a trailing slash. This is the
            value of :data:`METERING_BASE_URL_VARIABLE`.

    Returns:
        The full OTLP traces endpoint. Composing the house base
        ``https://api.revenium.io/meter/`` reproduces
        :data:`DEFAULT_OTLP_TRACES_ENDPOINT` exactly, and
        ``tests/unit/test_config_resolution.py`` asserts that rather than
        trusting it — a comment cannot notice the day one of the two is edited
        and the other is not.

    Raises:
        ConfigurationError: The base is blank, carries a query or fragment,
            lacks a scheme or host, is already a full OTLP traces endpoint, or
            contains a ``/meter`` segment that is not its last. Each of those is
            a case where proceeding would produce a URL the operator did not
            ask for, and the only signal would be a remote 404 naming neither
            the variable nor the mistake.

    **Why it raises on a base that is already an endpoint.** Composition is
    precisely where ``/v1/traces/v1/traces`` comes from. Detecting and
    diagnosing malformed endpoints in general is EXP-05, owned by plan 04-05;
    this function's job is to refuse the one case it would otherwise create
    silently, and to name the variable the operator should have used instead.

    **Why it raises on a mid-path ``/meter``.** The sibling's
    ``_normalize_base_url`` truncates everything after it, which is a guess with
    no error attached — and the guess discards path segments the operator typed
    on purpose. Refusing costs them one clear message.
    """
    candidate = base_url.strip()
    if not candidate:
        raise ConfigurationError(
            f"{METERING_BASE_URL_VARIABLE} is set but empty. Unset it to use the "
            f"default route, or set it to a Revenium base URL such as "
            f"https://api.revenium.io/meter/."
        )

    split = urlsplit(candidate)
    if split.query or split.fragment:
        raise ConfigurationError(
            f"{METERING_BASE_URL_VARIABLE}={candidate!r} carries a query or fragment. "
            "A metering base URL is a scheme, a host and an optional path; the OTLP "
            "traces route is composed onto it and there is nowhere for a query to go."
        )
    if not split.scheme or not split.netloc:
        raise ConfigurationError(
            f"{METERING_BASE_URL_VARIABLE}={candidate!r} has no scheme and host. "
            "Include them, as in https://api.revenium.io/meter/. Fuller URL "
            "validation is plan 04-05 (EXP-05); this is the presence check "
            "without which there is nothing to compose onto."
        )

    segments = [segment for segment in split.path.split("/") if segment]
    lowered = [segment.lower() for segment in segments]

    if _ends_with(lowered, _OTLP_TRACES_PATH_SEGMENTS) or _ends_with(
        lowered, _TRACES_ENDPOINT_TAIL
    ):
        raise ConfigurationError(
            f"{METERING_BASE_URL_VARIABLE}={candidate!r} is already a full OTLP traces "
            f"endpoint, not a base. Composing the traces route onto it would produce "
            f"/v1/traces/v1/traces, which reaches the far end as a 404 that names "
            f"nothing. Set {ENVIRONMENT_VARIABLE_NAMES['otlp_traces_endpoint']} to this "
            f"value instead, or set {METERING_BASE_URL_VARIABLE} to just the base "
            f"(for example https://api.revenium.io/meter/). Detecting a doubled suffix "
            "wherever else it can arise is plan 04-05 (EXP-05)."
        )

    if _METER_PATH_SEGMENT in lowered and lowered[-1] != _METER_PATH_SEGMENT:
        raise ConfigurationError(
            f"{METERING_BASE_URL_VARIABLE}={candidate!r} has a {_METER_PATH_SEGMENT!r} "
            "path segment that is not the last one, so where the OTLP traces route "
            "should attach is ambiguous. Set it to the base that ends at "
            f"/{_METER_PATH_SEGMENT}, or set "
            f"{ENVIRONMENT_VARIABLE_NAMES['otlp_traces_endpoint']} to the full endpoint."
        )

    if not lowered or lowered[-1] != _METER_PATH_SEGMENT:
        segments = [*segments, _METER_PATH_SEGMENT]

    path = "/" + "/".join([*segments, *_OTLP_TRACES_PATH_SEGMENTS])
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def _ends_with(segments: list[str], tail: tuple[str, ...]) -> bool:
    """Whether ``segments`` ends with ``tail``, compared segment by segment.

    Segment-wise rather than by string suffix: ``/metering`` ends with the
    *characters* of ``meter`` and is a different path.
    """
    return len(segments) >= len(tail) and tuple(segments[-len(tail) :]) == tail


def resolve_config(
    *,
    config: ReveniumConfig | None = None,
    otlp_traces_endpoint: str | None = None,
    api_key: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ReveniumConfig:
    """Decide where every configuration value comes from, once (CFG-08).

    Args:
        config: A fully-formed configuration. When supplied, **the environment
            is not read at all** — see below.
        otlp_traces_endpoint: Overrides the resolved traces endpoint.
        api_key: The metering credential (``rev_mk_``) for trace ingest.
        environ: The mapping to read. Defaults to the process environment. The
            parameter exists so tests supply values instead of monkeypatching a
            module, and so this module has exactly one read site.

    Returns:
        A new frozen :class:`ReveniumConfig`. Always a new instance: resolution
        that mutated its input would move "which endpoint did we export to"
        after the fact, for every other holder of the object.

    Raises:
        ConfigurationError: :data:`METERING_BASE_URL_VARIABLE` is set to
            something that cannot be composed. Nothing else is validated here —
            a malformed full endpoint is EXP-05 (plan 04-05), and a missing
            credential is raised by
            :func:`revenium_mlflow.tracing.install.configure_tracing`, which is
            where the caller has the context to fix it.

    **Precedence is per field, not per source**, highest first:

    1. the explicit keyword argument
    2. the Revenium-named environment variable for that field
    3. for the traces endpoint only, :data:`METERING_BASE_URL_VARIABLE` with the
       OTLP route composed onto it
    4. the :class:`ReveniumConfig` default

    Per field rather than per source because the alternative — "an argument
    anywhere means the environment is ignored" — reads tidier and silently drops
    a credential the operator did set, producing a ``ConfigurationError`` that
    names a value they can see in their own shell.

    **A supplied ``config`` bypasses the environment entirely.** A caller who
    built a :class:`ReveniumConfig` has stated every value explicitly; merging
    the environment into it would mean their code says one thing and the process
    does another, decided by a variable invisible from the call site. Explicit
    arguments still override it, because an argument is the most local statement
    of intent available.

    **A blank variable is treated as unset.** ``export REVENIUM_METERING_KEY=``
    is how a shell profile spells "unset" by accident, and an empty-string
    credential would pass an ``is not None`` check and then be rejected remotely
    — the silent-401 shape this SDK raises to avoid.
    """
    if config is not None:
        return dataclasses.replace(
            config,
            otlp_traces_endpoint=otlp_traces_endpoint or config.otlp_traces_endpoint,
            api_key=api_key or config.api_key,
        )

    # The one read site in this module. Never a write: see the module docstring
    # and ``tests/unit/test_otel_slot_untouched.py``, which enforces it by an AST
    # walk over every module in the shipped package.
    source: Mapping[str, str] = os.environ if environ is None else environ

    def read(field: str) -> str | None:
        """The variable for ``field``, with blank treated as unset."""
        value = source.get(ENVIRONMENT_VARIABLE_NAMES[field])
        return value.strip() or None if value is not None else None

    base_url = source.get(METERING_BASE_URL_VARIABLE)
    composed = (
        compose_otlp_traces_endpoint(base_url)
        if base_url is not None and base_url.strip()
        else None
    )

    defaults = ReveniumConfig()
    return dataclasses.replace(
        defaults,
        otlp_traces_endpoint=(
            otlp_traces_endpoint
            or read("otlp_traces_endpoint")
            or composed
            or defaults.otlp_traces_endpoint
        ),
        api_key=api_key or read("api_key"),
        outcome_api_key=read("outcome_api_key"),
        billing_team_id=read("billing_team_id"),
        environment=read("environment"),
        region=read("region"),
    )
