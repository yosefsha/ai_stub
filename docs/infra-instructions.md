# Infrastructure & Configuration (AWS + Python CDK)

All configuration below is production-grade. Infrastructure is defined as code using **AWS CDK (Python)**.

> Note: this repo is a stub — `cdk.json` (the file that points the CDK CLI at `infra/app.py` and is required for any `cdk` command, e.g. `cdk synth`/`deploy`/`destroy`) does not exist yet. Add it before running CDK commands against a real project.

## CDK Project Structure
```
infra/
  app.py              # CDK app entry point
  stacks/
    __init__.py
    network_stack.py   # VPC, subnets, security groups
    backend_stack.py   # ECS/Fargate service for the backend API
    frontend_stack.py  # S3 + CloudFront for the SPA
    deploy_stack.py    # GitHub OIDC provider + deploy role, CfnOutputs
  config/
    prod.py            # Production environment config
    staging.py         # Staging environment config
```

## Backend (API on ECS Fargate)
- Deploy as a Docker container on **ECS Fargate** behind an **ALB**.
- Dockerfile: multi-stage build, listening on port **8000** — the base image, install step and entrypoint are stack-specific and live in the backend instructions doc CLAUDE.md imports (`docs/backend-python-instructions.md` or `docs/backend-nestjs-instructions.md`).
- Migrations run as the backend's own migration command (`alembic upgrade head` for Python, `npm run migration:run` for NestJS). It appears in exactly two places — `infra/stacks/backend_stack.py` and the `run-task-container-overrides` line in `deploy.yml` — and `scripts/copy_repo.py` swaps both when a project is generated with `--backend nestjs`.
- ALB health check targets `GET /health`.
- Auto-scaling: target 70% CPU utilization, min 2 / max 10 tasks.
- Logs to **CloudWatch Logs** with 30-day retention.
- Secrets (DB credentials, API keys) stored in **AWS Secrets Manager**, injected as environment variables via ECS task definition — never baked into images.
- Use **ECR** for container image registry.

## Frontend (SPA on S3 + CloudFront)
- `npm run build` output deployed to an **S3 bucket** (private, no public access).
- **CloudFront** distribution with OAC (Origin Access Control) to serve from S3.
- Custom domain via **Route 53** alias record to CloudFront.
- **ACM certificate** in `us-east-1` for HTTPS.
- Cache policy: immutable assets (`/assets/*`) cached 1 year; `index.html` cached 0 seconds (always revalidated).
- Enable CloudFront Functions or Lambda@Edge for SPA routing (return `index.html` for 404s).

## CI/CD (GitHub Actions)

CI/CD runs in **GitHub Actions** — there is no CodePipeline, CodeBuild, or CodeStar
Connection. Three workflows in `.github/workflows/`, each with one job to do.

### Authentication — OIDC, never stored keys
- No AWS credential is stored in the repository. Jobs declare `permissions: id-token: write`, and `aws-actions/configure-aws-credentials@v4` exchanges the GitHub OIDC token for short-lived STS credentials that expire with the job.
- The OIDC provider, the deploy role, and its trust policy live in `infra/stacks/deploy_stack.py`. The role name is **fixed and derivable** (`<service>-<env>-github-actions-deploy`) so the workflow can construct the ARN before it has credentials to look anything up with.
- Account id, region, and service name are repository **variables** (`vars.AWS_ACCOUNT_ID`, `vars.AWS_REGION`, `vars.SERVICE_NAME`), not secrets — none is a credential, and putting them in secrets only makes logs unreadable. Set them once per project; the gate job fails with an explicit message when `AWS_ACCOUNT_ID` is missing:
  ```bash
  gh variable set AWS_ACCOUNT_ID --body 123456789012
  gh variable set AWS_REGION     --body us-east-1
  gh variable set SERVICE_NAME   --body myapp
  ```
- Set `role-session-name` per job (e.g. `gha-backend-${{ github.run_id }}`) so a CloudTrail entry traces back to the run that made the call.

### `ci.yml` — the merge gate
- Triggers on `pull_request` and `push` to `main`, plus `workflow_dispatch`. Concurrency group per ref with `cancel-in-progress: true` — a new push supersedes the run it invalidated.
- `permissions: contents: read` only. `defaults.run.shell: bash` everywhere, so steps run under `bash -e -o pipefail`.
- Three independent jobs: **backend** (lint + tests for whichever backend stack the project uses), **frontend** (lint + type-check + test + build), **images** (docker build for both).
- Backend tests run against **real service containers** (Postgres, Redis) using the same images and health probes as `docker-compose.yml` — not mocks. Wait for each to accept a connection before testing, so an unreachable service is a clear failure rather than a confusing test error.
- Run database migrations **before** the suite. Without it the schema-less database makes database-backed tests skip themselves and the suite goes green having touched no table.
- **A skipped test is a CI failure.** Fixtures may skip locally where there is no database; in CI that same skip would let a broken repo through. Grep the test runner's output for skips and fail the job.
- Pin the linter version in the workflow (`pip install ruff==0.16.2` for Python), not in the project's dependency file — the gate must not drift under the codebase when a new release adds or relaxes a rule. A NestJS backend pins ESLint through its committed `package-lock.json`, which `npm ci` enforces.
- The backend job is the one job that differs per stack. `.github/workflows/ci.yml` ships the Python variant; `templates/backend-nestjs/.github/workflows/ci.yml` is the NestJS one, installed over it by `--backend nestjs`.
- Frontend lint must carry `--max-warnings 0`; otherwise every recommended-preset warning exits 0 and the gate can never fail. Run the type-check as its own step so a type error is reported as a type error, not as a build failure.
- The images job **builds but does not push** — it only proves the Dockerfiles still build.

### `deploy.yml` — deploy to AWS
- Triggers on `push` to `main`, plus `workflow_dispatch` with a `target` choice (`production` / `staging`). Concurrency per environment with **`cancel-in-progress: false`** — a cancelled deploy can leave a registered task definition nothing points at, or a migration applied while the old image still serves.
- A **gate** job runs first and everything else `needs` it:
  - Refuses to run unless `github.ref == 'refs/heads/main'`, so a dispatch from a branch cannot ship unmerged code. This is a convenience, not a control — the real control is the environment's deployment-branch policy, a repository setting.
  - **Waits for `ci.yml` to conclude successfully for the exact SHA** (`gh api .../workflows/ci.yml/runs?head_sha=…`) rather than re-running the suite. A pipeline outside GitHub has to re-run the tests because it cannot see GitHub's result; a GitHub job can just ask.
  - Resolves the target environment, the CDK env prefix, and the role ARN, and exposes them as job outputs.
- Human approval is a **GitHub Environment** with required reviewers (`environment:` on the job). Declaring the environment is what makes the job wait; the reviewer rule itself must be configured in repository settings.
- **Backend and frontend jobs are independent** — neither `needs` the other, so a failed frontend build does not hold back an API fix.
- Never hardcode resource names in the workflow. Read them from the deploy stack's **CloudFormation outputs** (`aws cloudformation describe-stacks`) with `jq -er`, so a renamed `CfnOutput` fails loudly instead of deploying with an empty cluster name.
- Backend job order: ECR login → build and push → migrate → update service.
  - Tag images with the **commit SHA**; also push `latest` purely as a bootstrap so a brand-new environment has something to pull before the first run. Task definitions deploy the SHA tag — a rollback is then a redeploy of a known revision, not a race with whatever `latest` points at.
  - Run migrations as a **one-off Fargate task inside the VPC**, not from the runner: RDS is in private subnets and admits only the ECS task security group. Use `aws-actions/amazon-ecs-deploy-task-definition@v2` with `run-task: true` and **`wait-for-task-stopped: true`** — without it, an accepted-but-failed migration reports as a successful deploy.
  - Then render the service task definition against the same image and deploy with **`wait-for-service-stability: true`**. The deployment circuit breaker rolls a bad release back, and without the wait the job would go green while the service quietly reverted.
- Frontend job: `npm ci` → lint → build → assume role → `aws s3 sync dist/ s3://<bucket>/ --delete` → CloudFront invalidation on `/*`, **waiting for the invalidation to complete** so "deployed" means the edge is serving the new build.

### `claude-review.yml` — automated PR review
- Runs `anthropics/claude-code-action@v1` on `pull_request` (`opened`, `synchronize`, `reopened`, `ready_for_review`), skipping drafts. Needs `pull-requests: write` and `fetch-depth: 0` to diff against the base branch.
- **Deliberately separate from `ci.yml`.** It calls a paid external API; folded into the merge gate, a rate limit or outage would redden merges for a reason unrelated to the code — and a gate that reddens for unrelated reasons is one people learn to ignore.
- **No `continue-on-error`, and fail loudly when the auth secret is missing.** A job that authenticates with nothing, posts nothing, and reports success is indistinguishable from a clean review.

## Networking
- **VPC** with public and private subnets across 2+ AZs.
- ALB in public subnets, ECS tasks in private subnets.
- **NAT Gateway** for outbound internet from private subnets.
- Security groups: ALB allows inbound 443 only; ECS tasks allow inbound from ALB security group on port 8000 only.

## Monitoring & Observability
- **CloudWatch Alarms**: ALB 5xx rate > 1%, ECS CPU > 80%, unhealthy host count > 0.
- **SNS topic** for alarm notifications (email/PagerDuty).
- Structured JSON logging from FastAPI (use `python-json-logger`).
- **X-Ray** tracing on ALB and ECS for request tracing.

## Environment Configuration
- All environment-specific values (domain names, instance counts, feature flags) defined in `infra/config/` Python files — not hardcoded in stacks.
- CDK stacks accept an `env_config` parameter to swap between staging and production.
- Tag all resources with `Environment`, `Service`, and `Owner` tags.
- Enable **CDK Nag** (`cdk-nag`) in the pipeline to enforce AWS best practices and catch security issues before deployment.
