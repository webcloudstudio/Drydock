from __future__ import annotations

from datetime import UTC, datetime

from drydock.dependency_gate import (
    RegistryPackageInfo,
    canonicalize_package_name,
    check_python_dependency_manifests,
    collect_python_dependency_references,
)


class FakeRegistryClient:
    def __init__(self, packages: dict[tuple[str, str], RegistryPackageInfo]):
        self.packages = packages
        self.calls: list[tuple[str, str]] = []

    def lookup_package(self, normalized_name: str, registry_url: str) -> RegistryPackageInfo:
        self.calls.append((normalized_name, registry_url))
        return self.packages[(normalized_name, registry_url)]


def test_canonicalize_package_name():
    assert canonicalize_package_name("Python_DotEnv") == "python-dotenv"
    assert canonicalize_package_name("uvicorn.standard") == "uvicorn-standard"


def test_collect_dependency_references_from_pyproject_and_optional_groups(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "pyproject.toml").write_text(
        """
[project]
dependencies = ["python-dotenv>=1.0", "uvicorn[standard]>=0.29"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4"]
""",
        encoding="utf-8",
    )

    refs = collect_python_dependency_references(build_dir, ("pyproject.toml",))

    assert {(ref.package_name, ref.normalized_name) for ref in refs} == {
        ("python-dotenv", "python-dotenv"),
        ("uvicorn", "uvicorn"),
        ("pytest", "pytest"),
        ("ruff", "ruff"),
    }


def test_collect_dependency_references_from_requirements_ignores_non_registry_lines(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "requirements.txt").write_text(
        """
        Flask==3.0
        requests[socks]>=2.31 ; python_version >= "3.11"
        -r dev-requirements.txt
        git+https://example.com/repo.git
        thing @ https://example.com/thing.whl
        """,
        encoding="utf-8",
    )

    refs = collect_python_dependency_references(build_dir, ("requirements.txt",))

    assert {(ref.package_name, ref.normalized_name) for ref in refs} == {
        ("Flask", "flask"),
        ("requests", "requests"),
    }


def test_collect_dependency_references_from_uv_lock_uses_declared_registry(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "fastapi"
version = "0.110.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "workspace-local"
version = "0.1.0"
source = { editable = "." }
""",
        encoding="utf-8",
    )

    refs = collect_python_dependency_references(build_dir, ("uv.lock",))

    assert len(refs) == 1
    assert refs[0].package_name == "fastapi"
    assert refs[0].registry_url == "https://pypi.org/simple"


def test_check_python_dependency_manifests_reports_missing_and_new_packages(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "pyproject.toml").write_text(
        """
[project]
dependencies = ["good-package>=1.0", "missing-package>=1.0", "fresh-package>=1.0"]
""",
        encoding="utf-8",
    )
    client = FakeRegistryClient({
        ("good-package", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=True,
            registry_url="https://pypi.org/simple",
            first_published_at=datetime(2024, 1, 1, tzinfo=UTC),
        ),
        ("missing-package", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=False,
            registry_url="https://pypi.org/simple",
        ),
        ("fresh-package", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=True,
            registry_url="https://pypi.org/simple",
            first_published_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
    })

    result = check_python_dependency_manifests(
        build_dir,
        ("pyproject.toml",),
        client=client,
        today=datetime(2026, 7, 17, tzinfo=UTC).date(),
    )

    assert result.blocked is True
    assert result.scanned_files == ("pyproject.toml",)
    assert [issue.verdict for issue in result.issues] == ["missing", "newly-published"]
    assert result.issues[1].age_days == 16


def test_check_python_dependency_manifests_deduplicates_registry_lookups(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "pyproject.toml").write_text(
        """
[project]
dependencies = ["requests>=2.0"]

[project.optional-dependencies]
dev = ["requests>=2.0"]
""",
        encoding="utf-8",
    )
    client = FakeRegistryClient({
        ("requests", "https://pypi.org/simple"): RegistryPackageInfo(
            exists=True,
            registry_url="https://pypi.org/simple",
            first_published_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    })

    result = check_python_dependency_manifests(
        build_dir,
        ("pyproject.toml",),
        client=client,
        today=datetime(2026, 7, 17, tzinfo=UTC).date(),
    )

    assert result.blocked is False
    assert client.calls == [("requests", "https://pypi.org/simple")]
