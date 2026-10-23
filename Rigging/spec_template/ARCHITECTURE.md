# ARCHITECTURE: __PROJECT_NAME__

| Field | Value |
|-------|-------|
| Version | __TODAY__ V1 |
| Description | Modules, routes, and directory layout for __PROJECT_NAME__. |
| Depends On | |
| Provides | |
| Build Order | |

<!-- Code organization: modules, entry point, routes, directory layout. -->

## Modules

| Module | Responsibility |
|--------|---------------|
| | |

## Module Ownership

| Module | Owns | May Access |
|--------|------|------------|
| config.py | Typed configuration loading and validation | os.environ |
| db.py | Database connection, schema, migrations, and table classes | database driver |
| filestore.py | Application file storage | pathlib, open |
| services/ | External service wrappers | service client libraries |

## Routes

| Method | Path | Returns |
|--------|------|---------|
| GET | / | |

## Directory Layout

```
__PROJECT_SLUG__/
```

## Programmatic Acceptance

<!-- Required. The foundation story implements this file. One criterion per delivered capability:
the application starts, its entry point imports, a health route answers. Each criterion is a
standalone script: act on the product, read the state back, assert it. A story implementing this
file is refused without one. -->

## User Acceptance

- None.

## Guardrails

- None.
