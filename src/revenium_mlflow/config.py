"""The public configuration object, as a typed record of settled decisions.

**What this module is not, in Phase 1.** It performs no environment-variable
resolution, no endpoint normalisation, no credential-scope detection and no
validation. Those are CFG-08, EXP-05 and JOB-05, in Phases 4 and 5. What exists
here is the shape and the defaults — published now because the package ships
``py.typed`` (PKG-05) and D-02 puts this type on the public surface, so a user
annotating their own code against it should not have to wait for the phases that
fill in the behaviour.

Constructing :class:`ReveniumConfig` opens no socket, reads no environment
variable, and dials nothing. :data:`DEFAULT_OTLP_TRACES_ENDPOINT` is a string.

The class is frozen, slotted, and keyword-only. Frozen because a configuration
that can drift after resolution turns "which endpoint did we export to" into a
question with no stable answer. Keyword-only because field order would otherwise
become a public contract that reordering breaks, and this record will keep
growing through Phase 6.
"""

import dataclasses
from typing import Final

__all__ = ["DEFAULT_OTLP_TRACES_ENDPOINT", "ReveniumConfig"]

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
