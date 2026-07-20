# Rigging Manifest

Compact selection catalog for `drydock analyze` and QuarterDeck. Each entry names a real Rigging
component available for Commander selection. The manifest is selection context only; Analyze does
not open individual component files.

| File | Category | Purpose | Prerequisites |
|---|---|---|---|
| `BRANDING_DOCUMENTATION.md` | Branding | The users voice for Documentation voice, structure, and presentation rules. | — |
| `BRANDING_MAIN.md` | Branding | Core product branding (colors pallette etc ) and visual identity rules. | — |
| `BRANDING_POSTS.md` | Branding | Social and announcement post branding rules. | `BRANDING_MAIN.md` |
| `BRANDING_WEBSITE.md` | Branding | Website branding, voice, and presentation rules. | `BRANDING_MAIN.md` |
| `BRANDING_WHITEPAPERS.md` | Branding | Whitepaper branding and long-form presentation rules. | `BRANDING_MAIN.md` |
| `alexa-skills-kit.md` | AWS | Alexa Skill kit configuration, interaction models, and intent handling. | `common.md`, `python.md` |
| `aws-api-gateway.md` | AWS | AWS HTTP API Gateway Rules. | `aws-lambda.md` |
| `aws-dynamodb.md` | AWS | AWS DynamoDB single-table catalog and state patterns. | `cloud-client-library.md` |
| `aws-lambda.md` | AWS | AWS Lambda handlers, packaging, IAM, and testing patterns. | `python.md` |
| `aws-s3.md` | AWS | Private encrypted S3 storage and prefix-scoped sharing patterns. | `cloud-client-library.md` |
| `aws-sqs.md` | AWS | SQS durable queue, polling, and error-handling patterns. | `aws-lambda.md` |
| `bootstrap5.md` | Web Server | Bootstrap 5 layout, components, and form conventions. | — |
| `cloud-client-library.md` | AWS | Encapsulated AWS library for use in applications; application dont uses boto3. | `python.md`, `persistence.md` |
| `common.md` | Technologies | Common project layout, scripts, Git hygiene, and development workflow. | — |
| `django.md` | Web Server | Django settings, ORM, migrations, admin, and web application patterns. | `common.md`, `python.md` |
| `env_variables_and_secrets.md` | Technologies | Secret hygiene, environment validation, and `.env` discipline. | `common.md` |
| `fastapi.md` | Web Server | FastAPI routers, dependency injection, templates, and testing patterns. | `common.md`, `python.md` |
| `flask.md` | Web Server | Flask application factory, routes, templates, and error handling. | `common.md`, `python.md` |
| `github-actions.md` | Technologies | GitHub Actions CI/CD with OIDC and lint/test gates. | `terraform.md`, `python.md` |
| `persistence.md` | Persistence | Typed boundary for persistent stores and external services. | `common.md` |
| `postgres.md` | Persistence | PostgreSQL schema, pooling, migrations, and indexing patterns. | `python.md`, `persistence.md` |
| `python.md` | Technologies | Python conventions, typing, configuration, testing, and dependencies. | `common.md` |
| `sqlite.md` | Persistence | SQLite connections, migrations, WAL, and typed access patterns. | `python.md`, `persistence.md` |
| `terraform.md` | Technologies | Layered Terraform infrastructure and remote-state patterns. | `aws-dynamodb.md`, `aws-s3.md` |
| `typescript.md` | Technologies | TypeScript strict typing, domain modeling, and boundary validation. | `common.md` |
| `ui-flask.bootstrap-client.md` | Web Server | Focused Flask and Bootstrap screen implementation reference. | `flask.md`, `bootstrap5.md` |
| `uv_ruff.md` | Technologies | uv environments and ruff lint/format workflow. | `python.md` |
