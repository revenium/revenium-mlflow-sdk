"""Tool-execution metering: ``meter_tool_span`` as decorator and context manager.

Phase 5 (TOOL-01 through TOOL-07) implements this. Phase 1 fixes the signature
and the *shape* of the return value, because both are contract.

**Why it returns an object rather than being a generator-based context manager.**
The two supported call forms are ``with meter_tool_span(...):`` and
``@meter_tool_span(...)`` (TOOL-01), and a caller must get the same failure from
both. A ``@contextlib.contextmanager`` generator defers its body until
``__enter__``, so in Phase 1 the decorator form would accept the decoration
silently and only fail when the decorated function was eventually called —
possibly never, in a code path that is not exercised until production. Raising
from :func:`meter_tool_span` itself makes both forms fail at the same place, at
import time, in front of whoever wrote them.

**Why the idempotency key is a parameter.** TOOL-05 requires exactly one event
per logical tool execution. A retried HTTP POST, a wrapped retry decorator, and
a re-entered context manager all look like separate executions from inside this
SDK, and each duplicate is a billable event. Phase 5 derives a default key from
``(trace_id, span_id)``; the parameter exists for the case where the caller
knows the logical identity better than the span tree does.
"""

import contextlib
from collections.abc import Mapping
from types import TracebackType

__all__ = ["ToolSpanScope", "meter_tool_span"]

_PHASE_5 = (
    "not implemented until Phase 5 (Tool Metering and Job Outcomes). "
    "Phase 1 publishes this signature so callers and type checkers can be "
    "written against it; it raises rather than metering nothing quietly, "
    "because an unmetered tool execution is revenue that is never invoiced "
    "and leaves no trace of having gone missing."
)


class ToolSpanScope(contextlib.ContextDecorator, contextlib.AbstractContextManager[None]):
    """The scope returned by :func:`meter_tool_span`, usable both ways.

    Inheriting :class:`contextlib.ContextDecorator` is what makes
    ``@meter_tool_span(...)`` type-check as a decorator while
    ``with meter_tool_span(...):`` type-checks as a context manager, from one
    return annotation and without a union.

    Not re-exported from :mod:`revenium_mlflow` in Phase 1. It is named rather
    than private so a user can annotate against it if they need to, but D-02
    fixes what the published ``__all__`` carries, and adding a type there is
    cheap while removing one is not.
    """

    def __enter__(self) -> None:
        """Always raises in Phase 1."""
        raise NotImplementedError(f"ToolSpanScope is {_PHASE_5}")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Always raises in Phase 1.

        Returns ``None`` rather than ``bool`` by annotation, which is the way to
        say that this scope never suppresses an exception. A metering wrapper
        that swallowed the tool's own failure would convert a visible outage
        into a silently-unmetered success.
        """
        raise NotImplementedError(f"ToolSpanScope is {_PHASE_5}")


def meter_tool_span(
    *,
    tool_id: str,
    operation: str | None = None,
    cost: float | None = None,
    usage_metadata: Mapping[str, object] | None = None,
    idempotency_key: str | None = None,
) -> ToolSpanScope:
    """Meter one logical tool execution, measuring duration and success (TOOL-01).

    Usable as a context manager or as a decorator; both forms produce exactly
    one event per logical execution.

    Error information (TOOL-04) is observed rather than supplied: the scope sees
    the exception propagating through ``__exit__`` and records the failure from
    it. Passing it as a parameter would make the common case — a tool that
    raises — depend on the caller remembering to report what already happened in
    front of the SDK.

    Args:
        tool_id: The tool being executed. Required: an event that cannot say
            which tool it is cannot be rated.
        operation: The specific operation performed by that tool.
        cost: The caller-known cost of the execution, if any.
        usage_metadata: Free-form usage detail carried on the event.
        idempotency_key: Overrides the derived deduplication key. See the module
            docstring for when the caller knows better than the span tree.

    Returns:
        A :class:`ToolSpanScope`.

    Raises:
        NotImplementedError: Always, in Phase 1 — from this call, so the
            decorator and context-manager forms fail identically and early.
    """
    raise NotImplementedError(f"meter_tool_span() is {_PHASE_5}")
