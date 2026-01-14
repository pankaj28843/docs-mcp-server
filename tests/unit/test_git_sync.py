"""Unit tests for git sparse checkout utility."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess

import pytest

from docs_mcp_server.utils.git_sync import (
    DOCUMENTATION_EXTENSIONS,
    GitRepoSyncer,
    GitSourceConfig,
    GitSyncError,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clone_and_strip_prefix(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "remote")
    _write_file(repo, "aidlc/docs/chapter.md", "v1")
    _write_file(repo, "aidlc/docs/guide.md", "v1")
    _commit(repo, "initial")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["aidlc/docs"],
        strip_prefix="aidlc",
    )
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "work" / "repo", export_path=tmp_path / "export")

    result = await syncer.sync()

    assert result.files_copied == 2
    assert not result.warnings
    assert (tmp_path / "export" / "docs" / "chapter.md").read_text() == "v1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_updates_exported_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "remote2")
    _write_file(repo, "docs/file.md", "one")
    _commit(repo, "initial")

    config = GitSourceConfig(repo_url=str(repo), branch="main", subpaths=["docs"], strip_prefix="docs")
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "work2" / "repo", export_path=tmp_path / "export2")

    await syncer.sync()
    _write_file(repo, "docs/file.md", "two")
    _commit(repo, "update")

    result = await syncer.sync()

    assert result.repo_updated is True
    assert (tmp_path / "export2" / "file.md").read_text() == "two"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_subpath_is_reported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "remote3")
    _write_file(repo, "docs/exists.md", "data")
    _commit(repo, "initial")

    config = GitSourceConfig(repo_url=str(repo), branch="main", subpaths=["missing"], strip_prefix=None)
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "work3" / "repo", export_path=tmp_path / "export3")

    result = await syncer.sync()

    assert result.files_copied == 0
    assert len(result.warnings) == 1
    assert "missing" in result.warnings[0]


@pytest.mark.unit
def test_requires_subpaths(tmp_path: Path) -> None:
    config = GitSourceConfig(repo_url="https://example.com/repo.git", branch="main", subpaths=[])
    with pytest.raises(GitSyncError):
        GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")


@pytest.mark.unit
def test_strip_prefix_edge_cases(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
    )
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    assert syncer._apply_strip_prefix(Path("docs", "guide.md")) == Path("guide.md")
    # When the path matches the prefix exactly, we expect an empty Path that callers treat as project root.
    assert syncer._apply_strip_prefix(Path("docs")) == Path()
    # Paths outside the prefix should be preserved without raising.
    assert syncer._apply_strip_prefix(Path("examples", "demo.md")) == Path("examples", "demo.md")


@pytest.mark.unit
def test_normalize_optional_path_rejects_traversal(tmp_path: Path) -> None:
    config = GitSourceConfig(repo_url="https://example.com/repo.git", branch="main", subpaths=["docs"])
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    with pytest.raises(GitSyncError):
        syncer._normalize_optional_path("../secret")


@pytest.mark.unit
def test_build_git_env_with_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    token_value = "secret-token"
    calls: list[str] = []

    def fake_env_loader(name: str) -> str | None:
        calls.append(name)
        return token_value

    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        auth_token_env="GIT_TOKEN",
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "repo",
        export_path=tmp_path / "export",
        env_loader=fake_env_loader,
    )

    env = syncer._build_git_env()

    askpass = syncer._askpass_script
    assert askpass is not None and askpass.exists()
    assert env["GIT_SYNC_TOKEN"] == token_value
    assert env["GIT_ASKPASS"] == str(askpass)
    assert "GIT_TOKEN" in calls

    # Second call should use cached token without re-reading env or rewriting the script.
    calls.clear()
    second_env = syncer._build_git_env()
    assert second_env["GIT_SYNC_TOKEN"] == token_value
    assert not calls


@pytest.mark.unit
def test_build_git_env_missing_token_raises(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        auth_token_env="GIT_TOKEN",
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "repo",
        export_path=tmp_path / "export",
        env_loader=lambda _name: None,
    )

    with pytest.raises(GitSyncError):
        syncer._build_git_env()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_git_handles_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = GitSourceConfig(repo_url="https://example.com/repo.git", branch="main", subpaths=["docs"])
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    async def fake_exec(*_args, **_kwargs):
        raise FileNotFoundError("git missing")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(GitSyncError, match="git executable not found"):
        await syncer._run_git("status")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_git_raises_on_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = GitSourceConfig(repo_url="https://example.com/repo.git", branch="main", subpaths=["docs"])
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    class DummyProcess:
        def __init__(self, returncode: int, stdout: bytes, stderr: bytes):
            self.returncode = returncode
            self._stdout = stdout
            self._stderr = stderr

        async def communicate(self):
            return self._stdout, self._stderr

    async def fake_exec(*_args, **_kwargs):
        return DummyProcess(returncode=1, stdout=b"", stderr=b"fatal: error")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(GitSyncError) as exc:
        await syncer._run_git("status")

    assert "git command failed" in str(exc.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clone_repository_removes_existing_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git", branch="main", subpaths=["docs"], strip_prefix="docs"
    )
    repo_path = tmp_path / "work" / "repo"
    export_path = tmp_path / "export"
    repo_path.mkdir(parents=True)
    (repo_path / "stale.txt").write_text("stale")

    syncer = GitRepoSyncer(config, repo_path=repo_path, export_path=export_path)

    calls: list[tuple[tuple[str, ...], dict]] = []

    async def fake_run_git(*args: str, **kwargs):
        calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(syncer, "_run_git", fake_run_git)

    await syncer._clone_repository()

    # Ensure the previous repo directory was removed before cloning.
    assert not (repo_path / "stale.txt").exists()
    assert calls
    clone_args, clone_kwargs = calls[0]
    assert clone_args[0] == "clone"
    assert "--sparse" in clone_args
    assert "--depth" in clone_args
    # Cloning should happen from the parent directory (use_repo=False).
    assert clone_kwargs["use_repo"] is False


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(path, "init", "-b", "main")
    _run_git(path, "config", "user.name", "Docs MCP Test")
    _run_git(path, "config", "user.email", "docs@example.com")
    return path


def _write_file(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def _commit(repo: Path, message: str) -> None:
    _run_git(repo, "add", ".")
    # Allow empty commits when files removed between syncs
    _run_git(repo, "commit", "-m", message, "--allow-empty")


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# ============================================================================
# Extension Filtering Tests
# ============================================================================


@pytest.mark.unit
def test_documentation_extensions_contains_common_formats() -> None:
    """Verify that DOCUMENTATION_EXTENSIONS includes all expected formats."""
    # Markdown variants
    assert ".md" in DOCUMENTATION_EXTENSIONS
    assert ".markdown" in DOCUMENTATION_EXTENSIONS
    assert ".mdown" in DOCUMENTATION_EXTENSIONS

    # reStructuredText
    assert ".rst" in DOCUMENTATION_EXTENSIONS
    assert ".rest" in DOCUMENTATION_EXTENSIONS

    # Plain text
    assert ".txt" in DOCUMENTATION_EXTENSIONS
    assert ".text" in DOCUMENTATION_EXTENSIONS

    # AsciiDoc
    assert ".adoc" in DOCUMENTATION_EXTENSIONS
    assert ".asciidoc" in DOCUMENTATION_EXTENSIONS

    # HTML/XML
    assert ".html" in DOCUMENTATION_EXTENSIONS
    assert ".htm" in DOCUMENTATION_EXTENSIONS
    assert ".xml" in DOCUMENTATION_EXTENSIONS

    # Jupyter notebooks
    assert ".ipynb" in DOCUMENTATION_EXTENSIONS

    # Org-mode
    assert ".org" in DOCUMENTATION_EXTENSIONS

    # LaTeX
    assert ".tex" in DOCUMENTATION_EXTENSIONS
    assert ".latex" in DOCUMENTATION_EXTENSIONS

    # YAML/JSON/TOML
    assert ".yaml" in DOCUMENTATION_EXTENSIONS
    assert ".yml" in DOCUMENTATION_EXTENSIONS
    assert ".json" in DOCUMENTATION_EXTENSIONS
    assert ".toml" in DOCUMENTATION_EXTENSIONS

    # Man pages
    assert ".man" in DOCUMENTATION_EXTENSIONS
    for i in range(1, 10):
        assert f".{i}" in DOCUMENTATION_EXTENSIONS


@pytest.mark.unit
def test_documentation_extensions_is_lowercase() -> None:
    """All extensions in the set should be lowercase for case-insensitive matching."""
    for ext in DOCUMENTATION_EXTENSIONS:
        assert ext == ext.lower(), f"Extension {ext} should be lowercase"
        assert ext.startswith("."), f"Extension {ext} should start with a dot"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_extension_filter_includes_documentation_files(tmp_path: Path) -> None:
    """Default config (include_extensions=None) should only copy documentation files."""
    repo = _init_repo(tmp_path / "remote_ext1")

    # Documentation files - should be copied
    _write_file(repo, "docs/readme.md", "markdown")
    _write_file(repo, "docs/guide.rst", "restructured")
    _write_file(repo, "docs/notes.txt", "plain text")
    _write_file(repo, "docs/api.html", "html")
    _write_file(repo, "docs/schema.yaml", "yaml")
    _write_file(repo, "docs/notebook.ipynb", "jupyter")

    # Non-documentation files - should be excluded
    _write_file(repo, "docs/script.py", "python")
    _write_file(repo, "docs/image.png", "binary")
    _write_file(repo, "docs/styles.css", "css")
    _write_file(repo, "docs/code.js", "javascript")

    _commit(repo, "mixed files")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
        # include_extensions=None uses DOCUMENTATION_EXTENSIONS by default
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "work_ext1" / "repo",
        export_path=tmp_path / "export_ext1",
    )

    result = await syncer.sync()

    # Only documentation files should be copied
    assert result.files_copied == 6
    assert (tmp_path / "export_ext1" / "readme.md").exists()
    assert (tmp_path / "export_ext1" / "guide.rst").exists()
    assert (tmp_path / "export_ext1" / "notes.txt").exists()
    assert (tmp_path / "export_ext1" / "api.html").exists()
    assert (tmp_path / "export_ext1" / "schema.yaml").exists()
    assert (tmp_path / "export_ext1" / "notebook.ipynb").exists()

    # Non-documentation files should NOT exist
    assert not (tmp_path / "export_ext1" / "script.py").exists()
    assert not (tmp_path / "export_ext1" / "image.png").exists()
    assert not (tmp_path / "export_ext1" / "styles.css").exists()
    assert not (tmp_path / "export_ext1" / "code.js").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_extension_filter_includes_all_files(tmp_path: Path) -> None:
    """Empty include_extensions set should include ALL files."""
    repo = _init_repo(tmp_path / "remote_ext2")

    _write_file(repo, "docs/readme.md", "markdown")
    _write_file(repo, "docs/script.py", "python")
    _write_file(repo, "docs/styles.css", "css")
    _commit(repo, "mixed files")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
        include_extensions=frozenset(),  # Empty = include all
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "work_ext2" / "repo",
        export_path=tmp_path / "export_ext2",
    )

    result = await syncer.sync()

    assert result.files_copied == 3
    assert (tmp_path / "export_ext2" / "readme.md").exists()
    assert (tmp_path / "export_ext2" / "script.py").exists()
    assert (tmp_path / "export_ext2" / "styles.css").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_extension_filter(tmp_path: Path) -> None:
    """Custom include_extensions should only include specified extensions."""
    repo = _init_repo(tmp_path / "remote_ext3")

    _write_file(repo, "docs/readme.md", "markdown")
    _write_file(repo, "docs/guide.rst", "restructured")
    _write_file(repo, "docs/notes.txt", "plain text")
    _commit(repo, "doc files")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
        include_extensions=frozenset({".md", ".txt"}),  # Only markdown and text
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "work_ext3" / "repo",
        export_path=tmp_path / "export_ext3",
    )

    result = await syncer.sync()

    assert result.files_copied == 2
    assert (tmp_path / "export_ext3" / "readme.md").exists()
    assert (tmp_path / "export_ext3" / "notes.txt").exists()
    assert not (tmp_path / "export_ext3" / "guide.rst").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extension_filter_is_case_insensitive(tmp_path: Path) -> None:
    """Extension filtering should be case-insensitive."""
    repo = _init_repo(tmp_path / "remote_ext4")

    _write_file(repo, "docs/README.MD", "uppercase ext")
    _write_file(repo, "docs/Guide.Rst", "mixed case")
    _write_file(repo, "docs/notes.TXT", "upper")
    _commit(repo, "mixed case extensions")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
        include_extensions=frozenset({".md", ".rst", ".txt"}),
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "work_ext4" / "repo",
        export_path=tmp_path / "export_ext4",
    )

    result = await syncer.sync()

    assert result.files_copied == 3
    assert (tmp_path / "export_ext4" / "README.MD").exists()
    assert (tmp_path / "export_ext4" / "Guide.Rst").exists()
    assert (tmp_path / "export_ext4" / "notes.TXT").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extension_filter_with_nested_directories(tmp_path: Path) -> None:
    """Extension filtering should work with nested directory structures."""
    repo = _init_repo(tmp_path / "remote_ext5")

    _write_file(repo, "docs/intro/readme.md", "intro md")
    _write_file(repo, "docs/intro/image.png", "image")
    _write_file(repo, "docs/api/reference.rst", "api rst")
    _write_file(repo, "docs/api/schema.json", "api json")
    _write_file(repo, "docs/tutorials/deep/nested/guide.adoc", "nested adoc")
    _write_file(repo, "docs/tutorials/deep/nested/code.py", "nested py")
    _commit(repo, "nested structure")

    config = GitSourceConfig(
        repo_url=str(repo),
        branch="main",
        subpaths=["docs"],
        strip_prefix="docs",
        # Default: use DOCUMENTATION_EXTENSIONS
    )
    syncer = GitRepoSyncer(
        config,
        repo_path=tmp_path / "work_ext5" / "repo",
        export_path=tmp_path / "export_ext5",
    )

    result = await syncer.sync()

    # Documentation files in nested dirs should be copied
    assert result.files_copied == 4
    assert (tmp_path / "export_ext5" / "intro" / "readme.md").exists()
    assert (tmp_path / "export_ext5" / "api" / "reference.rst").exists()
    assert (tmp_path / "export_ext5" / "api" / "schema.json").exists()
    assert (tmp_path / "export_ext5" / "tutorials" / "deep" / "nested" / "guide.adoc").exists()

    # Non-documentation files should NOT exist
    assert not (tmp_path / "export_ext5" / "intro" / "image.png").exists()
    assert not (tmp_path / "export_ext5" / "tutorials" / "deep" / "nested" / "code.py").exists()


@pytest.mark.asyncio
async def test_export_subpaths_removes_existing_staging_dir(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        strip_prefix=None,
        auth_token_env=None,
        shallow_clone=True,
        include_extensions=frozenset({".md"}),
    )
    repo_path = tmp_path / "repo"
    export_path = tmp_path / "export"
    syncer = GitRepoSyncer(config, repo_path=repo_path, export_path=export_path)

    (repo_path / "docs").mkdir(parents=True, exist_ok=True)
    (repo_path / "docs" / "readme.md").write_text("hello", encoding="utf-8")

    staging_dir = export_path.parent / f".{export_path.name}.git-staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "old.txt").write_text("old", encoding="utf-8")

    files_copied, warnings = await syncer._export_subpaths()

    assert files_copied == 1
    assert warnings == []
    assert export_path.exists()


def test_apply_strip_prefix_noop_when_missing(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        strip_prefix=None,
        auth_token_env=None,
        shallow_clone=True,
        include_extensions=frozenset({".md"}),
    )
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    relative = Path("docs/guide.md")

    assert syncer._apply_strip_prefix(relative) == relative  # pylint: disable=protected-access


def test_normalize_subpaths_skips_empty_entries(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        strip_prefix=None,
        auth_token_env=None,
        shallow_clone=True,
        include_extensions=frozenset({".md"}),
    )
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    normalized = syncer._normalize_subpaths(["", "docs", " "])  # pylint: disable=protected-access

    assert normalized == ["docs"]


def test_normalize_optional_path_handles_empty_and_dot(tmp_path: Path) -> None:
    config = GitSourceConfig(
        repo_url="https://example.com/repo.git",
        branch="main",
        subpaths=["docs"],
        strip_prefix=None,
        auth_token_env=None,
        shallow_clone=True,
        include_extensions=frozenset({".md"}),
    )
    syncer = GitRepoSyncer(config, repo_path=tmp_path / "repo", export_path=tmp_path / "export")

    assert syncer._normalize_optional_path("  ") is None  # pylint: disable=protected-access
    assert syncer._normalize_optional_path(".") is None  # pylint: disable=protected-access
