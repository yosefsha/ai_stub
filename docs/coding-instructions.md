# Coding Instructions

## General

- All configuration must be production-ready standard — no placeholder values, TODO stubs, or "good enough for now" defaults. Every config entry should be deployable to production as-is.

## Repository Layout

The two services live in `backend/` and `frontend/` at the repository root.
`.github/workflows/ci.yml` hardcodes those directory names as its working
directories and runs on every push, so **CI fails until both exist with the
files below.** A freshly generated project is red on its first push; creating
these is the first task, not a later cleanup.

```
backend/
  requirements.txt        # Runtime dependencies
  requirements-dev.txt    # Includes requirements.txt, adds pytest + httpx
  Dockerfile              # python:3.12-slim base
  alembic.ini             # `alembic upgrade head` runs in CI before the suite
  app/ tests/ config/     # See "Python / FastAPI" below
frontend/
  package.json            # Must define: dev, build, type-check, lint, test
  package-lock.json       # CI runs `npm ci`, which fails without it
  Dockerfile              # node:22-alpine base
  src/                    # See the frontend section below
docker-compose.yml        # Local Postgres + Redis, same images as CI
```

What CI needs from each, beyond the files existing:
- `pip install -r backend/requirements-dev.txt` must pull in `pytest`, `httpx`, `psycopg` and `redis` — the last two are what the readiness check imports.
- `alembic upgrade head` must apply cleanly to an empty database.
- **`pytest` must not skip.** A skipped test fails the build; fixtures that skip themselves when no database is present will trip it, so gate them on something CI satisfies.
- `npm run lint` must carry `--max-warnings 0`, or the lint gate can never fail.

Building only one of the two services is a change to `ci.yml` — delete the job
you don't need rather than leaving it red.

## Repository Setup (GitHub)

Files alone are not enough — the workflows need repository settings that live
outside the codebase. Do this once per generated project.

### `CLAUDE_CODE_OAUTH_TOKEN` secret (required by `claude-review.yml`)

Without it, every pull request gets a red "Claude review" check. The workflow
verifies the secret before doing anything and fails loudly rather than exiting
green, because a review that authenticated with nothing and posted nothing is
indistinguishable from a clean review.

```bash
claude setup-token                                    # prints an OAuth token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
```

`claude setup-token` requires a Claude Pro or Max subscription. To bill an API
key instead, set `ANTHROPIC_API_KEY` as the secret and swap
`claude_code_oauth_token:` for `anthropic_api_key:` in the workflow.

Two limits worth knowing before concluding the token is broken:
- **Fork pull requests never receive secrets.** The review only runs for branches pushed to this repository.
- **Draft pull requests are skipped** until marked ready for review.

## Python / FastAPI

### Project Structure
```
backend/
  app/
    __init__.py
    main.py            # FastAPI app, route definitions
    models.py           # Pydantic request/response schemas
    <domain>.py         # Business logic classes
    <domain>_loader.py  # Data loading / parsing utilities
  tests/
    __init__.py
    test_<module>.py    # Mirror app/ structure
  config/
    *.json              # Runtime configuration files
```

### Code Style
- Type-annotate all function signatures including return types.
- Use `dataclass(frozen=True)` for internal value objects that don't need Pydantic validation.
- Use Pydantic `BaseModel` for API request/response schemas.
- Route handlers must be thin — delegate to business logic classes.
- Use `snake_case` for functions and variables, `PascalCase` for classes.
- One class/concern per file.

### Configuration
- Use environment variables for all runtime configuration (DB URLs, file paths, feature flags).
- Provide sensible defaults so local development works without any env vars set.
- Load configuration at module level so it's available at startup.

### Testing
- Use `pytest` as the test runner.
- Use FastAPI's `TestClient` for API/integration tests.
- Unit tests should construct dependencies inline (no shared global fixtures for business logic).
- Test both success paths and error/edge cases.
- Run a single test: `pytest tests/test_file.py::test_name`

### Dependencies
- Pin minimum versions in `requirements.txt` (e.g., `fastapi>=0.115.0`).
- For production, generate a locked `requirements.lock` with exact versions.

---

## React / TypeScript

### Project Structure
```
frontend/
  src/
    main.tsx            # Entry point
    App.tsx             # Root component
    types.ts            # Shared type definitions
    parser.ts           # Pure utility functions
    components/
      <Name>.tsx        # One component per file, PascalCase filename
```

### Code Style
- Functional components only — no class components.
- Define props as a standalone `interface Props` above the component.
- Use named exports for all components (exception: root `App`).
- `camelCase` for functions/variables, `PascalCase` for components/types/interfaces.
- Keep parsing and transformation logic in pure functions outside components.
- Shared types go in `types.ts`, not scattered across components.

### State & Effects
- Use `useEffect` cleanup functions for mount/unmount lifecycle work.
- Derive state from props where possible instead of duplicating into local state.

### Layout
- Use CSS Grid or Flexbox via inline styles unless a CSS framework is adopted.

### Build & Lint
`package.json` must define all four scripts — CI calls them by name and does not
know which framework or toolchain sits behind them.
- `npm run dev` — Vite dev server with HMR.
- `npm run build` — type-check then Vite production build.
- `npm run type-check` — the type-checker for this project (`tsc -b`, `vue-tsc -b`, …). CI runs it as its own gate so a type error is reported as one.
- `npm run lint` — ESLint, and it must carry `--max-warnings 0`. Recommended presets ship most rules as warnings; without the flag the CI lint gate can never fail.
- `npm run test` — the unit test suite.
