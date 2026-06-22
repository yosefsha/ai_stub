---
name: security-review
description: Security review of the current branch diff. Runs standard checks then applies FNTC-specific rules (org scoping, Cognito token handling, SQL injection, FastAPI auth, Bedrock/LLM injection). Use on any PR before merge.
context: fork
agent: Explore
allowed-tools: Read, Bash, Glob, Grep
---

# FNTC Security Review

## Diff to review
- Changed files: !`git diff --name-only main`
- Full diff: !`git diff main`

## Current branch
- Branch: !`git branch --show-current`
- Commits since main: !`git log main..HEAD --oneline`

---

## Step 1 — Standard security checks (apply to all files in diff)

Check every changed file for:

- **Secrets / credentials** — hardcoded API keys, passwords, tokens, AWS keys, client secrets. Flag any string that looks like a secret not sourced from `os.environ`.
- **SQL injection** — queries built with f-strings or `%s %` formatting instead of parameterized queries (`$1` in asyncpg, `%s` with separate params in Django). Flag any f-string or `.format()` inside a SQL string.
- **Shell injection** — `subprocess` calls with unsanitized input, `os.system()`.
- **Sensitive data in logs** — `logger.*`, `print()`, `console.log()` emitting tokens, passwords, `cognito_sub`, PII, or financial amounts.
- **Debug/dev backdoors** — `DEBUG=True` committed to non-dev config, `AllowAny` on non-auth endpoints, commented-out auth checks, `verify=False` on HTTPS calls.
- **Insecure deserialization** — `pickle.loads`, `yaml.load()` without `Loader=`, `eval()` on external input.
- **New dependencies** — flag new entries in `requirements.txt` or `package.json` that have known CVEs or look suspicious.

---

## Step 2 — FNTC-specific checks

### 2A — Org scoping (IDOR prevention)
Every queryset and raw SQL query touching financial data (`Transaction`, `Invoice`, `Bill`, `BankAccount`, `ForecastJob`, `ChatSession`, `ChatMessage`) **must** be scoped to the authenticated org.

**Correct Django pattern:**
```python
queryset = Transaction.objects.filter(org_account=get_user_org_account(request.user))
```
**Correct FastAPI pattern:**
```python
org_id = await get_user_org_account_id(user_id)  # from fastapi/auth.py
# SQL: WHERE org_account_id = $1  with org_id as the param
```

Flag any query that:
- Sources `org_id` / `org_account_id` from request params, body, or model/LLM args instead of the JWT-derived value
- Is missing a `WHERE org_account_id = ...` clause on the above models
- Uses `.all()` or `.filter()` without an org constraint on financial models

### 2B — FastAPI authentication
Every new FastAPI endpoint must call `get_current_user_id(request)` from `fastapi/auth.py` before doing any work.

```python
user_id = await get_current_user_id(request)   # ← must be present
org_id  = await get_user_org_account_id(user_id)
```

Flag endpoints that:
- Decode the Bearer token themselves instead of using `get_current_user_id()`
- Accept `user_id` or `org_id` as query/path params and trust them without JWT validation
- Have no auth call at all

### 2C — Cognito token handling
- Cognito `AccessToken`, `RefreshToken`, `IdToken` must **never** appear in logs, API responses, or error messages.
- `cognito_sub` (UUID) must not be returned in any API response body — it is an internal identifier only.
- Token validation must use `algorithms=["RS256"]` in production. HS256 is local-dev only, gated on `COGNITO_USER_POOL_ID` being empty.
- `verify_aud: False` is acceptable only on AccessTokens (Cognito doesn't set `aud` on them). Flag if applied to IdTokens.

### 2D — Bedrock / LLM prompt injection (fastapi/chat.py)
- The system prompt must always include the authenticated org name/ID to scope the assistant — verify `get_financial_context()` still sets this.
- Tool definitions (`toolConfig`) must not expose `org_id` as a parameter the model can supply — it is always injected server-side in `execute_tool()` (SR-2).
- Tool results returned to Bedrock must not include raw SQL, stack traces, or internal DB identifiers.
- The tool-calling loop must retain the max-iterations guard (currently 5). Flag if removed or raised above 10.
- Flag any new tool that accepts free-form user text as a SQL filter or file path.

### 2E — Lambda / SQS message integrity
- SQS message body must be validated before processing: `job_id` must be a valid UUID, `org_account_id` a positive integer.
- Lambda must verify `org_account_id` ownership before running Prophet (prevent IDOR via crafted SQS messages).
- DLQ messages must not contain PII, message content, or full financial data — only `job_id` and error metadata.

### 2F — CDK / IAM least privilege
- New IAM statements must use specific resource ARNs, not `"*"`.
- Lambda execution roles must not have broad permissions like `s3:*`, `dynamodb:*`, `cognito-idp:*`.
- New Secrets Manager reads must be scoped to the specific secret ARN.
- `removal_policy=DESTROY` on stateful resources (RDS, Cognito User Pool, S3 buckets with data) is a **critical** flag — these should be `RETAIN`.

---

## Step 3 — Output format

For each finding output:

```
[SEVERITY] Category — file:line
Issue description.
Recommended fix.
```

Severity levels:
- **CRITICAL** — exploitable now (auth bypass, cross-org data leak, hardcoded secret in committed code)
- **HIGH** — exploitable with moderate effort (missing org scope, token logged, HS256 in prod path)
- **MEDIUM** — defense-in-depth gap (missing input validation, broad IAM, missing ownership check in Lambda)
- **LOW** — hygiene / best practice (print() instead of logger, overly broad exception swallowing)

End with a summary:

| Severity | Count |
|----------|-------|
| CRITICAL | n |
| HIGH     | n |
| MEDIUM   | n |
| LOW      | n |

If a category has no issues, write: `✅ <Category> — nothing to flag`
