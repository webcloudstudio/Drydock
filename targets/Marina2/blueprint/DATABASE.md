# DATABASE: Marina Data Stores

| Field       | Value |
|-------------|-------|
| Version     | 20260621 V1 |
| Description | Marina persists cloud catalog state in DynamoDB and local control-plane state in SQLite behind typed repository boundaries. |
| Depends On  | ARCHITECTURE.md |
| Provides    | marina-catalog-table, marina-local-sqlite-schema |
| Phase       | 1 |

## Cloud Store

### DynamoDB table

`marina-{project}-catalog`

Properties:
- billing mode: `PAY_PER_REQUEST`
- primary key: `PK` + `SK`
- SSE enabled
- point-in-time recovery enabled
- TTL enabled on attribute `ttl`

### Item model

| Item type | PK | SK | Required fields |
|-----------|----|----|-----------------|
| Project | `ORG#{org}` | `PROJECT#{project}` | `type`, `project`, `display_name`, `short_description`, `status`, `stack`, `repo`, `updated_at` |
| Capability | `ORG#{org}` | `PROJECT#{project}#CAP#{name}` | `type`, `project`, `name`, `description`, `tags`, `transports`, `owners`, `access`, `updated_at` |
| Heartbeat | `ORG#{org}` | `PROJECT#{project}#HB#{program}` | `type`, `project`, `program`, `state`, `message`, `updated_at` |
| Event | `ORG#{org}` | `PROJECT#{project}#EVT#{ulid}` | `type`, `project`, `severity`, `message`, `updated_at`, `ttl` |
| Access grant | `ORG#{org}` | `PROJECT#{project}#ACL#{principal}` | `type`, `project`, `principal`, `repo`, `access`, `updated_at` |
| Share index | `ORG#{org}` | `PROJECT#{project}#SHARE#{owner}#{key}` | `type`, `project`, `owner`, `key`, `size`, `content_type`, `updated_at` |

Every item carries `type`, `project`, and `updated_at`.

## Access Patterns

| # | Pattern | Operation | Key condition |
|---|---------|-----------|---------------|
| 1 | Upsert project metadata | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}` |
| 2 | Upsert capability | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}#CAP#{capability}` |
| 3 | Prune removed capabilities | `Query` + `DeleteItem` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{project}#CAP#")` |
| 4 | Read project subtree | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{project}")` |
| 5 | List org projects | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#")` with client-side `type=project` filter |
| 6 | List capabilities | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#")` with client-side `type=capability` and optional tag filter |
| 7 | Write heartbeat | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}#HB#{program}` |
| 8 | Append event | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}#EVT#{ulid}` |
| 9 | Read latest heartbeats | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{project}#HB#")` |
| 10 | Read recent events | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{project}#EVT#")` with `ScanIndexForward=False` and limit |
| 11 | Read ACL grant | `GetItem` | `PK=ORG#{org}, SK=PROJECT#{project}#ACL#{principal}` |
| 12 | Write ACL grant | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}#ACL#{principal}` |
| 13 | List share index rows | `Query` | `PK=ORG#{org} AND begins_with(SK,"PROJECT#{project}#SHARE#")` |
| 14 | Upsert share index row | `PutItem` | `PK=ORG#{org}, SK=PROJECT#{project}#SHARE#{owner}#{key}` |

No Scan is allowed in request-path logic.

## Write Rules

- Catalog publishes are full-project projections.
- Project and capability writes use `attribute_not_exists(SK) OR updated_at <= :now`.
- Heartbeats are latest-only per program.
- Events are append-only and time-ordered by ULID.
- Event TTL is `updated_at + 30 days`.
- Share index rows are rewritten on repeated `put` for the same object key.
- ACL writes are idempotent upserts.

## Local Store

### SQLite database

Path: `data/marina.db`

The local app reaches SQLite only through typed repository classes:

| Repository | Responsibility |
|------------|----------------|
| `SettingsRepository` | key-value settings reads and writes |
| `UserProfileRepository` | single-row alert profile |
| `GitHubSourceRepository` | configured GitHub scan sources |
| `GitHubRepoRepository` | cached GitHub repository inventory and download state |
| `ProjectRepository` | local project scan and conformance state |
| `PlatformStatsRepository` | scan counts, last-scan timestamp, and local verification status |
| `Database` | connection lifecycle and transaction boundary |

### Tables

#### `settings`

| Column | Type | Rules |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | setting name |
| `value` | TEXT NOT NULL | empty string means unset override |
| `updated_at` | TEXT NOT NULL | ISO-8601 timestamp |

Standard keys:
- `app_name`
- `app_theme`
- `aws_profile`
- `marina_org`
- `github_username`
- `PROJECTS_DIR`
- `MARINA_API_URL`
- `AWS_REGION`
- `AWS_PROFILE`
- `PORT`

#### `user_profile`

| Column | Type | Rules |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | always `1` |
| `email` | TEXT | optional but validated when present |
| `cell_phone` | TEXT | normalized to E.164 when present |
| `updated_at` | TEXT | ISO-8601 timestamp |

#### `github_sources`

| Column | Type | Rules |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `account` | TEXT NOT NULL UNIQUE | username, org slug, or URL |
| `account_type` | TEXT NOT NULL | `User`, `Org`, `URL`, or `Unknown` |
| `added_at` | TEXT NOT NULL | ISO-8601 timestamp |

#### `github_repos`

| Column | Type | Rules |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `name` | TEXT NOT NULL | repo name |
| `source_account` | TEXT NOT NULL | source owner or URL seed |
| `description` | TEXT | |
| `html_url` | TEXT | |
| `clone_url` | TEXT | HTTPS clone |
| `ssh_url` | TEXT | SSH clone |
| `private` | INTEGER NOT NULL | `0` or `1` |
| `pushed_at` | TEXT | ISO-8601 |
| `is_downloaded` | INTEGER NOT NULL | `0` or `1` |
| `is_conformed` | INTEGER NOT NULL | `0` or `1` |
| `synced_at` | TEXT NOT NULL | ISO-8601 |

Unique constraint: `(name, source_account)`.

#### `projects`

| Column | Type | Rules |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | |
| `name` | TEXT NOT NULL | directory or metadata name |
| `display_name` | TEXT | |
| `short_description` | TEXT | |
| `status` | TEXT | lifecycle status |
| `namespace` | TEXT | nullable |
| `path` | TEXT NOT NULL | absolute path |
| `git_repo` | TEXT | Git remote |
| `source_account` | TEXT | nullable when unmatched to configured sources |
| `conform_status` | TEXT | `conformed`, `needs_update`, or `unknown` |
| `is_conformed` | INTEGER NOT NULL | `0` or `1` |
| `is_published` | INTEGER NOT NULL | `0` or `1` |
| `published_at` | TEXT | ISO-8601 |
| `scan_at` | TEXT | ISO-8601 |
| `git_status` | TEXT | cached short status |

#### `platform_stats`

| Column | Type | Rules |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | stat name |
| `value` | TEXT NOT NULL | text storage for counts and flags |
| `updated_at` | TEXT NOT NULL | ISO-8601 timestamp |

Standard keys:
- `github_repo_count`
- `scan_projects_total`
- `projects_by_state_{status}`
- `catalog_last_published`
- `last_scan`
- `python_aws_ok`
- `terraform_deployed`
- `endpoint_reachable`

`last_scan` must be a full ISO-8601 timestamp with a UTC offset.

## Encapsulation Rules

- Application code does not issue ad hoc SQL from route handlers.
- Application code does not access DynamoDB directly outside the `marina` package and Lambda/storage services.
- A storage implementation change that preserves repository interfaces does not invalidate downstream features.

## Acceptance Criteria

- The DynamoDB schema serves catalog, capability, ACL, heartbeat, event, and share-index access without Scan operations.
- The SQLite schema covers settings, user profile, GitHub source inventory, GitHub repo cache, local project registry, and aggregate platform stats.
- Repository classes isolate all SQLite access from route handlers and view code.

## Guardrails

- No raw-storage access occurs outside typed repository or storage service boundaries.
- Event TTL stays enabled on `ttl`.
- `last_scan` always includes a timezone offset.

## Open Questions

- Heartbeat history remains latest-only in Phase 1 and Phase 2; a historical heartbeat ring is deferred unless a real incident requires it.
- Multi-user local installs are out of scope for V1; `user_profile` remains single-row.
