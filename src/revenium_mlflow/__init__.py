"""Revenium MLflow SDK — economic telemetry for MLflow-instrumented applications.

This package lets an application already instrumented with MLflow tracing send
attribution, tool-metering, and job-outcome signals to Revenium without forking
or modifying MLflow. MLflow remains the engineering system of record for traces,
evaluation, and experiments; Revenium becomes the authoritative rating source.

This is a Revenium product. It is neither part of, nor endorsed by, the MLflow
project.

This module is deliberately inert: it imports nothing from ``mlflow``,
``opentelemetry``, or ``httpx``, performs no network I/O, and installs no global
tracing state. Importing it must never raise. The MLflow capability probe runs
at configure time, not import time.
"""

from importlib.metadata import PackageNotFoundError, version as _version

#: Fallback used when no ``revenium-mlflow`` distribution is installed, which is
#: the case for a direct run out of the source tree. The authoritative value is
#: the ``version`` literal in ``pyproject.toml``; the two are asserted equal by
#: ``tests/unit/test_package_metadata.py`` whenever a distribution is present.
_FALLBACK_VERSION = "0.1.0"

try:
    __version__ = _version("revenium-mlflow")
except PackageNotFoundError:  # pragma: no cover - source-tree run without install
    __version__ = _FALLBACK_VERSION

__all__ = ["__version__"]
