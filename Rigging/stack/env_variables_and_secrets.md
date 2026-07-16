# Environment Variables and Secrets

**Version:** 20260716 V1  
**Category:** Technologies
**Description:** Secret hygiene and environment-variable discipline for specification-driven projects

Technology reference for configuration and secret handling. Language-agnostic — applies to every project. This file does not change between projects.

Prerequisite: `stack/common.md`

---

## 1. Never Commit Secrets

**Rule**: Never commit secrets or real credentials — not in code, config, tests, fixtures, examples, or commit history. Keep `.env` and equivalent local secret files ignored.

```gitignore
# .gitignore
.env
.env.*
!.env.example
*.pem
*.key
credentials*.json
```

Rules:
- Secrets reach the process only through the environment (local `.env`, CI secrets store, or a cloud secret manager) — never through tracked files or source code.
- Test fixtures use obvious fakes (`test-key`, `sk-fake-000`), never expired or "harmless" real credentials.
- A secret that touches git history is compromised: rotate it immediately; do not rely on a follow-up commit that deletes it.

**Why**: Git history is permanent and widely copied. Rotation is the only remedy once a credential lands in it, and prevention is far cheaper than rotation.

---

## 2. Maintain `.env.example`

**Rule**: Maintain a committed `.env.example` whenever environment variables are introduced, changed, or removed. It must stay synchronized with the actual variable names the application reads and contain safe dummy values or clear placeholders.

```bash
# .env.example — every variable the app reads, nothing more
SECRET_KEY=change-me
DATABASE_PATH=data/app.db
APP_PORT=5001
APP_DEBUG=0
SMTP_HOST=smtp.example.com
SMTP_PASSWORD=<your-smtp-password>
```

Rules:
- Any change to the variables the application reads updates `.env.example` in the same commit.
- Values are dummies (`change-me`) or placeholders (`<your-smtp-password>`) — never real values, even for "non-sensitive" settings copied from a real environment.
- New-clone setup is `cp .env.example .env` plus filling in real values; if that does not produce a bootable app, the example has drifted.

**Why**: `.env.example` is the executable documentation of the app's configuration surface. Drift turns every new environment setup into archaeology.

---

## 3. Validate Early, Fail Usefully

**Rule**: Validate required environment variables at startup and fail with an error that names the missing or malformed variable. Never let a missing variable surface as a `None`/`undefined` crash at first use.

```python
# Python — the typed Config class is the only env reader (stack/python.md §1)
raise RuntimeError(f"Missing required env var: {e}") from e
```

```typescript
// TypeScript — schema-validated at startup (stack/typescript.md §5)
export const config = ConfigSchema.parse(process.env);  // throws naming the bad field
```

Rules:
- One typed config object per process is the only reader of the environment; app code never reads `os.environ` / `process.env` directly.
- Required variables crash at startup when absent; optional variables have explicit defaults visible in the config definition.
- Error messages name the variable and expected form — "Missing required env var: SECRET_KEY", not a stack trace from deep inside a request handler.

**Why**: A process that boots misconfigured fails later, in production, at the worst moment. Startup validation converts that into an immediate, self-explanatory failure.

---

## 4. Do Not Over-Environmentalize

**Rule**: Avoid introducing environment variables when configuration can safely remain static and non-sensitive. The environment is for secrets and per-environment differences, not for every constant.

Decision test — a value belongs in the environment only if at least one holds:
- It is a secret (API key, password, signing key).
- It genuinely differs between dev/test/prod (port, database path, log level).
- An operator must change it without a deploy.

Otherwise it is code: a named constant or a checked-in config file, typed, versioned, and reviewed.

**Why**: Every environment variable adds a degree of freedom that must be documented, defaulted, validated, and kept synchronized in `.env.example` and every deployment. Static values in code are visible in review and cannot drift per machine.

---

## Summary Checklist

- [ ] No secrets or real credentials in code, tests, fixtures, or git history; leaked secrets rotated
- [ ] `.env` and local secret files gitignored; `!.env.example` explicitly tracked
- [ ] `.env.example` updated in the same commit as any variable change; names match what the app reads; values are dummies or placeholders
- [ ] Required env vars validated at startup through the single typed config; failures name the variable
- [ ] No env var introduced where a static, non-sensitive constant suffices
