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
