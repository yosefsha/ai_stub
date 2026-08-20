# Backend — TypeScript / NestJS

The backend service lives in `backend/`. `.github/workflows/ci.yml` hardcodes
that directory as its working directory and runs on every push, so **CI is red
until it exists with the files below.**

```
backend/
  package.json            # Must define: start:dev, build, start:prod, lint, type-check, test, test:e2e, migration:run, migration:generate
  package-lock.json       # CI runs `npm ci`, which fails without it
  tsconfig.json           # strict: true
  tsconfig.build.json     # Excludes tests from the production build
  nest-cli.json
  eslint.config.mjs       # Flat config; `npm run lint` carries --max-warnings 0
  Dockerfile              # node:22-alpine base, multi-stage
  src/
    main.ts               # bootstrap(): global ValidationPipe, listens on PORT (default 8000)
    app.module.ts         # Root module — imports feature modules and ConfigModule
    config/
      configuration.ts    # Typed config factory
      validation.ts       # Env schema — the app refuses to boot on a bad env
    health/
      health.module.ts
      health.controller.ts  # GET /health — the ALB health check target
    <domain>/
      <domain>.module.ts
      <domain>.controller.ts  # Thin — validates and delegates
      <domain>.service.ts     # Business logic
      dto/<name>.dto.ts       # class-validator request/response DTOs
      <domain>.repository.ts  # Port interface + injection token — see below
      repositories/           # One file per concrete source (Postgres, HTTP, …)
    migrations/           # TypeORM migrations — `npm run migration:run` applies them
  test/
    <domain>.e2e-spec.ts  # Supertest against the real Nest app
    jest-e2e.json
```

Unit specs (`*.spec.ts`) sit next to the file they cover under `src/`; end-to-end
specs (`*.e2e-spec.ts`) live in `test/`.

What CI needs from the backend, beyond the files existing:
- `npm ci` must install `pg` and `ioredis` — they are what the readiness check imports before the suite runs.
- `npm run migration:run` must apply cleanly to an empty database.
- **The suite must not skip.** A skipped or `todo` test fails the build; specs that skip themselves when no database is present will trip it, so gate them on something CI satisfies.
- `npm run lint` must carry `--max-warnings 0`, or the lint gate can never fail — `typescript-eslint`'s recommended preset ships most rules as warnings.
- `npm run type-check` (`tsc --noEmit -p tsconfig.json`) is its own gate, so a type error is reported as a type error rather than as a build failure.

## Code Style
- Type every function signature including the return type. `strict: true` in `tsconfig.json`, and no `any` — use `unknown` and narrow.
- One class/concern per file. `PascalCase` for classes/types/interfaces, `camelCase` for functions/variables, `kebab-case.<role>.ts` for filenames (`order.service.ts`, `create-order.dto.ts`).
- Controllers must be thin — validate, delegate to a service, map to a response DTO. No business logic, no data access.
- Request/response shapes are `class`-based DTOs with `class-validator` decorators, not bare interfaces — the global `ValidationPipe` needs a class at runtime.
- Enable the global pipe with `whitelist: true`, `forbidNonWhitelisted: true`, `transform: true` so unknown fields are rejected rather than silently carried.
- Use constructor injection with `readonly` parameters. No property injection, no service locator.
- Internal value objects are `readonly` interfaces or classes with `readonly` fields — immutable by default.
- Throw Nest's `HttpException` subclasses (`NotFoundException`, `ConflictException`, …) from the service layer, or map domain errors to them in an exception filter. Never leak a driver error to the client.

## Configuration
- Use `@nestjs/config` with `isGlobal: true` and a typed `configuration.ts` factory. Read config through `ConfigService`, never `process.env` outside that factory.
- Validate the environment at startup with a schema (`validation.ts`); an invalid env must fail the boot, not surface as an undefined at the first request.
- Provide sensible defaults so `npm run start:dev` works with no env vars set: `PORT=8000`, `DATABASE_URL=postgresql://app:app@localhost:5432/app`, `REDIS_URL=redis://localhost:6379/0`.
- Secrets come from the environment (Secrets Manager in ECS) — never from a committed `.env`.

## Data sources go behind a port interface
Anything fetched from outside the process — an HTTP API, a database, a cache, a
queue — is reached through an `interface` named in domain terms, with domain
return types and its own error types. One implementation per source under
`<domain>/repositories/`, bound to an injection token in the module's
`providers`, plus an in-memory fake for tests. The full rule set lives in
`.claude/agents/backend-engineer-nestjs.md`.

## Testing
- `jest` as the runner, `supertest` for HTTP-level tests.
- Unit tests construct the service under test directly (`new OrderService(fake)`) — reach for `Test.createTestingModule` only when Nest's DI is what's under test.
- E2E specs boot the real `AppModule` against the real Postgres and Redis containers, with the same global pipes as `main.ts`, and assert on status codes and body shapes.
- Substitute the in-memory fake through `overrideProvider(TOKEN)`; do not mock the driver.
- Test both success paths and error/edge cases.
- Run a single test: `npm test -- src/orders/order.service.spec.ts -t "rejects a duplicate"`

## Dependencies
- `package.json` pins ranges; `package-lock.json` is the lock and is committed. CI runs `npm ci`, so the two must agree.
- Runtime deps stay out of `devDependencies` — the production image installs with `npm ci --omit=dev`.

## Container runtime
- Multi-stage `Dockerfile` on a `node:22-alpine` base: a builder stage runs `npm ci` and `npm run build`, the runtime stage runs `npm ci --omit=dev` and copies `dist/`.
- Entrypoint: `node dist/main.js`, listening on **8000** — that is what the ALB target group and the ECS security groups expect, so `main.ts` must default `PORT` to 8000 rather than Nest's own 3000.
- Run as a non-root user, and `dumb-init` (or `--init`) as PID 1 so SIGTERM reaches Node and `app.enableShutdownHooks()` can drain.
- `GET /health` must return 200 — the ALB health check targets it.
- Database migrations run as `npm run migration:run`, both in CI and as the one-off ECS task in `deploy.yml`. The runtime image must therefore ship the compiled migrations and the TypeORM CLI datasource.

## Tracing (OpenTelemetry)
Spans are instrumented in the application; where they are sent is a deployment
detail. Local runs and production emit the *same* spans — only the exporter
differs, and it is chosen from the environment at startup, never by an `if` in
a controller.

- `src/tracing.ts` is imported as the **first line of `main.ts`**, before
  `NestFactory` or any module. Auto-instrumentation patches `http`, `pg` and
  the rest as they are required; anything loaded before the SDK starts is
  never instrumented.
- With no collector configured, `ConsoleSpanExporter` prints each span to
  stdout — parent/child nesting, durations and attributes, readable in the
  terminal that is already open. This is the local debugging setup: no
  container, no agent, no browser tab.
- When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the OTLP exporter takes over.
  That env var is the only difference between a laptop and ECS.

```typescript
// src/tracing.ts — imported first in main.ts, before any Nest module
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { ConsoleSpanExporter } from '@opentelemetry/sdk-trace-node';

const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

const sdk = new NodeSDK({
  serviceName: process.env.OTEL_SERVICE_NAME ?? 'backend',
  traceExporter: otlpEndpoint ? new OTLPTraceExporter() : new ConsoleSpanExporter(),
  instrumentations: [
    getNodeAutoInstrumentations({
      '@opentelemetry/instrumentation-http': {
        ignoreIncomingRequestHook: (req) => req.url === '/health',
      },
      '@opentelemetry/instrumentation-fs': { enabled: false },
    }),
  ],
});

sdk.start();
process.once('SIGTERM', () => void sdk.shutdown());
```

```typescript
// src/main.ts
import './tracing';           // must stay first — see above
import { NestFactory } from '@nestjs/core';
```

Two deliberate exceptions to the rules elsewhere in this document:

- **`process.env` is read directly here.** Tracing starts before the Nest
  container exists, so `ConfigService` is not available yet. This file is the
  only place outside `config/configuration.ts` allowed to touch `process.env`.
- Skipping `/health` is not optional: the ALB probes it every 30 seconds per
  task, and those spans would outnumber the real traffic. `instrumentation-fs`
  is off for the same reason — it spans every file read.

Instrumenting your own code:

```typescript
import { trace } from '@opentelemetry/api';

const tracer = trace.getTracer('orders');

return tracer.startActiveSpan('parse_order', (span) => {
  span.setAttribute('order.id', orderId);
  try {
    return this.parse(payload);
  } finally {
    span.end();
  }
});
```

- Span names are low-cardinality domain verbs (`parse_order`, `settle_invoice`).
  Never interpolate an id into a name — ids are attributes.
- Auto-instrument the boundaries you don't own (HTTP, `pg`, `ioredis`) and
  write manual spans only for domain steps worth naming. A span per private
  method produces a waterfall nobody reads.
- **Record the failure path.** `span.recordException(err)` and
  `span.setStatus({ code: SpanStatusCode.ERROR })` where the error is caught,
  or the trace of a request that 500'd looks fast and successful.
- `span.end()` belongs in a `finally`. A span that is never ended is never
  exported, so the bug you were chasing leaves no trace at all.
- Traces complement structured logs, they do not replace them. Log the
  `traceId` so a log line leads to its trace.

Dependencies: `@opentelemetry/sdk-node`, `@opentelemetry/api`,
`@opentelemetry/auto-instrumentations-node`,
`@opentelemetry/exporter-trace-otlp-http`. They are runtime dependencies — the
production image installs with `npm ci --omit=dev`, and `dist/tracing.js` must
be there.

For a waterfall UI locally, add `jaegertracing/all-in-one` to
`docker-compose.yml` (ports `16686` for the UI, `4318` for OTLP/HTTP) and set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`. One container, and the
application code does not change.
