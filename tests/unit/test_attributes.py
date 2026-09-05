"""The 21 ``revenium.*`` attribute-key constants and their backend caps (ATTR-07, D-02).

The backend silently **drops** unrecognized and oversized attribute values —
``ReveniumAttributes.kt``, recorded in PROJECT.md — so a hand-typed key vanishes
with no error on either side and the customer's attribution is quietly wrong.
Exported constants convert that class of silent billing loss into an author-time
``AttributeError`` or a mypy complaint. These tests exist to keep the constants
honest against three specific drifts:

*Key drift.* The expected key set below is a **literal**, deliberately not
imported from the module under test. If the module renames or drops a key, the
comparison fails rather than agreeing with itself (threat T-01-21).

*Name drift.* Every constant name must derive from its key by one mechanical
rule, because plan 01-05 turns the same 21 names into the 21 explicit keyword
parameters of ``attribution()`` (D-03). A constant named by hand is a parameter
named by hand.

*Cap drift.* The eight per-column caps are pinned to the values verified against
the backend source. They are transcribed, not runtime-verified — this project
forbids calling the hosted route — so the literal here is the record of what was
read (threat T-01-25).
"""

import types

import pytest

from revenium_mlflow import attributes

pytestmark = pytest.mark.unit

#: The authoritative ATTR-07 list, spelled out. This is the assertion's whole
#: value: it is an independent copy of the contract, not a view of the module.
_ATTR_07_KEYS = frozenset(
    {
        "revenium.organization.name",
        "revenium.product.name",
        "revenium.subscription.id",
        "revenium.subscriber.id",
        "revenium.subscriber.email",
        "revenium.agent.name",
        "revenium.task.type",
        "revenium.trace.type",
        "revenium.trace.name",
        "revenium.transaction.name",
        "revenium.job.id",
        "revenium.job.name",
        "revenium.job.type",
        "revenium.job.version",
        "revenium.squad.id",
        "revenium.squad.name",
        "revenium.squad.role",
        "revenium.operation.subtype",
        "revenium.retry.number",
        "revenium.request.stream",
        "revenium.middleware.source",
    }
)

#: The per-column caps ``ReveniumAttributes.kt`` enforces, transcribed from the
#: source read recorded in PROJECT.md. Oversized values are dropped, not
#: truncated, which is why client-side validation (ATTR-09, Phase 3) is worth
#: having at all.
_EXPECTED_CAPS = {
    "revenium.trace.name": 256,
    "revenium.trace.type": 128,
    "revenium.task.type": 255,
    "revenium.job.id": 256,
    "revenium.job.name": 512,
    "revenium.job.type": 128,
    "revenium.job.version": 64,
    "revenium.middleware.source": 255,
}

#: The additional pass-through attributes the backend also recognizes — the six
#: PROJECT.md entries, with ``subscriber.credential.{name,value}`` expanded to
#: the two keys it actually denotes. They are V2-03, deliberately out of scope:
#: D-03 makes each one a new keyword parameter on ``attribution()``, so shipping
#: them early would enlarge a signature nothing in this milestone can populate.
_V2_03_PASS_THROUGH_KEYS = frozenset(
    {
        "revenium.ticket.id",
        "revenium.model.host",
        "revenium.subscriber.email.source",
        "revenium.system.fingerprint",
        "revenium.subscription_tier",
        "revenium.subscriber.credential.name",
        "revenium.subscriber.credential.value",
    }
)

_KEY_PREFIX = "revenium."


def _expected_constant_name(key: str) -> str:
    """Apply the mechanical mapping: uppercase the suffix, dots become underscores."""
    return "REVENIUM_" + key[len(_KEY_PREFIX) :].upper().replace(".", "_")


def _string_constants() -> dict[str, str]:
    """Every public module-level ``str`` constant, which is every attribute key."""
    return {
        name: value
        for name, value in vars(attributes).items()
        if not name.startswith("_") and isinstance(value, str)
    }


def test_there_are_exactly_twenty_one_unique_keys() -> None:
    """21, not 27: the V2-03 pass-through attributes are a later signature change."""
    assert len(attributes.REVENIUM_ATTRIBUTE_KEYS) == 21
    assert len(set(attributes.REVENIUM_ATTRIBUTE_KEYS)) == 21


def test_the_key_tuple_is_a_tuple() -> None:
    """A tuple, so a caller cannot append a key the backend would drop anyway."""
    assert isinstance(attributes.REVENIUM_ATTRIBUTE_KEYS, tuple)


def test_every_key_is_revenium_prefixed_with_a_non_empty_suffix() -> None:
    """``revenium.`` alone is not an attribute; the suffix is what names the column."""
    for key in attributes.REVENIUM_ATTRIBUTE_KEYS:
        assert key.startswith(_KEY_PREFIX), f"{key!r} is not revenium-prefixed"
        assert len(key) > len(_KEY_PREFIX), f"{key!r} has an empty suffix"


def test_the_keys_are_exactly_the_attr_07_set() -> None:
    """The independent copy of the contract, compared against the module (T-01-21)."""
    assert set(attributes.REVENIUM_ATTRIBUTE_KEYS) == _ATTR_07_KEYS


def test_every_key_has_a_constant_named_by_the_mechanical_rule() -> None:
    """Key to name, in the direction plan 01-05's parameter names are derived."""
    for key in attributes.REVENIUM_ATTRIBUTE_KEYS:
        name = _expected_constant_name(key)
        assert hasattr(attributes, name), f"{key!r} has no constant named {name}"
        assert getattr(attributes, name) == key


def test_every_string_constant_maps_back_to_its_own_key() -> None:
    """Name to key, so no constant exists that the tuple does not carry."""
    constants = _string_constants()
    assert len(constants) == 21
    for name, key in constants.items():
        assert key in _ATTR_07_KEYS, f"{name} holds {key!r}, which is not an ATTR-07 key"
        assert name == _expected_constant_name(key), f"{name} does not follow the naming rule"


def test_the_v2_03_pass_through_attributes_are_absent() -> None:
    """The recognized-but-deferred keys must not have leaked into this milestone."""
    assert not (_V2_03_PASS_THROUGH_KEYS & set(attributes.REVENIUM_ATTRIBUTE_KEYS))
    for key in _V2_03_PASS_THROUGH_KEYS:
        assert not hasattr(attributes, _expected_constant_name(key))


def test_the_caps_match_the_verified_backend_table() -> None:
    """Eight columns, pinned to the values read from the backend source."""
    assert dict(attributes.ATTRIBUTE_CAPS) == _EXPECTED_CAPS
    assert len(attributes.ATTRIBUTE_CAPS) == 8


def test_every_capped_key_is_a_real_attribute_key() -> None:
    """A cap on a key the SDK never emits would be a cap nothing consults."""
    assert set(attributes.ATTRIBUTE_CAPS).issubset(set(attributes.REVENIUM_ATTRIBUTE_KEYS))


def test_every_cap_is_a_positive_integer() -> None:
    """A zero or negative cap would reject every value the column can hold."""
    for key, cap in attributes.ATTRIBUTE_CAPS.items():
        assert isinstance(cap, int), f"cap for {key!r} is {type(cap).__name__}, not int"
        assert not isinstance(cap, bool), f"cap for {key!r} is a bool"
        assert cap > 0, f"cap for {key!r} is not positive"


def test_the_cap_mapping_rejects_item_assignment() -> None:
    """Exported as a read-only view: a caller must not be able to widen a cap."""
    assert isinstance(attributes.ATTRIBUTE_CAPS, types.MappingProxyType)
    with pytest.raises(TypeError):
        attributes.ATTRIBUTE_CAPS["revenium.trace.name"] = 1_000_000  # type: ignore[index]


def test_the_module_declares_its_surface() -> None:
    """``__all__`` carries the aggregate names alongside the 21 constants."""
    assert "REVENIUM_ATTRIBUTE_KEYS" in attributes.__all__
    assert "ATTRIBUTE_CAPS" in attributes.__all__
    assert len(attributes.__all__) == len(set(attributes.__all__))
    for name in attributes.__all__:
        assert hasattr(attributes, name), f"__all__ names {name}, which does not exist"
