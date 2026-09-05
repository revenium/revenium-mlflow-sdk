"""Import ``revenium_mlflow`` under the socket guard and report five facts.

Run as the entry point of a fresh interpreter launched with ``PYTHONPATH``
pointing at this directory, so ``sitecustomize`` in the same directory has
already installed the socket guard by the time this file's first line executes.

The five printed lines, in order:

===========================  ==================================================
``mlflow_imported``          Whether importing the SDK dragged MLflow in (D-12).
``compat_imported``          Whether the capability probe module was loaded.
``provider_kind``            Class name of the OpenTelemetry global provider.
``provider_processors``      Span processors registered on it, by class name.
``guard_live``               Whether the guard actually blocks a connection.
===========================  ==================================================

``provider_kind`` and ``guard_live`` exist to stop the other three passing
vacuously. An empty ``provider_processors`` list is equally consistent with "no
processor is registered" and "the defensive attribute chain did not resolve on
this provider object"; the class name tells a reader which one was observed. And
a guard that silently failed to install would produce a byte-identical clean
transcript, so the probe attempts a loopback connection itself and reports
whether the guard's own error came back.

Exits non-zero, before importing anything of ours, if the guard was not loaded at
start-up — because every line below would otherwise be a measurement of nothing.
"""

import sys

if "sitecustomize" not in sys.modules:  # pragma: no cover - subprocess-only path
    raise SystemExit(
        "import-purity guard was not loaded at start-up: 'sitecustomize' is absent "
        "from sys.modules. Launch this probe with PYTHONPATH=tests/import_purity."
    )

GUARD_TOKEN: str = sys.modules["sitecustomize"].GUARD_TOKEN

# Everything above this line is guard verification; everything below it is
# observation. These imports sit here, past the guard check, rather than at the
# top of the file — hence the E402 suppressions. The check has to run first: a
# probe that imported the subject before confirming the guard was installed
# could measure an unguarded import and never notice.
#
# `socket` is already in sys.modules (sitecustomize imported it) and
# `opentelemetry.trace` only creates the API's proxy provider, so neither
# instrument perturbs what is being observed. `revenium_mlflow` is the subject:
# it is imported last, so everything in sys.modules that was not there a moment
# ago is attributable to it.
import socket  # noqa: E402

from opentelemetry import trace as otel_trace  # noqa: E402

import revenium_mlflow  # noqa: E402

#: Touched so the subject's import is a use, not dead weight a linter would
#: strip. Reading a module attribute registers nothing and opens nothing.
_SUBJECT_VERSION = revenium_mlflow.__version__


def _connect_is_blocked_by_the_guard() -> bool:
    """True only if both connection routes raise the guard's own error.

    A plain :class:`OSError` — what an unguarded loopback attempt to a closed
    port produces — deliberately counts as *not* blocked. The distinction is the
    whole point: this function has to be able to report ``False``.
    """
    try:
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)
    except RuntimeError as exc:
        if GUARD_TOKEN not in str(exc):
            return False
    except OSError:
        return False
    else:
        return False

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.01)
            sock.connect(("127.0.0.1", 9))
    except RuntimeError as exc:
        return GUARD_TOKEN in str(exc)
    except OSError:
        return False
    return False


def _registered_span_processors(provider: object) -> list[str]:
    """Class names of the span processors on the global tracer provider.

    Read defensively through ``getattr``: when nothing has initialised a real
    provider, the global is still OpenTelemetry's ``ProxyTracerProvider``, which
    carries no processor collection at all. That case yields an empty list, and
    it is the stronger PKG-09 result — not merely "our processor is absent" but
    "the global provider was never built". ``provider_kind`` is printed so the
    transcript records which of the two states produced the empty list.
    """
    active = getattr(provider, "_active_span_processor", None)
    processors = getattr(active, "_span_processors", None) or ()
    return [type(processor).__name__ for processor in processors]


global_provider = otel_trace.get_tracer_provider()

facts = {
    "mlflow_imported": "mlflow" in sys.modules,
    "compat_imported": "revenium_mlflow._compat" in sys.modules,
    "provider_kind": type(global_provider).__name__,
    "provider_processors": _registered_span_processors(global_provider),
    "guard_live": _connect_is_blocked_by_the_guard(),
}

for name, value in facts.items():
    print(f"{name}={value}")
