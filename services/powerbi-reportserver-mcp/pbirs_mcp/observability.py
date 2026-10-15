"""Trace context and the platform log contract.

**Vendored file — keep it identical everywhere it appears.** It started in the
fourteen MCP servers and now also serves ``workflow-execution-engine`` and
``pii-masking-service``: separate git repositories with no shared package
between them, so the choice was one copied file or a bespoke implementation per
repository; a copy at least makes drift visible as a diff. Only the wiring at
the edges is per-repo. The copy in ``stair-gitlab-mcp/src/observability.py`` is
the canonical one: change it there, then copy outward, and ``md5sum`` across the
repositories is how drift is found.

The two newer callers are not MCP servers and meet this file differently: both
are FastAPI applications, so the middleware is installed with
``app.add_middleware`` rather than by wrapping an ASGI app by hand, and
``workflow-execution-engine`` binds its context a second time inside the
background task that actually runs the workflow — its HTTP request has returned
``202`` long before the work starts.

What a request meets, in order:

* :class:`TraceContextMiddleware` reads ``traceparent`` and ``X-Session-Id`` off
  the inbound request, binds them for the duration of that request, and echoes
  them back on the response (§4 steps 1, 2 and 5 of the platform contract).
* :class:`ContractFormatter` renders every log record as one JSON line under the
  §4 field names, so the ``trace_id`` a support engineer copies out of a span in
  Grafana finds these lines through the same ``tracesToLogsV2`` jump that works
  on the engine and the router.

Why this exists at all: the engine already injects the W3C context into every
MCP call, and it already emits an ``execute_tool`` span per call — so the *trace*
was never broken. What was missing is the other half of the join. A tool that
answers in 30 seconds or fails left a span saying "30 seconds, error" and server
logs that could not be proven to belong to that call.

Two names that look like details and are not:

* ``session.id``, not ``session_id`` — a differently spelled key is a *different
  field* in VictoriaLogs, and the headline query of the whole design
  (``session.id:"…"``) is written with the dot.
* ``service.name`` — Fluent Bit fills it from the container name for any pod
  that does not log one itself, and it is a VictoriaLogs ``_stream`` key.
  Streams already written do not un-split, so a service that starts emitting its
  own name splits its history at that moment. That is the intended one-off cost.

Field names come from
``ai-agent-execution-engine/docs/observability/traceability-design-victoria.md``
§4. Standard library only, by design: these repositories share no dependency
set, and a logging contract that needs a package to be installed first is a
logging contract that will be skipped somewhere.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import secrets
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol

TRACEPARENT_HEADER = "traceparent"
SESSION_ID_HEADER = "x-session-id"
REQUEST_ID_HEADER = "x-request-id"

logger = logging.getLogger("mcp.observability")

_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-"
    r"(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-"
    r"(?P<trace_flags>[0-9a-f]{2})(?:-.+)?$"
)
_ZERO_TRACE_ID = "0" * 32
_ZERO_SPAN_ID = "0" * 16
DEFAULT_TRACE_FLAGS = "01"


# -----------------------------------------------------------------------------
# The request's trace context
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestTrace:
    """The W3C trace context this request runs under."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    trace_flags: str = DEFAULT_TRACE_FLAGS

    @property
    def traceparent(self) -> str:
        """The header naming *our* span as the parent, for outbound calls."""
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    @property
    def inbound_traceparent(self) -> str | None:
        """The caller's header, rebuilt from its parsed parts.

        What a server with no span of its own should forward: our ``span_id`` is
        then an id no span will ever carry, and handing it downstream makes the
        callee's span point at a parent that does not exist. ``None`` when
        nothing came in.
        """
        if not self.parent_span_id:
            return None
        return f"00-{self.trace_id}-{self.parent_span_id}-{self.trace_flags}"


@dataclass(frozen=True)
class _ParsedTraceparent:
    trace_id: str
    parent_span_id: str
    trace_flags: str


def parse_traceparent(value: str | None) -> _ParsedTraceparent | None:
    """Parse a W3C ``traceparent``, returning None when absent or malformed."""
    if not value:
        return None
    match = _TRACEPARENT_RE.match(value.strip().lower())
    if not match:
        return None

    trace_id = match.group("trace_id")
    parent_span_id = match.group("span_id")
    if trace_id == _ZERO_TRACE_ID or parent_span_id == _ZERO_SPAN_ID:
        return None
    if match.group("version") == "ff":
        return None

    return _ParsedTraceparent(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        trace_flags=match.group("trace_flags"),
    )


def resolve_request_trace(headers: Mapping[str, str]) -> RequestTrace:
    """Continue the caller's trace, or start one when nothing came in.

    An MCP server is always called by the engine, which always injects the
    context — so in production this continues. The originate branch is what
    keeps a direct ``curl`` during an incident from producing log lines with no
    ids at all.
    """
    parsed = parse_traceparent(headers.get(TRACEPARENT_HEADER))
    if parsed is not None:
        return RequestTrace(
            trace_id=parsed.trace_id,
            span_id=secrets.token_hex(8),
            parent_span_id=parsed.parent_span_id,
            trace_flags=parsed.trace_flags,
        )
    return RequestTrace(trace_id=secrets.token_hex(16), span_id=secrets.token_hex(8))


def session_id_from_headers(headers: Mapping[str, str]) -> str | None:
    """The session id the engine supplied, if any."""
    value = headers.get(SESSION_ID_HEADER)
    return value.strip() if value and value.strip() else None


@dataclass(frozen=True)
class RequestContext:
    """Everything the logger stamps on a line, resolved once per request."""

    trace: RequestTrace
    request_id: str
    session_id: str | None = None

    def log_fields(self) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "trace_id": self.trace.trace_id,
            "span_id": self.trace.span_id,
            # OTel carries the parent on the *span*; a flat log line has no
            # standard name for it, hence the platform namespace.
            "http.request.id": self.request_id,
        }
        if self.trace.parent_span_id:
            fields["stair.parent.span_id"] = self.trace.parent_span_id
        if self.session_id:
            fields["session.id"] = self.session_id
        return fields


_request_context_var: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "mcp_request_context", default=None
)


@contextmanager
def request_context(context: RequestContext) -> Iterator[None]:
    """Bind the request's ids for its duration."""
    token = _request_context_var.set(context)
    try:
        yield
    finally:
        _request_context_var.reset(token)


def current_request_context() -> RequestContext | None:
    return _request_context_var.get()


def current_traceparent() -> str | None:
    """The ``traceparent`` for an outbound call, or None outside a request.

    A server that owns no span of its own forwards the *caller's* traceparent —
    see :attr:`RequestTrace.inbound_traceparent`. One that does own a span
    overwrites the context (see ``otel_tracing.traceparent_for``), so this
    returns our own id only where a span with that id exists.
    """
    context = _request_context_var.get()
    if context is None:
        return None
    return context.trace.inbound_traceparent or context.trace.traceparent


def current_session_id() -> str | None:
    context = _request_context_var.get()
    return context.session_id if context else None


# -----------------------------------------------------------------------------
# The log line
# -----------------------------------------------------------------------------

# Attributes the logging module puts on every record. Anything outside this set
# arrived through ``extra={...}`` and is worth keeping on the line.
_STD_LOGRECORD_ATTRS = frozenset(
    {
        "args", "asctime", "color_message", "created", "exc_info", "exc_text",
        "filename", "funcName", "levelname", "levelno", "lineno", "message",
        "module", "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

# Spellings that predate the contract, mapped rather than chased through every
# call site: the same meaning under two names is two fields in VictoriaLogs.
_RENAMED_EXTRAS = {
    "session_id": "session.id",
    "trace.id": "trace_id",
    "span.id": "span_id",
}


def static_log_fields(
    service_name: str,
    *,
    service_version: str | None = None,
    environment: str | None = None,
) -> dict[str, Any]:
    """Process-level fields that belong on every line.

    ``environment`` falls back to ``SERVICE_ENVIRONMENT``, the name the platform
    values files already use. The ``k8s.*`` fields are added by the collector's
    Kubernetes filter and are deliberately not duplicated here.
    """
    fields: dict[str, Any] = {"service.name": service_name}
    if service_version:
        fields["service.version"] = service_version
    environment = environment or os.getenv("SERVICE_ENVIRONMENT")
    if environment:
        fields["deployment.environment.name"] = environment
    hostname = os.getenv("HOSTNAME")
    if hostname:
        fields["host.name"] = hostname
    return fields


class ContractFormatter(logging.Formatter):
    """One JSON object per record, under the §4 field names.

    The request's ids are read from the contextvar at format time rather than
    bound onto the record, so a log call anywhere in the process — including
    library code that knows nothing about this module — carries them.
    """

    def __init__(self, static_fields: Mapping[str, Any] | None = None) -> None:
        super().__init__()
        self._static_fields = dict(static_fields or {})

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            # ISO 8601 with a timezone. A timestamp the collector cannot parse
            # makes it fall back to its own clock, and events land minutes from
            # where they happened.
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "severity_text": record.levelname,
            "body": record.getMessage(),
            "stair.logger": record.name,
        }
        payload.update(self._static_fields)

        context = _request_context_var.get()
        if context is not None:
            payload.update(context.log_fields())

        for key, value in record.__dict__.items():
            if key in _STD_LOGRECORD_ATTRS or key.startswith("_") or value is None:
                continue
            payload.setdefault(_RENAMED_EXTRAS.get(key, key), value)

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if exc_type is not None:
                payload["exception.type"] = exc_type.__name__
            if exc_value is not None:
                payload["exception.message"] = str(exc_value)
            # The stack trace goes *inside* the JSON line: a bare multi-line
            # traceback becomes N records in the collector, and only the first
            # would carry the trace context.
            payload["exception.stacktrace"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stair.stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)


def contract_formatter(
    service_name: str = "mcp-server",
    *,
    service_version: str | None = None,
    environment: str | None = None,
) -> ContractFormatter:
    """Factory for the ``()`` key of a ``logging.config.dictConfig`` formatter.

    For the servers that configure logging from a YAML file: the contract
    replaces the format *string* there, and nothing else about their setup has
    to move into code.
    """
    return ContractFormatter(
        static_log_fields(service_name, service_version=service_version, environment=environment)
    )


def configure_contract_logging(
    service_name: str,
    *,
    level: str = "INFO",
    service_version: str | None = None,
    environment: str | None = None,
    filters: tuple[logging.Filter, ...] = (),
    stream: Any = None,
) -> logging.Handler:
    """Install the contract formatter on the root logger. Idempotent.

    Returns the handler so a caller can keep a reference to it. Any pre-existing
    handler is dropped — uvicorn and the MCP SDK install their own, and two
    handlers mean every line twice.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(
        ContractFormatter(
            static_log_fields(
                service_name, service_version=service_version, environment=environment
            )
        )
    )
    for log_filter in filters:
        handler.addFilter(log_filter)
    root.addHandler(handler)

    # Access logs restate what the middleware already logs, once per request.
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    return handler


# -----------------------------------------------------------------------------
# The middleware
# -----------------------------------------------------------------------------


class SpanHooks(Protocol):
    """How the middleware talks to a tracer, for the servers that have one.

    Only the MCP servers that call outward on their own account own a SERVER
    span — elsewhere it would restate the engine's ``execute_tool`` span one for
    one. Those servers pass an implementation (``otel_tracing.OtelSpanHooks``);
    the rest pass nothing and this module stays dependency-free.
    """

    def start_request_span(self, name: str, trace: RequestTrace) -> Any | None: ...

    def span_ids(self, span: Any) -> tuple[str, str] | None: ...

    def end_request_span(
        self, span: Any, *, status_code: int | None = None, error: BaseException | None = None
    ) -> None: ...


class TraceContextMiddleware:
    """Bind the request's trace context, echo the ids, optionally own a span.

    Pure ASGI rather than Starlette's ``BaseHTTPMiddleware``: the MCP
    streamable-HTTP transport answers with a long-lived SSE stream, and
    ``BaseHTTPMiddleware`` pumps a response through an intermediate queue, which
    is the wrong shape for one. It also keeps this file importable in a repo
    that has no Starlette.

    Outermost by design — whatever runs before it logs without the ids, and the
    auth failure lines are the first thing anyone reads.
    """

    def __init__(
        self,
        app: Any,
        *,
        excluded_paths: frozenset[str] = frozenset({"/health", "/healthz", "/metrics"}),
        span_hooks: SpanHooks | None = None,
    ) -> None:
        self.app = app
        self.excluded_paths = excluded_paths
        self.span_hooks = span_hooks

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") in self.excluded_paths:
            # A probe every 30 seconds is a span nobody reads and a log line
            # nobody reads.
            await self.app(scope, receive, send)
            return

        headers = _headers_from_scope(scope)
        trace = resolve_request_trace(headers)
        request_id = (headers.get(REQUEST_ID_HEADER) or "").strip() or secrets.token_hex(8)
        session_id = session_id_from_headers(headers)

        span = None
        if self.span_hooks is not None:
            span = self.span_hooks.start_request_span(
                f"{scope.get('method', 'HTTP')} {scope.get('path', '')}", trace
            )
            ids = self.span_hooks.span_ids(span) if span is not None else None
            if ids is not None:
                # Once the span exists it, not the id resolver, owns the ids —
                # otherwise the line and the span disagree about span_id.
                trace = replace(trace, trace_id=ids[0], span_id=ids[1])

        context = RequestContext(trace=trace, request_id=request_id, session_id=session_id)
        echo = [
            (b"x-request-id", request_id.encode("latin-1")),
            (b"x-trace-id", trace.trace_id.encode("latin-1")),
            (b"traceparent", trace.traceparent.encode("latin-1")),
        ]
        if session_id:
            echo.append((b"x-session-id", session_id.encode("latin-1")))

        status_code: int | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status")
                message = dict(message)
                message["headers"] = list(message.get("headers") or []) + echo
            await send(message)

        method = scope.get("method", "")
        path = scope.get("path", "")
        started = time.monotonic()

        with request_context(context):
            # These two lines are the reason the join works at all: a server
            # whose tools happen to log nothing would otherwise have no line
            # carrying the trace_id, and the trace→logs jump would come back
            # empty even though everything is configured correctly. The pair
            # also bounds a hanging tool call from both ends.
            logger.info(
                "http.request_started",
                extra={"http.request.method": method, "url.path": path},
            )
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                logger.exception(
                    "http.request_failed",
                    extra={
                        "http.request.method": method,
                        "url.path": path,
                        "event.duration_ms": (time.monotonic() - started) * 1000,
                    },
                )
                if span is not None and self.span_hooks is not None:
                    self.span_hooks.end_request_span(span, error=exc)
                raise
            logger.info(
                "http.request_finished",
                extra={
                    "http.request.method": method,
                    "url.path": path,
                    "http.response.status_code": status_code,
                    "event.duration_ms": (time.monotonic() - started) * 1000,
                },
            )
            if span is not None and self.span_hooks is not None:
                self.span_hooks.end_request_span(span, status_code=status_code)


def _headers_from_scope(scope: Mapping[str, Any]) -> dict[str, str]:
    """Lower-cased header map from an ASGI scope. Last value wins, as in HTTP."""
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers") or []
    }
