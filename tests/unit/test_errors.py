"""The public exception hierarchy (D-02, PKG-05).

D-02 puts the exception types on the published surface for a concrete reason:
the package ships ``py.typed``, so a user's own checker consumes these names,
and an application that wants to treat "the telemetry side-car had a problem"
as one case needs a single root to catch. These tests pin three claims:

1. There is exactly one root and every other type descends from it, so one
   ``except`` clause is genuinely sufficient.
2. The declared surface (``__all__``) and the actual surface agree. A module
   whose two surfaces disagree is a module whose boundary claims have to be
   taken on trust, and this package's whole argument is that they should not.
3. Each type carries a docstring naming the phase whose behaviour raises it.
   Four of the six raise nothing yet; without that note a reader deletes them
   as dead code.

The membership assertion carries the six names as a literal set rather than
importing ``__all__`` and comparing it to itself. A test that reads the module
to decide what the module should contain agrees with every future edit.
"""

import inspect

import pytest

from revenium_mlflow import errors

pytestmark = pytest.mark.unit

#: The published exception surface, written out rather than derived. Removing a
#: name from here is a breaking change for importers (D-02 rates this costly);
#: adding one is cheap. Either way it should be a visible diff on this literal.
_EXPECTED_EXCEPTION_NAMES = frozenset(
    {
        "ReveniumMLflowError",
        "ConfigurationError",
        "CredentialScopeError",
        "ExportError",
        "OrderingError",
        "UnsupportedMLflowError",
    }
)


def _public_exception_classes() -> dict[str, type[BaseException]]:
    """Every public exception class actually defined in the module."""
    return {
        name: obj
        for name, obj in vars(errors).items()
        if not name.startswith("_") and inspect.isclass(obj) and issubclass(obj, BaseException)
    }


def test_all_lists_exactly_the_six_public_exception_types() -> None:
    """The declared surface is the six names D-02 contracted, no more, no less."""
    assert set(errors.__all__) == _EXPECTED_EXCEPTION_NAMES
    assert len(errors.__all__) == 6
    assert len(set(errors.__all__)) == 6


def test_declared_surface_matches_the_defined_surface() -> None:
    """Nothing public is defined that ``__all__`` forgets to mention."""
    assert set(_public_exception_classes()) == _EXPECTED_EXCEPTION_NAMES


def test_every_name_in_all_resolves_to_an_exception_class() -> None:
    """``__all__`` names classes, not strings that happen to look like classes."""
    for name in errors.__all__:
        obj = getattr(errors, name)
        assert inspect.isclass(obj), f"{name} is not a class"
        assert issubclass(obj, BaseException), f"{name} is not an exception"


def test_the_root_descends_from_exception() -> None:
    """The root is a plain ``Exception``, so ``except Exception`` still works.

    Not ``BaseException`` directly: a telemetry side-car must never be able to
    swallow ``KeyboardInterrupt`` or ``SystemExit`` handling by sitting outside
    the ordinary exception tree.
    """
    assert issubclass(errors.ReveniumMLflowError, Exception)
    assert errors.ReveniumMLflowError is not Exception


def test_every_exception_descends_from_the_single_root() -> None:
    """One ``except ReveniumMLflowError`` catches the whole family."""
    for name in errors.__all__:
        if name == "ReveniumMLflowError":
            continue
        assert issubclass(getattr(errors, name), errors.ReveniumMLflowError), (
            f"{name} does not descend from ReveniumMLflowError"
        )


def test_catching_the_root_catches_each_subclass_when_raised() -> None:
    """The subclass relationship holds at raise time, not only at import time."""
    for name in errors.__all__:
        if name == "ReveniumMLflowError":
            continue
        exception_type = getattr(errors, name)
        with pytest.raises(errors.ReveniumMLflowError):
            raise exception_type(f"synthetic {name} for the hierarchy test")


def test_each_exception_carries_a_docstring() -> None:
    """Four of the six raise nothing yet; the docstring is why they survive review."""
    for name in errors.__all__:
        docstring = getattr(errors, name).__doc__
        assert docstring is not None and docstring.strip(), f"{name} has no docstring"


def test_the_placeholder_types_name_the_phase_that_will_raise_them() -> None:
    """A contract placeholder has to say it is one, in its own docstring."""
    for name in ("ConfigurationError", "CredentialScopeError", "ExportError", "OrderingError"):
        docstring = getattr(errors, name).__doc__ or ""
        assert "Phase" in docstring, f"{name} does not name the phase that raises it"
