# SQLAlchemy 2 Persistence Boundary

**Type:** guidance
**Version:** 20260909 V1
**Category:** Persistence
**Description:** SQLAlchemy 2 ORM, repository, DTO, and transaction rules for Python relational applications.

Technology reference. Apply when a Python Target has relational persistence.

Prerequisites: `languages/python/python.md`, `stack/persistence.md`

---

## Required Boundary

```text
route → service → repository → SQLAlchemy session/model → database
```

Only `persistence/` imports SQLAlchemy. Routes and services receive DTOs and call repository
methods. They never receive an ORM model, `Session`, `Row`, SQL string, table name, or column name.

Each public repository method corresponds to one feature-owned `FEATURE-<DOMAIN>-<NNN>` contract in `DATABASE.md`.
Its signature and DTO input/output are the public persistence API.

```python
# persistence/projects.py
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectModel

@dataclass(frozen=True)
class ProjectDashboard:
    id: int
    name: str
    status: str

class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_dashboard(self) -> list[ProjectDashboard]:
        rows = self._session.scalars(select(ProjectModel).order_by(ProjectModel.name)).all()
        return [ProjectDashboard(id=row.id, name=row.name, status=row.status) for row in rows]
```

```python
# service layer
def dashboard(projects: ProjectRepository) -> list[ProjectDashboard]:
    return projects.list_dashboard()
```

## Session Ownership

The application owns a configured `sessionmaker`; each request or unit of work opens one session,
commits on success, rolls back on failure, and closes it. Repository methods never commit
independently.

```python
from collections.abc import Iterator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

engine = create_engine(database_url)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

def session_scope() -> Iterator[Session]:
    with SessionFactory.begin() as session:
        yield session
```

## Guardrails

- Do not call `session.execute()` outside `persistence/`.
- Do not return ORM models from repositories.
- Do not use `Base.metadata.create_all()` outside disposable tests.
- Do not generate or apply schema changes from application startup.
- Every schema change is an Alembic revision; see `alembic.md`.
