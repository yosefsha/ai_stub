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
chosen by `scripts/create_remote_project.py --backend`. It owns the `backend/`
layout, the CI contract for that stack, and the container runtime. `ci.yml`
matches whichever one is there.

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
