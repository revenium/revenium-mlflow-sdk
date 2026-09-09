"""The fake Revenium OTLP collector: a real socket, and the only place a billing claim is asserted.

**Why a real HTTP server and not a mock (VER-03).** This repository has been
bitten twice by an assertion that passed while the wire was wrong — attribution
written in ``on_end`` and discarded, and MLflow's own translator dropping
``cache_read_input_tokens``. Both survived a green suite because the green suite
asserted on objects the code under test handed it, rather than on the bytes that
left the process. Every billing-relevant assertion in Phase 4 therefore reads the
decoded ``ExportTraceServiceRequest`` this module captured off a socket, and this
module is the one place that decode happens.

**Why stdlib ``http.server`` and not ``respx``.** The OTLP HTTP exporter
transports over ``requests``, not ``httpx``. ``respx`` patches httpx transports
and would intercept nothing here: the export would never happen, the captured
list would stay empty, and every assertion written as a comprehension over it
would pass vacuously. That is the same failure shape in new clothing, which is
why :meth:`FakeOTLPCollector.assert_received_export` exists and why callers are
expected to reach for it before asserting anything about content.

**Two mechanics that are load-bearing and look like boilerplate.**

1. The response sends an explicit ``Content-Length: 0``. Without it the exporter
   waits out its full read timeout on every export and then reports failure, so
   a suite that omitted the header would be slow *and* wrong, with no error
   naming the cause.
2. The server binds ``("127.0.0.1", 0)`` — loopback, ephemeral port. Never a
   routable address. :meth:`FakeOTLPCollector.hosts` exposes what each request
   was addressed to so a test can assert the negative (T-04-02): a fixture
   edited to point somewhere real fails rather than exfiltrates.

Nothing here imports MLflow, at module scope or anywhere else, for the reason
``tests/fixtures/spans.py`` records: an import during collection would beat
``tests/conftest.py``'s telemetry-silencing fixture. The protobuf types come from
``opentelemetry-exporter-otlp-proto-http``, already a declared runtime
dependency — this module adds no distribution to ``pyproject.toml``.
"""

import dataclasses as _dataclasses
import gzip as _gzip
import http.server as _http_server
import threading as _threading
import types as _types
from collections.abc import Iterator as _Iterator
from collections.abc import Mapping as _Mapping
from collections.abc import Sequence as _Sequence
from typing import Final as _Final

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest as _ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue as _AnyValue
from opentelemetry.proto.common.v1.common_pb2 import KeyValue as _KeyValue

__all__ = [
    "CapturedRequest",
    "ExportedSpan",
    "FakeOTLPCollector",
    "unwrap_any_value",
    "unwrap_attributes",
]

#: The OTLP HTTP traces path. Composed into :attr:`FakeOTLPCollector.endpoint`
#: rather than accepted from a caller, because a collector listening on a
#: different path than the exporter posts to would present as "zero requests
#: captured" with no other symptom.
_TRACES_PATH: _Final[str] = "/v1/traces"

#: What the exporter sends. Asserted by callers rather than enforced here — the
#: collector records what arrived, and a test decides whether it was right.
_PROTOBUF_CONTENT_TYPE: _Final[str] = "application/x-protobuf"

#: The loopback interface, spelled once. Not ``localhost``: name resolution can
#: be redirected, and the point of this constant is that it cannot be.
_LOOPBACK_HOST: _Final[str] = "127.0.0.1"


@_dataclasses.dataclass(frozen=True, slots=True)
class CapturedRequest:
    """One POST, exactly as it arrived, before anything interprets it."""

    #: The request path, e.g. ``/v1/traces``.
    path: str

    #: Every header, lowercased. Lowercased on capture because HTTP header names
    #: are case-insensitive on the wire and an assertion about ``x-api-key``
    #: should not depend on how the client happened to spell it.
    headers: _Mapping[str, str]

    #: The body after any ``Content-Encoding`` was undone. Raw protobuf bytes.
    body: bytes

    #: The ``Host`` header the client addressed. The subject of T-04-02.
    host: str

    def decode(self) -> _ExportTraceServiceRequest:
        """Parse :attr:`body` as an ``ExportTraceServiceRequest``.

        Raises:
            google.protobuf.message.DecodeError: The body is not a valid
                request. Deliberately not caught: a body that will not decode is
                a finding, not a reason to return an empty request that every
                downstream comprehension would pass over.
        """
        request = _ExportTraceServiceRequest()
        request.ParseFromString(self.body)
        return request


@_dataclasses.dataclass(frozen=True, slots=True)
class ExportedSpan:
    """One span read out of a decoded payload, with its resource and scope.

    A flat view over the three nesting levels of the OTLP message, assembled so
    an assertion can say "this span carried this resource attribute" without
    re-walking ``resource_spans -> scope_spans -> spans`` at every call site.
    Every field is derived from the decoded protobuf and from nothing else.
    """

    #: The span name.
    name: str

    #: The OTLP ``SpanKind`` enum value. ``3`` is ``SPAN_KIND_CLIENT`` (SEM-12);
    #: ``1`` is ``SPAN_KIND_INTERNAL``, which is what a raw MLflow span carries.
    kind: int

    #: 32 lowercase hex characters.
    trace_id: str

    #: 16 lowercase hex characters.
    span_id: str

    #: 16 lowercase hex characters, or ``None`` for a root span.
    parent_span_id: str | None

    #: Integer nanoseconds.
    start_time_ns: int

    #: Integer nanoseconds.
    end_time_ns: int

    #: Span attributes, unwrapped to native Python.
    attributes: _Mapping[str, object]

    #: Which ``AnyValue`` oneof each span attribute arrived in — ``int_value``,
    #: ``string_value``, and so on. Kept alongside :attr:`attributes` because
    #: "the token count is an integer on the wire" is a claim about the encoding
    #: and cannot be made from the unwrapped value alone: a ``bool_value``
    #: unwraps to a Python ``bool``, which ``isinstance(x, int)`` accepts.
    attribute_kinds: _Mapping[str, str]

    #: Resource attributes, unwrapped to native Python.
    resource_attributes: _Mapping[str, object]

    #: The instrumentation scope name. ``mlflow.tracing.provider`` for a span
    #: MLflow produced — the provenance path that survives overriding
    #: ``telemetry.sdk.name`` in the resource.
    scope_name: str


def unwrap_any_value(value: _AnyValue) -> object:
    """One OTLP ``AnyValue`` as native Python, recursively.

    Args:
        value: The wrapper the OTLP encoder produced.

    Returns:
        ``None`` for an unset value, a ``list`` for an array, a ``dict`` for a
        kvlist, and the scalar otherwise. The recursion matters for
        ``gen_ai.response.finish_reasons``, which is emitted as a tuple of
        strings and arrives as an ``array_value``.
    """
    which = value.WhichOneof("value")
    if which is None:
        return None
    if which == "array_value":
        return [unwrap_any_value(item) for item in value.array_value.values]
    if which == "kvlist_value":
        return {entry.key: unwrap_any_value(entry.value) for entry in value.kvlist_value.values}
    unwrapped: object = getattr(value, which)
    return unwrapped


def unwrap_attributes(attributes: _Sequence[_KeyValue]) -> dict[str, object]:
    """An OTLP ``KeyValue`` list as a plain dict of native Python values."""
    return {entry.key: unwrap_any_value(entry.value) for entry in attributes}


def _attribute_kinds(attributes: _Sequence[_KeyValue]) -> dict[str, str]:
    """Which ``AnyValue`` oneof each attribute arrived in.

    See :attr:`ExportedSpan.attribute_kinds` for why the oneof name is kept
    alongside the unwrapped value.
    """
    return {entry.key: (entry.value.WhichOneof("value") or "unset") for entry in attributes}


def _exported_spans(request: _ExportTraceServiceRequest) -> list[ExportedSpan]:
    """Flatten one decoded request into :class:`ExportedSpan` records."""
    flattened: list[ExportedSpan] = []
    for resource_spans in request.resource_spans:
        resource_attributes = unwrap_attributes(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                flattened.append(
                    ExportedSpan(
                        name=span.name,
                        kind=int(span.kind),
                        trace_id=span.trace_id.hex(),
                        span_id=span.span_id.hex(),
                        parent_span_id=span.parent_span_id.hex() or None,
                        start_time_ns=int(span.start_time_unix_nano),
                        end_time_ns=int(span.end_time_unix_nano),
                        attributes=unwrap_attributes(span.attributes),
                        attribute_kinds=_attribute_kinds(span.attributes),
                        resource_attributes=resource_attributes,
                        scope_name=scope_spans.scope.name,
                    )
                )
    return flattened


class _CollectorHandler(_http_server.BaseHTTPRequestHandler):
    """Records one POST and answers it, and does nothing else.

    ``protocol_version`` stays at HTTP/1.0 so each export gets its own
    connection and the handler never has to reason about keep-alive framing.
    """

    #: Set by :class:`_CollectorServer` before the thread starts.
    server: "_CollectorServer"

    def do_POST(self) -> None:
        """Capture the body, then answer 200 with an explicit empty payload.

        The camel-case name is what ``BaseHTTPRequestHandler`` dispatches to; it
        is a framework contract rather than a style choice.
        """
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
            body = _gzip.decompress(body)

        self.server.record(
            CapturedRequest(
                path=self.path,
                headers={name.lower(): value for name, value in self.headers.items()},
                body=body,
                host=(self.headers.get("Host") or "").split(":", 1)[0],
            )
        )

        self.send_response(200)
        self.send_header("Content-Type", _PROTOBUF_CONTENT_TYPE)
        # Explicit and non-negotiable. Omitting it leaves the exporter blocked on
        # its own read timeout for every single export, and the resulting
        # failure names a timeout rather than a missing header.
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Silence the per-request stderr line ``BaseHTTPRequestHandler`` writes by default."""


class _CollectorServer(_http_server.ThreadingHTTPServer):
    """An ``HTTPServer`` that owns the captured-request list and its lock."""

    daemon_threads = True

    def __init__(self) -> None:
        """Bind loopback on an ephemeral port. Never a routable address (T-04-02)."""
        super().__init__((_LOOPBACK_HOST, 0), _CollectorHandler)
        self._lock = _threading.Lock()
        self._captured: list[CapturedRequest] = []

    def record(self, request: CapturedRequest) -> None:
        """Append one captured request under the lock. Called on a handler thread."""
        with self._lock:
            self._captured.append(request)

    def captured(self) -> tuple[CapturedRequest, ...]:
        """A snapshot of everything captured so far, safe to read from the test thread."""
        with self._lock:
            return tuple(self._captured)

    def clear(self) -> None:
        """Drop every captured request."""
        with self._lock:
            self._captured.clear()


class FakeOTLPCollector:
    """A loopback OTLP endpoint that records what was POSTed to it.

    Use as a context manager::

        with FakeOTLPCollector() as collector:
            handle = configure_tracing(otlp_traces_endpoint=collector.endpoint, ...)
            ...
            handle.flush(5.0)
            request = collector.assert_received_export()

    **Do not shut the collector down before the flush that fills it completes.**
    ``shutdown()`` stops the serve loop while the listening socket stays open, so
    a late export presents to the client as a read timeout rather than as a
    refused connection — a symptom that reads like a slow collector and is
    actually a closed one.
    """

    def __init__(self) -> None:
        """Bind the socket immediately so :attr:`endpoint` is valid before ``__enter__``."""
        self._server = _CollectorServer()
        self._thread: _threading.Thread | None = None

    @property
    def port(self) -> int:
        """The ephemeral port the kernel assigned."""
        port: int = self._server.server_address[1]
        return port

    @property
    def endpoint(self) -> str:
        """The full OTLP traces URL to hand an exporter."""
        return f"http://{_LOOPBACK_HOST}:{self.port}{_TRACES_PATH}"

    def __enter__(self) -> "FakeOTLPCollector":
        """Start serving on a daemon thread and hand back ``self``."""
        self._thread = _threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: _types.TracebackType | None,
    ) -> None:
        """Stop the serve loop and close the socket."""
        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()

    @property
    def requests(self) -> tuple[CapturedRequest, ...]:
        """Every request captured so far, oldest first."""
        return self._server.captured()

    @property
    def hosts(self) -> tuple[str, ...]:
        """The host each captured request was addressed to. The subject of T-04-02."""
        return tuple(request.host for request in self.requests)

    def reset(self) -> None:
        """Forget every captured request, keeping the socket and the port."""
        self._server.clear()

    def decoded(self) -> tuple[_ExportTraceServiceRequest, ...]:
        """Every captured request, parsed. The only sanctioned source of a billing assertion."""
        return tuple(request.decode() for request in self.requests)

    def exported_spans(self) -> list[ExportedSpan]:
        """Every span in every decoded request, flattened with its resource and scope."""
        return [span for request in self.decoded() for span in _exported_spans(request)]

    def assert_received_export(self) -> _ExportTraceServiceRequest:
        """The falsifiability affordance: fail here when nothing was exported.

        Returns:
            The single decoded request, when there is exactly one.

        Raises:
            AssertionError: No request arrived, more than one did, the content
                type was wrong, or the payload carried no spans.

        Every other assertion in this phase is a statement about the *content* of
        an export, and a comprehension over an empty list satisfies all of them
        at once. This is the assertion that has to be made first, so a pipeline
        that silently stopped exporting fails on the export rather than passing
        on its absence. Plan 04-01 Task 3 proves it can fail, by removing the
        exporter's delegate call and capturing the red.
        """
        captured = self.requests
        assert captured, (
            f"the collector at {self.endpoint} received no request at all. "
            "Nothing below this line is a claim about an export — assertions over "
            "an empty payload pass vacuously. Check that flush() was called and "
            "that the exporter was pointed at this endpoint."
        )
        assert len(captured) == 1, (
            f"expected exactly one export, captured {len(captured)}: "
            f"{[request.path for request in captured]}"
        )
        request = captured[0]
        content_type = request.headers.get("content-type")
        assert content_type == _PROTOBUF_CONTENT_TYPE, (
            f"expected Content-Type {_PROTOBUF_CONTENT_TYPE!r}, got {content_type!r} — "
            "the exporter is not speaking http/protobuf (CFG-09)."
        )
        decoded = request.decode()
        assert decoded.resource_spans, (
            "the request decoded but carried no resource_spans. An export of zero spans "
            "is not evidence that the pipeline works."
        )
        return decoded

    def iter_captured(self) -> _Iterator[CapturedRequest]:
        """Iterate the captured requests. Provided so a caller need not copy the tuple."""
        return iter(self.requests)
