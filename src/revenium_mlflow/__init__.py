"""Revenium MLflow SDK — economic telemetry for MLflow-instrumented applications.

This package lets an application already instrumented with MLflow tracing send
attribution, tool-metering, and job-outcome signals to Revenium without forking
or modifying MLflow. MLflow remains the engineering system of record for traces,
evaluation, and experiments; Revenium becomes the authoritative rating source.

This is a Revenium product. It is neither part of, nor endorsed by, the MLflow
project.

**The published surface is flat (D-01).** Every name a user needs is imported
from here — ``from revenium_mlflow import configure_tracing, attribution``
— and never from a submodule. The internal split into ``tracing`` (the OTLP
path) and ``metering`` (the Revenium HTTP path) exists precisely so that
structure can change without changing anyone's import line, and the two never
import each other, which is what keeps trace export installable with no
Revenium HTTP credential at all.

**What is on the surface, and why more than six names (D-02).** The six
callables are the API. The exception hierarchy is here because a user has to be
able to write ``except``; the handle, config, and diagnostics types because
``py.typed`` (PKG-05) means users annotate against them; the 21 attribute-key
constants because Revenium's ingest silently *drops* a key it does not
recognise, so a hand-typed ``"revenium.subscriber.emial"`` becomes an invisible
billing-attribution loss rather than an error.

**This module stays inert (D-12, PKG-09).** It imports neither ``mlflow`` nor
the compatibility probe, performs no network I/O, reads no environment variable,
and installs no global tracing state. Importing it must never raise. The MLflow
capability probe runs inside :func:`configure_tracing`, where a failure is
actionable and in context. The one non-stdlib import reached transitively from
here is ``opentelemetry.sdk.trace``, the public home of the ``SpanProcessor``
base class; it registers nothing and opens nothing.

**Nothing here is a silent no-op (OI-02).** Phase 1 implements no MLflow
behaviour. Every public callable raises :class:`NotImplementedError` naming the
phase that implements it, and the span processor cannot be constructed at all —
because a stub that quietly succeeds in a billing path produces a wrong invoice
instead of an error.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from .attributes import (
    ATTRIBUTE_CAPS,
    REVENIUM_AGENT_NAME,
    REVENIUM_ATTRIBUTE_KEYS,
    REVENIUM_JOB_ID,
    REVENIUM_JOB_NAME,
    REVENIUM_JOB_TYPE,
    REVENIUM_JOB_VERSION,
    REVENIUM_MIDDLEWARE_SOURCE,
    REVENIUM_OPERATION_SUBTYPE,
    REVENIUM_ORGANIZATION_NAME,
    REVENIUM_PRODUCT_NAME,
    REVENIUM_REQUEST_STREAM,
    REVENIUM_RETRY_NUMBER,
    REVENIUM_SQUAD_ID,
    REVENIUM_SQUAD_NAME,
    REVENIUM_SQUAD_ROLE,
    REVENIUM_SUBSCRIBER_EMAIL,
    REVENIUM_SUBSCRIBER_ID,
    REVENIUM_SUBSCRIPTION_ID,
    REVENIUM_TASK_TYPE,
    REVENIUM_TRACE_NAME,
    REVENIUM_TRACE_TYPE,
    REVENIUM_TRANSACTION_NAME,
)
from .config import DEFAULT_OTLP_TRACES_ENDPOINT, ReveniumConfig
from .diagnostics import ConnectionDiagnostics, validate_connection
from .errors import (
    ConfigurationError,
    CredentialScopeError,
    ExportError,
    OrderingError,
    ReveniumMLflowError,
    UnsupportedMLflowError,
)
from .metering import meter_tool_span, report_job_outcome
from .tracing import (
    ReveniumAttributionSpanProcessor,
    ReveniumExportHandle,
    attribution,
    configure_tracing,
)

#: Fallback used when no ``revenium-mlflow`` distribution is installed, which is
#: the case for a direct run out of the source tree. The authoritative value is
#: the ``version`` literal in ``pyproject.toml``; the two are asserted equal by
#: ``tests/unit/test_package_metadata.py`` whenever a distribution is present.
_FALLBACK_VERSION = "0.1.0"

try:
    __version__ = _version("revenium-mlflow")
except PackageNotFoundError:  # pragma: no cover - source-tree run without install
    __version__ = _FALLBACK_VERSION

# Sorted, not grouped, and the sorting is enforced rather than chosen (RUF022).
#
# The surface is five groups — the six callables, the types a user annotates
# against, the exception hierarchy, the 21 attribute-key constants with their
# tuple and cap table, and the version. Each group is already legible above as
# its own ``from .<module> import`` block, which is where its rationale belongs.
#
# Inline group comments were written here first and removed: the lint rule sorts
# this list and strands each comment against whatever name happens to follow it,
# which reads as a mislabelled group rather than as no label at all. Suppressing
# the rule to keep the grouping was the other option and was rejected — this
# project's gate is deliberately unsuppressable (D-08), and a cosmetic exemption
# is exactly how a wall like that stops meaning anything.
__all__ = [
    "ATTRIBUTE_CAPS",
    "DEFAULT_OTLP_TRACES_ENDPOINT",
    "REVENIUM_AGENT_NAME",
    "REVENIUM_ATTRIBUTE_KEYS",
    "REVENIUM_JOB_ID",
    "REVENIUM_JOB_NAME",
    "REVENIUM_JOB_TYPE",
    "REVENIUM_JOB_VERSION",
    "REVENIUM_MIDDLEWARE_SOURCE",
    "REVENIUM_OPERATION_SUBTYPE",
    "REVENIUM_ORGANIZATION_NAME",
    "REVENIUM_PRODUCT_NAME",
    "REVENIUM_REQUEST_STREAM",
    "REVENIUM_RETRY_NUMBER",
    "REVENIUM_SQUAD_ID",
    "REVENIUM_SQUAD_NAME",
    "REVENIUM_SQUAD_ROLE",
    "REVENIUM_SUBSCRIBER_EMAIL",
    "REVENIUM_SUBSCRIBER_ID",
    "REVENIUM_SUBSCRIPTION_ID",
    "REVENIUM_TASK_TYPE",
    "REVENIUM_TRACE_NAME",
    "REVENIUM_TRACE_TYPE",
    "REVENIUM_TRANSACTION_NAME",
    "ConfigurationError",
    "ConnectionDiagnostics",
    "CredentialScopeError",
    "ExportError",
    "OrderingError",
    "ReveniumAttributionSpanProcessor",
    "ReveniumConfig",
    "ReveniumExportHandle",
    "ReveniumMLflowError",
    "UnsupportedMLflowError",
    "__version__",
    "attribution",
    "configure_tracing",
    "meter_tool_span",
    "report_job_outcome",
    "validate_connection",
]
