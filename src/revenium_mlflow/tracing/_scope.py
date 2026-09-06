"""The one ``ContextVar`` the attribution scope writes and the processor reads.

**This module exists so there can be exactly one of it.** Three consumers depend
on the scoped attribution state — :func:`attribution`, which writes it;
:class:`ReveniumAttributionSpanProcessor`, which reads it for every span in the
host process; and Phase 3's later cap validation, which inspects it — and a
``ContextVar`` that two of those modules could each declare is the one bug in
this design that no test would catch. Two variables, both named
``"revenium_mlflow.attribution"``, are two entirely separate variables at
runtime: the writer would set one and the reader would read the other, forever,
and the reader's would always be empty. Every behavioural test would go red on
day one, which is the good case; the bad case is a later refactor that splits
them apart with the tests still passing because each half was moved with its own
copy. One module owns the variable, and nothing else declares one.

**The snapshot is immutable and copy-on-write, and that is a concurrency
requirement rather than a style (T-03-01).** Entering a nested scope produces a
*new* snapshot merged over the outer one; it never mutates the outer object.
The outer object is simultaneously what the outer scope's ``Token`` will restore
and what a sibling ``asyncio`` task — which inherited the same object when its
``Context`` was copied at task creation — is concurrently reading. Mutating it
in place would let one request's attribution appear on another request's span,
which is a cross-tenant billing and privacy failure rather than a race that
merely loses data. :class:`types.MappingProxyType` makes the sharing safe by
making the shared object unwritable.

**Nothing here imports MLflow, and nothing here imports OpenTelemetry either.**
The MLflow prohibition is D-12: this module is reached from ``import
revenium_mlflow`` and that import must stay inert. The absence of an
OpenTelemetry import is not required by anything — it is simply what fell out of
the module having no span in it. Attribution values are plain ``str``, ``int``
and ``bool``, which is a subset of OpenTelemetry's ``AttributeValue``, so the
processor can hand them straight to ``span.set_attribute`` with no conversion
step and this module stays pure standard library.

Everything is imported under a private alias so this module's public surface is
exactly the names in ``__all__``.
"""

import types as _types
from collections.abc import Mapping as _Mapping
from contextvars import ContextVar as _ContextVar
from contextvars import Token as _Token
from typing import Final as _Final
from typing import TypeAlias as _TypeAlias

from revenium_mlflow.attributes import REVENIUM_ATTRIBUTE_KEYS as _REVENIUM_ATTRIBUTE_KEYS
from revenium_mlflow.attributes import (
    REVENIUM_MIDDLEWARE_SOURCE as _REVENIUM_MIDDLEWARE_SOURCE,
)

__all__ = [
    "DEFAULT_MIDDLEWARE_SOURCE",
    "PARAMETER_TO_ATTRIBUTE_KEY",
    "AttributionSnapshot",
    "AttributionValue",
    "current",
    "enter",
    "leave",
    "resolve_attributes",
]

#: Every type an ATTR-07 value can be. ``int`` carries ``retry_number`` and
#: ``bool`` carries ``request_stream``; the other nineteen are ``str``. Declared
#: as this union rather than as OpenTelemetry's ``AttributeValue`` because that
#: type also admits sequences, and no attribution key is a sequence — a narrower
#: alias is what makes ``span.set_attribute`` a no-conversion hand-off that the
#: type checker can verify rather than one it has to be told to trust.
AttributionValue: _TypeAlias = str | int | bool

#: The scoped attribution, keyed by :func:`attribution`'s *parameter* names
#: rather than by ``revenium.*`` keys. Parameter names are what the caller wrote
#: and therefore what a validation error must name back at them (ATTR-09, plan
#: 03-04); the translation to wire keys happens once, in
#: :func:`resolve_attributes`, at the point the values become span attributes.
AttributionSnapshot: _TypeAlias = _Mapping[str, AttributionValue]

#: The prefix every ATTR-07 key carries, stripped to produce a parameter name.
_KEY_PREFIX: _Final[str] = "revenium."

#: Parameter name to ``revenium.*`` key, derived by the same one mechanical rule
#: ``attribution.py``'s docstring states and ``tests/unit/test_attribution_signature.py``
#: recomputes: drop the ``revenium.`` prefix, replace dots with underscores.
#:
#: **Derived rather than written out, and that is what keeps this wave honest
#: about its scope.** Plan 03-01 needs one key to resolve — ``subscriber_id`` —
#: and plan 03-02 owns the full 21-key work: the type coercion, the caps, the
#: ``middleware.source`` default and the tests that prove each key individually.
#: A table that special-cased ``subscriber_id`` would have made the other twenty
#: parameters accept a value and silently discard it, which is precisely the
#: failure the 21 explicit parameters exist to eliminate. Deriving the whole
#: table is both less code and the only version with no silent drop in it.
PARAMETER_TO_ATTRIBUTE_KEY: _Final[_Mapping[str, str]] = _types.MappingProxyType(
    {key.removeprefix(_KEY_PREFIX).replace(".", "_"): key for key in _REVENIUM_ATTRIBUTE_KEYS}
)

#: The value :data:`attributes.REVENIUM_MIDDLEWARE_SOURCE` takes when a caller
#: inside an active scope supplied none (ATTR-08, and a Key Decision in
#: PROJECT.md). It names *this* SDK, which is the whole point of the field:
#: Revenium uses it to tell which middleware produced a record, and a record
#: from this package that left it blank would be unattributable to a producer.
#:
#: **Applied here rather than as ``attribution()``'s parameter default.** The
#: published signature says every one of the 21 parameters defaults to ``None``
#: and ``test_attribution_signature.py`` pins that in
#: ``test_every_attribution_parameter_defaults_to_none``. Moving the literal into
#: ``attribution()``'s signature would be a published-signature
#: change made silently, and it would break the ``None``-means-silence contract
#: for that one parameter — the caller could no longer tell "I said nothing"
#: apart from "I said ``mlflow``", which is the exact distinction
#: :func:`enter` preserves for the other twenty.
DEFAULT_MIDDLEWARE_SOURCE: _Final[str] = "mlflow"

#: The value outside every scope. A shared, empty, unwritable mapping rather than
#: ``None``: ``current()`` then has one return type, and the processor's hot-path
#: guard is a falsiness check on a mapping rather than a ``None`` check that
#: someone will later "simplify" into one.
_EMPTY: _Final[AttributionSnapshot] = _types.MappingProxyType({})

#: The variable itself. Module-level, because a ``ContextVar`` created inside a
#: function is a new variable on every call — the documented requirement, and a
#: mistake that presents as attribution silently never arriving.
_ATTRIBUTION: _Final[_ContextVar[AttributionSnapshot]] = _ContextVar(
    "revenium_mlflow.attribution", default=_EMPTY
)


def current() -> AttributionSnapshot:
    """The attribution in effect on this task or thread, right now.

    Returns:
        An unwritable snapshot keyed by parameter name, empty outside every
        scope. Never ``None``.
    """
    return _ATTRIBUTION.get()


def enter(values: _Mapping[str, AttributionValue | None], /) -> _Token[AttributionSnapshot]:
    """Install ``values`` merged over whatever is currently in effect.

    Args:
        values: Parameter name to value. A ``None`` value means "say nothing
            about this key" — the meaning :func:`attribution`'s docstring
            publishes — so it is dropped rather than recorded, and it does not
            clear an outer scope's value for the same key. Clearing an inherited
            value is not something the published signature can express, and
            inventing a spelling for it here would make ``None`` mean two things.

    Returns:
        The ``Token`` that :func:`leave` restores. The caller must pass it to
        :func:`leave` from a ``finally``.

    The merge is copy-on-write: a brand-new mapping is built and the previous one
    is left exactly as it was. See the module docstring for why in-place mutation
    is a cross-tenant failure rather than a lost write.
    """
    supplied = {name: value for name, value in values.items() if value is not None}
    merged: AttributionSnapshot = _types.MappingProxyType({**_ATTRIBUTION.get(), **supplied})
    return _ATTRIBUTION.set(merged)


def leave(token: _Token[AttributionSnapshot], /) -> None:
    """Restore whatever :func:`enter` displaced.

    Args:
        token: The token :func:`enter` returned.

    ``reset`` rather than a re-``set`` of a remembered previous value: only
    ``reset`` restores the *absence* of a value distinctly from the presence of
    an empty one, and only ``reset`` is defined to raise when a token from a
    different ``Context`` is passed instead of quietly installing state on the
    wrong task.
    """
    _ATTRIBUTION.reset(token)


def resolve_attributes(snapshot: AttributionSnapshot, /) -> dict[str, AttributionValue]:
    """Turn a snapshot into the ``revenium.*`` attributes a processor writes.

    Args:
        snapshot: Usually the result of :func:`current`.

    Returns:
        A plain mutable ``dict`` keyed by ``revenium.*`` wire key, carrying
        :data:`DEFAULT_MIDDLEWARE_SOURCE` under
        :data:`attributes.REVENIUM_MIDDLEWARE_SOURCE` when ``snapshot`` supplied
        none — and empty, with no default in it, when ``snapshot`` is empty.
        Mutable and freshly built on purpose: the caller iterates it once and
        drops it, and handing back a proxy would allocate a second object to
        protect a value nobody retains.

    Raises:
        KeyError: When ``snapshot`` carries a name that is not one of
            :func:`attribution`'s parameters. The lookup is deliberately
            unguarded. A ``name in PARAMETER_TO_ATTRIBUTE_KEY`` filter here would
            convert an SDK-internal drift — a 22nd parameter added to
            ``attribution()`` without its constant — into exactly the silent
            attribution drop this whole module is built to prevent, and it would
            do so on the one path where nobody is watching. It cannot fire from
            caller input: ``attribution()`` is the only writer, its parameter
            names are keyword-only, and
            ``test_attribution_parameter_names_derive_from_the_constants`` goes
            red before this could.

    **Values are carried in their declared types, and the absence of a
    conversion here is the decision rather than an omission.** Nineteen of the
    twenty-one keys are ``str``; ``retry_number`` is ``int`` and
    ``request_stream`` is ``bool``. All three are natively typed OpenTelemetry
    attribute values, so this function hands them to ``span.set_attribute``
    unchanged. Stamping ``retry_number`` as ``"1"`` would repeat, on the
    attribution half of the SDK, the exact defect ``mlflow.tracing.configure``
    was rejected for — values arriving in a shape the backend drops or
    mis-stores — and Phase 2 already settled the same question for token counts
    (SEM-04). Neither key appears in :data:`attributes.ATTRIBUTE_CAPS`, which is
    what the backend not treating them as string columns looks like from here.

    **This function is also the seam any future per-value work belongs in.**
    ATTR-09's cap validation (plan 03-04) runs between the snapshot and the
    write, which is exactly this expression, and it needs the parameter names the
    snapshot is keyed by in order to name the offending argument back at the
    caller. Adding an encoding or coercion step anywhere downstream — in the
    processor's write loop, say — would put it after the point where the
    parameter name is gone.

    **The ``middleware.source`` default fills a missing key inside an active
    scope; it does not create a scope (ATTR-08, T-03-06).** An empty snapshot
    resolves to an empty mapping and gets no default at all. The boundary is
    drawn here rather than relied on from ``on_start``'s empty-snapshot early
    return, because that early return exists for a different reason — it is the
    hot-path guard for a process that never calls :func:`attribution` — and a
    resolver that defaulted unconditionally would be correct only for as long as
    ``on_start`` remained its only caller. It is already not going to be: 03-04's
    cap validation reads this same function. A bare
    ``revenium.middleware.source`` on an otherwise unattributed span would assert
    Revenium provenance for traffic nobody attributed, and since this runs for
    every span in the host process that would mark the customer's whole trace
    store as Revenium-sourced.

    ``setdefault`` rather than a pre-merge, so an explicit ``middleware_source``
    the caller passed always wins. A default that overrode the caller would make
    every record emitted through a wrapping integration claim to have come from
    this SDK.
    """
    if not snapshot:
        return {}
    resolved = {PARAMETER_TO_ATTRIBUTE_KEY[name]: value for name, value in snapshot.items()}
    resolved.setdefault(_REVENIUM_MIDDLEWARE_SOURCE, DEFAULT_MIDDLEWARE_SOURCE)
    return resolved
