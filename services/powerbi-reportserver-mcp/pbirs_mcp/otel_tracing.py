"""OpenTelemetry spans, for an MCP server that calls outward on its own account.

**Vendored file — keep it identical across the MCP repositories that have one.**
Only four do: ``sql-executor-mcp`` (the canonical copy), ``python-exec-secure``,
``rag-mcp`` and ``web-tools-mcp``. Everywhere else a SERVER span would restate the engine's
``execute_tool`` span one for one — same start, same end, same outcome — and the
right answer is no span at all. Here the engine's span says *30 seconds, error*
and cannot say whether that was the database, the network or us; the child span
around the outward call is the whole reason this file exists.

Deliberately mirrors the router's ``observability/otel.py``:

* **Off is a no-op, not an error.** With no endpoint configured every function
  here does nothing, so local runs and tests need no collector.
* **Telemetry never breaks a request.** Every function swallows its own
  failures — a broken exporter must not turn a working tool call into a 500.
* **Imports are function-local**, so a deployment that has not installed the
  OpenTelemetry packages still starts and simply runs untraced.

The span this server owns is the *parent* the engine's ``execute_tool`` span
sits above, so the forwarded trace context must name it — which is why
``TraceContextMiddleware`` takes the ids back from the span once it exists
rather than keeping the ones it minted.
"""

from __future__ import annotations

import contextvars
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("mcp.otel")

_INSTRUMENTATION_SCOPE = "mcp_server"

_tracer_provider: Any | None = None
_tracer: Any | None = None

# The request's SERVER span, so a tool handler deep in the call stack can hang a
# child off it without threading it through every signature.
_current_span_var: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "mcp_current_span", default=None
)


def _span_exporter(endpoint: str, protocol: str) -> Any:
    """The OTLP exporter for *protocol*, imported only when it is the one in use.

    Two protocols because one server cannot use the other. VictoriaTraces serves
    OTLP/HTTP on ``:10428`` — the same unauthenticated port that also answers
    *queries* — and OTLP/gRPC on ``:4317``, which ingests and nothing else.
    ``python-exec-secure`` runs LLM-generated code inside its own pod's network
    namespace, so whatever that pod may reach, the sandboxed script may reach:
    allowing ``:10428`` there would hand untrusted code read access to every
    trace on the platform, prompts and completions included. It exports over
    gRPC to ``:4317`` for that reason and that reason alone; everywhere else
    HTTP is the simpler dependency.
    """
    if protocol == "grpc":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcSpanExporter,
        )

        # A plain http:// endpoint means no TLS, which the exporter will not
        # infer for a bare host:port.
        return GrpcSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint)


def setup_tracing(
    service_name: str,
    *,
    service_version: str | None = None,
    environment: str | None = None,
    endpoint: str | None = None,
    protocol: str | None = None,
    scope: str | None = None,
) -> bool:
    """Configure the tracer provider and the OTLP exporter.

    ``endpoint`` falls back to ``OTEL_TRACES_ENDPOINT`` and ``protocol`` to
    ``OTEL_TRACES_PROTOCOL`` (``http/protobuf``, the default, or ``grpc``) — the
    names the platform values files use. Returns whether tracing ended up on.

    ``scope`` names the instrumentation library on every span this provider
    emits, and exists because this file is vendored beyond the MCP servers: a
    workflow engine reporting ``otel.scope.name = mcp_server`` reads as a
    mis-attribution to anyone looking at the span. A caller that is an MCP server
    leaves it unset.
    """
    global _tracer_provider, _tracer

    endpoint = endpoint or os.getenv("OTEL_TRACES_ENDPOINT")
    protocol = (protocol or os.getenv("OTEL_TRACES_PROTOCOL") or "http/protobuf").lower()
    if not endpoint:
        logger.info("otel.tracing_disabled")
        return False

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        attributes: dict[str, Any] = {"service.name": service_name}
        if service_version:
            attributes["service.version"] = service_version
        environment = environment or os.getenv("SERVICE_ENVIRONMENT")
        if environment:
            attributes["deployment.environment.name"] = environment

        # `Resource.create` merges OTEL_RESOURCE_ATTRIBUTES on top, which is how
        # k8s.pod.name reaches spans when the deployment fills it from the
        # downward API. Spans may carry pod identity; metrics may not — and this
        # server exports no metrics, so that rule never comes up here.
        _tracer_provider = TracerProvider(resource=Resource.create(attributes))
        _tracer_provider.add_span_processor(
            BatchSpanProcessor(_span_exporter(endpoint, protocol))
        )
        _tracer = _tracer_provider.get_tracer(scope or _INSTRUMENTATION_SCOPE, service_version or "")

        logger.info(
            "otel.tracing_ready",
            extra={"url.full": endpoint, "network.protocol.name": protocol},
        )
        return True
    except Exception as exc:  # noqa: BLE001 — never fail startup on telemetry
        logger.error("otel.tracing_failed", extra={"exception.message": str(exc)})
        _tracer_provider = None
        _tracer = None
        return False


class OtelSpanHooks:
    """The tracer, in the shape ``TraceContextMiddleware`` asks for.

    Takes the inbound context from a duck-typed ``trace`` (anything with
    ``trace_id`` / ``parent_span_id`` / ``trace_flags``) so this file needs no
    import from ``observability`` and both stay independently copyable.
    """

    def start_request_span(self, name: str, trace: Any) -> Any | None:
        """Start the SERVER span the outward-call spans hang off.

        Rooted in the caller's trace when one arrived — an MCP server is always
        called by the engine, so in production it always has one. A span that
        minted its own trace id would look like a request nobody made.
        """
        tracer = _tracer
        if tracer is None:
            return None

        try:
            from opentelemetry import trace as otel_trace
            from opentelemetry.context import Context
            from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags

            context = Context()
            trace_id = getattr(trace, "trace_id", None)
            parent_span_id = getattr(trace, "parent_span_id", None)
            if trace_id and parent_span_id:
                try:
                    remote = SpanContext(
                        trace_id=int(trace_id, 16),
                        span_id=int(parent_span_id, 16),
                        is_remote=True,
                        trace_flags=TraceFlags(int(getattr(trace, "trace_flags", "01") or "01", 16)),
                    )
                except ValueError:
                    remote = None
                if remote is not None and remote.trace_id and remote.span_id:
                    context = otel_trace.set_span_in_context(NonRecordingSpan(remote))

            span = tracer.start_span(name, context=context, kind=SpanKind.SERVER)
            _current_span_var.set(span)
            return span
        except Exception as exc:  # noqa: BLE001 — telemetry never breaks a request
            logger.warning(
                "otel.span_start_failed", extra={"stair.span": name, "exception.message": str(exc)}
            )
            return None

    def span_ids(self, span: Any) -> tuple[str, str] | None:
        """The span's ``(trace_id, span_id)`` as hex, for the log line."""
        try:
            context = span.get_span_context()
            return f"{context.trace_id:032x}", f"{context.span_id:016x}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("otel.span_ids_failed", extra={"exception.message": str(exc)})
            return None

    def end_request_span(
        self, span: Any, *, status_code: int | None = None, error: BaseException | None = None
    ) -> None:
        attributes: dict[str, Any] = {}
        if status_code is not None:
            attributes["http.response.status_code"] = status_code
        end_span(span, attributes=attributes, error=error)
        _current_span_var.set(None)


@contextmanager
def child_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any | None]:
    """Wrap one outward call in a child of the request's SERVER span.

    Yields None — and does nothing else — when tracing is off or when there is
    no SERVER span to hang off: a child floating in its own trace is worse than
    no span, because it looks like a request nobody made.
    """
    tracer = _tracer
    parent = _current_span_var.get()
    if tracer is None or parent is None:
        yield None
        return

    span = None
    try:
        from opentelemetry import trace as otel_trace

        span = tracer.start_span(name, context=otel_trace.set_span_in_context(parent))
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks a request
        logger.warning(
            "otel.span_start_failed", extra={"stair.span": name, "exception.message": str(exc)}
        )

    try:
        yield span
    except Exception as exc:
        end_span(span, attributes=attributes, error=exc)
        raise
    end_span(span, attributes=attributes)


def traceparent_for(span: Any | None) -> str | None:
    """The ``traceparent`` header naming *span*, for an outbound call.

    A server that owns spans must overwrite the inbound header rather than
    forward it: passing the caller's value on would make the callee's span a
    *sibling* of ours instead of a child, putting our work beside the callee's
    rather than around it. Returns None when there is no span, and the caller
    then falls back to the inbound header.
    """
    if span is None:
        return None
    try:
        context = span.get_span_context()
        return f"00-{context.trace_id:032x}-{context.span_id:016x}-{context.trace_flags:02x}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel.traceparent_failed", extra={"exception.message": str(exc)})
        return None


def set_span_attributes(span: Any | None, attributes: dict[str, Any]) -> None:
    """Add attributes discovered while the span was open (row counts, models)."""
    if span is None:
        return
    try:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel.span_attribute_failed", extra={"exception.message": str(exc)})


def end_span(
    span: Any | None,
    *,
    attributes: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    """Close a span with its attributes, tolerating any telemetry failure."""
    if span is None:
        return
    try:
        set_span_attributes(span, attributes or {})
        if error is not None:
            span.set_attribute("error.type", type(error).__name__)
            span.record_exception(error)
        span.end()
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel.span_end_failed", extra={"exception.message": str(exc)})


def shutdown_tracing() -> None:
    """Flush and shut the provider down (called from the app lifespan)."""
    global _tracer_provider, _tracer

    provider = _tracer_provider
    _tracer_provider = _tracer = None
    if provider is None:
        return
    try:
        provider.shutdown()  # flushes what is pending
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel.shutdown_failed", extra={"exception.message": str(exc)})
