# Coding Instructions

## General

- All configuration must be production-ready standard — no placeholder values, TODO stubs, or "good enough for now" defaults. Every config entry should be deployable to production as-is.
- Write to the industry standard of the language and framework in front of you, not to a personal style. The stack's own idioms and its community conventions win over a clever alternative; a reviewer who knows FastAPI, NestJS or React should recognise the shape of the code without being told how this repo does things.

## Design Principles

Follow SOLID, and treat it as a set of concrete obligations rather than a slogan
to cite in review. What each one demands here:

- **Single responsibility** — one class, one reason to change. A route handler that also parses a payload, applies a business rule and writes to a database has three. Split it, and put the pieces where the structure section says they go.
- **Open/closed** — adding a case should mean adding a file, not editing a growing `if`/`switch`. When a second variant of something arrives, that is the signal to extract the abstraction the first one implied — not a signal to add another branch.
- **Liskov substitution** — every implementation of an interface must be usable through it without the caller knowing which one it got. An implementation that only works when the caller special-cases it, or that raises where its siblings return, has broken the contract, not extended it.
- **Interface segregation** — small, purpose-named interfaces. A caller that needs one method must not be made to depend on nine. Prefer several narrow ports over one service-shaped interface that everything ends up importing.
- **Dependency inversion** — business logic depends on abstractions it owns and names; concrete clients (HTTP, database, cache, queue) depend on those abstractions and are wired in at the edge. This is the rule the backend "data sources go behind a Protocol/port" section exists to enforce, and it is the one that carries the most weight in this codebase.

Extensibility is judged by the same standard the Protocol/port rule applies:
**adding the second source, provider or variant must not require editing the
code that consumes the first.** If it does, the seam is in the wrong place.

Two limits, so the above doesn't become its own kind of damage:

- **Extensibility is the seam, not extra code.** Build the abstraction and one real implementation (plus the in-memory fake tests use). Do not write a second implementation, a plugin registry or a configuration switch for a case nobody has asked for — YAGNI outranks a speculative interface.
- **Do not abstract on first use.** A single implementation behind a hand-rolled framework is harder to change than the concrete code it replaced. The exception is anything crossing a process boundary, which goes behind a port immediately — that boundary is known to move.

Also standard, and not negotiable per-feature:

- **DRY within a bounded context, not across the repo.** Two things that merely look alike are not duplication; coupling them because of the resemblance is worse than repeating them.
- **Fail loudly at the boundary.** Validate input where it enters the process and reject it there. Never swallow an exception to keep a request alive, and never let a transport-level error (an HTTP client error, a driver error) reach a caller that has no way to interpret it.
- **Make illegal states unrepresentable.** Immutable value objects, exhaustive types, no optional field that is really required — lean on the type system rather than on a runtime check a later caller can skip.
- **Every public function is typed, named for what it does in domain terms, and covered by a test for its failure path as well as its success path.**

## Repository Layout

The two services live in `backend/` and `frontend/` at the repository root.
`.github/workflows/ci.yml` hardcodes those directory names as its working
directories and runs on every push, so **CI fails until both exist with the
files below.** A freshly generated project is red on its first push; creating
these is the first task, not a later cleanup.

```
backend/                  # Language-specific — see the backend instructions
                          # doc CLAUDE.md imports for its layout and CI needs
frontend/
  package.json            # Must define: dev, build, type-check, lint, test
  package-lock.json       # CI runs `npm ci`, which fails without it
  Dockerfile              # node:22-alpine base
  src/                    # See the frontend section below
docker-compose.yml        # Local Postgres + Redis, same images as CI
```

Exactly one backend instructions doc is present in a generated project —
`docs/backend-python-instructions.md` or `docs/backend-nestjs-instructions.md`,
chosen by the required `--backend` flag of `scripts/create_remote_project.py`.
It owns the `backend/` layout, the CI contract for that stack, and the
container runtime. `ci.yml` matches whichever one is there.

That doc also carries the tracing section, kept or dropped by the same script's
`--with-otel` / `--without-otel` flag. A project generated with `--without-otel`
has no tracing guidance anywhere; one generated with `--with-otel` instruments
spans in the application and picks its exporter from the environment, so the
local run prints them to stdout and needs no collector.

What CI needs from the frontend, beyond the files existing:
- **`npm run lint` must carry `--max-warnings 0`**, or the lint gate can never fail.
- `npm run type-check` runs as its own gate, so a type error is reported as one.
- `npm run test` must not skip — a skipped test is treated as a failure.

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
