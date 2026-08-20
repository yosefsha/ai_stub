# Backend — Python / FastAPI

The backend service lives in `backend/`. `.github/workflows/ci.yml` hardcodes
that directory as its working directory and runs on every push, so **CI is red
until it exists with the files below.**

```
backend/
  requirements.txt        # Runtime dependencies
  requirements-dev.txt    # Includes requirements.txt, adds pytest + httpx
  Dockerfile              # python:3.12-slim base
  alembic.ini             # `alembic upgrade head` runs in CI before the suite
  app/
    __init__.py
    main.py               # FastAPI app, route definitions
    models.py             # Pydantic request/response schemas
    <domain>.py           # Business logic classes
    <domain>_loader.py    # Data loading / parsing utilities
    repositories/         # One module per data source — see "Protocol" below
  tests/
    __init__.py
    test_<module>.py      # Mirror app/ structure
  config/
    *.json                # Runtime configuration files
```

What CI needs from the backend, beyond the files existing:
- `pip install -r backend/requirements-dev.txt` must pull in `pytest`, `httpx`, `psycopg` and `redis` — the last two are what the readiness check imports.
- `alembic upgrade head` must apply cleanly to an empty database.
- **`pytest` must not skip.** A skipped test fails the build; fixtures that skip themselves when no database is present will trip it, so gate them on something CI satisfies.
- `ruff check .` must pass. The version is pinned in the workflow, not in `requirements-dev.txt`, so the gate cannot drift under the codebase.

## Code Style
- Type-annotate all function signatures including return types.
- Use `dataclass(frozen=True)` for internal value objects that don't need Pydantic validation.
- Use Pydantic `BaseModel` for API request/response schemas.
- Route handlers must be thin — delegate to business logic classes.
- Use `snake_case` for functions and variables, `PascalCase` for classes.
- One class/concern per file.

## Configuration
- Use environment variables for all runtime configuration (DB URLs, file paths, feature flags).
- Provide sensible defaults so local development works without any env vars set.
- Load configuration at module level so it's available at startup.

## Data sources go behind a Protocol
Anything fetched from outside the process — an HTTP API, a database, a cache, a
queue — is reached through a `typing.Protocol` named in domain terms, with
domain return types and its own exception types. One implementation per source
under `app/repositories/`, injected with FastAPI `Depends`, plus an in-memory
fake for tests. The full rule set lives in `.claude/agents/backend-engineer.md`.

## Testing
- Use `pytest` as the test runner.
- Use FastAPI's `TestClient` for API/integration tests.
- Unit tests should construct dependencies inline (no shared global fixtures for business logic).
- Test both success paths and error/edge cases.
- Run a single test: `pytest tests/test_file.py::test_name`

## Dependencies
- Pin minimum versions in `requirements.txt` (e.g., `fastapi>=0.115.0`).
- For production, generate a locked `requirements.lock` with exact versions.

## Container runtime
- Multi-stage `Dockerfile` on a `python:3.12-slim` base, installing from the locked `requirements.lock`.
- Entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`. Port **8000** is what the ALB target group and the ECS security groups expect.
- `GET /health` must return 200 — the ALB health check targets it.
- Database migrations run as `alembic upgrade head`, both in CI and as the one-off ECS task in `deploy.yml`.

## Tracing (OpenTelemetry)
Spans are instrumented in the application; where they are sent is a deployment
detail. Local runs and production emit the *same* spans — only the exporter
differs, and it is chosen from the environment at startup, never by an `if` in
a route.

- Configure tracing once, at startup, before the first request. It lives in
  `app/tracing.py` and is called from `main.py`.
- With no collector configured, `ConsoleSpanExporter` prints each span to
  stdout as JSON — parent/child nesting, durations and attributes, readable in
  the terminal that is already open. This is the local debugging setup: no
  container, no agent, no browser tab.
- When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the OTLP exporter takes over.
  That env var is the only difference between a laptop and ECS.

```python
# app/tracing.py
import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "backend")


def configure_tracing(app: FastAPI) -> None:
    exporter = OTLPSpanExporter() if OTLP_ENDPOINT else ConsoleSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
```

`excluded_urls="health"` is not optional: the ALB probes `GET /health` every
30 seconds per task, and those spans would outnumber the real traffic.

Instrumenting your own code:

```python
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("parse_order") as span:
    span.set_attribute("order.id", order_id)
```

- Span names are low-cardinality domain verbs (`parse_order`, `settle_invoice`).
  Never interpolate an id into a name — ids are attributes.
- Auto-instrument the boundaries you don't own (FastAPI, `httpx`, `psycopg`)
  and write manual spans only for domain steps worth naming. A span per
  private helper produces a waterfall nobody reads.
- **Record the failure path.** `span.record_exception(exc)` and
  `span.set_status(Status(StatusCode.ERROR))` in the handler that catches it,
  or the trace of a request that 500'd looks fast and successful.
- Traces complement structured logs, they do not replace them. Log the
  `trace_id` so a log line leads to its trace.

Dependencies: `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`,
`opentelemetry-exporter-otlp-proto-http`.

For a waterfall UI locally, add `jaegertracing/all-in-one` to
`docker-compose.yml` (ports `16686` for the UI, `4318` for OTLP/HTTP) and set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`. One container, and the
application code does not change.
