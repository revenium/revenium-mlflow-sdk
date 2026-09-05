"""Block outbound connections before any user module runs (PKG-09, T-01-32).

CPython's ``site`` module imports ``sitecustomize`` automatically at interpreter
start-up if it can find it on ``sys.path``. The probe subprocess is launched with
``PYTHONPATH`` pointing at this directory precisely for that reason: it is the
only hook that fires *before* ``revenium_mlflow`` is even located, let alone
executed. A guard installed any later — in a ``-c`` preamble, in a conftest
fixture, at the top of the probe body — would leave a window in which an
import-time socket call could still succeed, and the proof would have a hole
exactly the size of the thing it is meant to exclude.

The replacements raise :class:`RuntimeError` rather than :class:`OSError` on
purpose. An ``OSError`` is indistinguishable from an ordinary connection failure,
so a package that swallowed it would produce a clean transcript while genuinely
having tried to reach the network. ``RuntimeError`` carrying a single searchable
token makes any block attributable to this guard and to nothing else.

This module is never imported by the pytest session. It is loaded only in the
probe subprocess, where mutating the ``socket`` module affects nothing else.
"""

import socket
from typing import Any, NoReturn

#: One searchable token, so a block is attributable to this guard rather than to
#: a coincidental failure. The probe imports this name rather than restating the
#: string, so the two cannot drift.
GUARD_TOKEN = "REVENIUM_IMPORT_PURITY_SOCKET_GUARD"

_MESSAGE = (
    f"{GUARD_TOKEN}: an outbound connection was attempted while the "
    f"import-purity guard was installed"
)


def _blocked(*_args: Any, **_kwargs: Any) -> NoReturn:
    """Refuse every connection attempt, loudly and attributably."""
    raise RuntimeError(_MESSAGE)


# The three entry points every stdlib and third-party client bottoms out in.
# `socket.socket` is a Python-level subclass of the C `_socket.socket`, so
# assigning here shadows the inherited method for every instance, including ones
# created before this line runs.
socket.socket.connect = _blocked  # type: ignore[method-assign]
socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
socket.create_connection = _blocked  # type: ignore[assignment]
