# Technology Stack Reference Library

**Purpose**: Reusable, prescriptive best practices for building projects with chosen technologies.

These technology files are **shared across all projects** in this specification system. Each file is:
- **Prescriptive** — Not descriptive; each rule has concrete code examples
- **Opinionated** — Reflects production best practices and lessons learned
- **Standalone** — Self-contained; can be read independently
- **Copy-Paste Ready** — Code examples are immediately usable

---

# Catalog

| File | Maps to STACK.yaml | Covers |
|------|-------------------|--------|
| `common.md` | *(always)* | Directory layout, bin/ scripts, Links.md, CLAUDE.md conventions, git hygiene, dev workflow |
| `env_variables_and_secrets.md` | *(always)* | Secret hygiene, `.env`/`.env.example` discipline, early env validation, when not to use env vars |
| `python.md` | `language: python` | Config classes, code style, type hints and static typing, logging, testing with pytest, dependencies, startup validation |
| `uv_ruff.md` | `tooling: uv-ruff` | uv environment/lock workflow, ruff lint+format configuration, identical local/CI gates |
| `typescript.md` | `language: typescript` | Code style, strict compiler settings, no `any`/unsafe assertions, explicit domain modeling, boundary validation, generated types |
| `go.md` | `language: go` | Module layout, errors as values, consumer-side interfaces, goroutine lifetimes, table-driven tests, build and lint gates, dependency discipline |
| `flask.md` | `framework: flask` | App factory, blueprints, Jinja2, HTMX, test client, security |
| `django.md` | `framework: django` | Settings package, ORM, migrations, admin, django-htmx |
| `sqlite.md` | `database: sqlite` | Connection setup, PRAGMAs, JSON columns, migrations, backup |
| `postgres.md` | `database: postgres` | Connection pooling, JSONB, numbered migrations, indexing |
| `bootstrap5.md` | `frontend: bootstrap5` | CDN setup, dark theme, components, HTMX integration |
| `alexa-skills-kit.md` | `aws_services: [alexa-skills-kit]` | Alexa Skill configuration, interaction models, intent handling |
| `aws-lambda.md` | `aws_services: [aws-lambda]` | Lambda function structure, environment setup, testing, IAM |
| `aws-sqs.md` | `aws_services: [aws-sqs]` | Queue configuration, polling patterns, error handling |
| `aws-api-gateway.md` | `aws_services: [aws-api-gateway]` | API setup, IAM/SigV4 auth, Lambda proxy, throttling |
| `aws-dynamodb.md` | `aws_services: [aws-dynamodb]` | Single-table hierarchical design, on-demand billing, access patterns |
| `aws-s3.md` | `aws_services: [aws-s3]` | Private buckets, prefix-per-user company share, encryption, lifecycle |
| `terraform.md` | `infra: terraform` | Layered roots, S3+DynamoDB remote backend, naming/tags, bash wrappers |
| `github-actions.md` | `ci: github-actions` | OIDC role assumption, ruff/pytest gates, plan-on-PR / apply-on-merge |
| `cloud-client-library.md` | `lib: cloud-client` | A project-owned cloud client library — the single cloud boundary (never raw boto3) |

---

# Stacks

## Technology Groupings

### Cross-Cutting
- **env_variables_and_secrets.md** — Secret hygiene and environment-variable discipline (all languages)

### Languages
- **python.md** — Server-side Python application development
- **typescript.md** — Typed JavaScript application development (strict compilation, boundary validation)
- **go.md** — Go application and CLI development (module layout, errors as values, owned goroutines)

### Tooling
- **uv_ruff.md** — Python toolchain: uv environments/dependencies, ruff lint+format

### Web Frameworks
- **flask.md** — Lightweight Python web framework with HTMX
- **django.md** — Full-featured Python web framework

### Databases
- **sqlite.md** — Local/embedded SQL database (WAL mode, JSON support)
- **postgres.md** — Production PostgreSQL with connection pooling

### Frontend
- **bootstrap5.md** — CSS framework with dark theme variant

### AWS Cloud Services
- **aws-lambda.md** — Serverless compute
- **aws-sqs.md** — Message queuing (durable store-and-forward)
- **aws-api-gateway.md** — HTTP API routing (IAM/SigV4)
- **aws-dynamodb.md** — On-demand NoSQL catalog/state (single-table)
- **aws-s3.md** — Blob storage and per-user company share
- **alexa-skills-kit.md** — Voice interaction platform

### Infrastructure & Delivery
- **terraform.md** — Infrastructure as code (layered, remote backend)
- **github-actions.md** — CI/CD pipelines (OIDC, no static keys)

### Client Library
- **cloud-client-library.md** — The project-owned cloud indirection library (swap layer)

---

# Prerequisites

## For Using These Files

1. **Read `common.md` first** — Applies to all projects
2. **Read language file** — Choose Python, Node, etc.
3. **Read framework file** — Choose Flask, Django, etc.
4. **Read database file** — Choose SQLite, PostgreSQL, etc.
5. **Read frontend file** — Choose Bootstrap 5, Tailwind, etc.
6. **Read AWS service files** — As needed for your project

## Dependency Chain

```
common.md (always required)
├── python.md
│   ├── flask.md or django.md
│   └── [sqlite.md or postgres.md]
├── bootstrap5.md
└── aws-*.md (optional, as needed)
```

## Validation

Before starting a project:
1. Create `STACK.yaml` in your project directory
2. List all selected technologies
3. Run `validate.sh` to verify all referenced stack files exist
4. Run `generate-prompt.sh` to create a merged prompt for Claude AI

---

# Structure of a Technology File

Each technology file follows this pattern:

### Header
- **Technology name**
- **Prerequisites** — Which other stack files to read first
- **Version/Last Updated**

### Rules (1–5 per file)

Each rule contains:
1. **Rule** — Prescriptive one-liner (e.g., "Always enable WAL mode")
2. **Implementation** — Concrete, copy-paste code examples
3. **Why** — Brief rationale and tradeoffs
4. **Summary Checklist** — Items to verify before shipping

### Example Structure

```markdown
# Flask Best Practices

Prerequisites: stack/common.md, stack/python.md

---

## 1. Application Factory

**Rule**: Use a `create_app()` factory function...

**Implementation**:
```python
# app.py
...code example...
```

**Why**: Factory pattern enables multiple app instances...

---

## Summary Checklist
- [ ] App created via create_app() factory
- [ ] Blueprints registered in factory
- [ ] Config classes used (Dev, Test, Prod)
...
```

---

# Using Stack Files in Your Project

### Step 1: Create METADATA.md

```yaml
language: python
framework: flask
database: sqlite
frontend: bootstrap5

project:
  name: MyProject
  title: "My Project Title"
  port: 5001

specifications:
  - 01-OVERVIEW.md
  - 02-ARCHITECTURE.md
  # ... etc
```

### Step 2: Validate

```bash
./validate.sh MyProject
# Checks that all referenced stack files exist
```

### Step 3: Generate Prompt

```bash
./generate-prompt.sh MyProject
# Merges stack files into a single prompt for Claude AI
```

### Step 4: Follow the Rules

For each rule in the stack files:
1. Read the **Rule** statement
2. Copy the **Implementation** code
3. Understand the **Why** rationale
4. Check items off the **Summary Checklist**

---

# Adding New Technology Files

If you need a technology not yet covered:

1. **Create `stack/technology-name.md`**
2. **Follow the structure above** (Header, Rules, Implementation, Why, Checklist)
3. **Add entry to this README** with file mapping and description
4. **Update validation logic** in `validate.sh` if introducing new STACK.yaml keys
5. **Document prerequisites** at the top of the file

---

# Sharing & Version Control

- These files are **version controlled** in git
- **No project should fork or modify** a stack file for its own use
- If a rule needs updating for all projects, **update the file in place**
- If a rule is project-specific, **document it in CLAUDE.md**, not in stack/ files

---

# Quick Reference

### I'm starting a new project — what files do I read?
1. `common.md`
2. `python.md` (or your language)
3. `flask.md` or `django.md` (or your framework)
4. `sqlite.md` or `postgres.md` (or your database)
5. `bootstrap5.md` (or your frontend)

### I'm adding AWS Lambda to my project — what do I read?
1. `aws-lambda.md`
2. `aws-sqs.md` (if using SQS)
3. `aws-api-gateway.md` (if building an API)

### I disagree with a rule — what do I do?
1. Discuss with the team in a GitHub issue
2. If it's project-specific, document the exception in your project's `CLAUDE.md`
3. If it's a universal improvement, propose updating the stack file

---

# Next Steps

1. Choose your technology stack
2. Create your project directory with `STACK.yaml`
3. Run `validate.sh` to verify setup
4. Read through the relevant stack files in order
5. Create your project-specific specification files (01-OVERVIEW.md, etc.)
