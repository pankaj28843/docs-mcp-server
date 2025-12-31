"""Sparse checkout + export workflow for git-backed tenants."""

from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
from time import perf_counter


logger = logging.getLogger(__name__)


# Documentation file extensions (case-insensitive) supported for git sync export.
# These are commonly used human and machine readable documentation formats.
# Organized by category for maintainability.
DOCUMENTATION_EXTENSIONS: frozenset[str] = frozenset(
    {
        # --- Markdown variants ---
        ".md",
        ".markdown",
        ".mdown",
        ".mkd",
        ".mkdn",
        ".mdwn",
        ".mdtxt",
        ".mdtext",
        # reStructuredText (Sphinx, Python docs)
        ".rst",
        ".rest",
        # Plain text
        ".txt",
        ".text",
        # AsciiDoc
        ".adoc",
        ".asciidoc",
        ".asc",
        # HTML/XML documentation
        ".html",
        ".htm",
        ".xhtml",
        ".xml",
        # Jupyter notebooks (executable docs)
        ".ipynb",
        # Org-mode (Emacs)  # noqa: ERA001
        ".org",
        # LaTeX (academic/technical docs)
        ".tex",
        ".latex",
        # Typst (modern typesetting)
        ".typ",
        # YAML/JSON (API docs, schemas, configs)
        ".yaml",
        ".yml",
        ".json",
        # TOML (config documentation)
        ".toml",
        # Man pages
        ".man",
        ".1",
        ".2",
        ".3",
        ".4",
        ".5",
        ".6",
        ".7",
        ".8",
        ".9",
        # Pod (Perl documentation)
        ".pod",
        # Textile
        ".textile",
        # MediaWiki
        ".wiki",
        ".mediawiki",
        # DocBook
        ".docbook",
        ".dbk",
        # DITA (Darwin Information Typing Architecture)
        ".dita",
        ".ditamap",
        # Rich Text Format
        ".rtf",
        # GraphQL schema (API docs)
        ".graphql",
        ".gql",
        # OpenAPI/Swagger specs
        ".openapi",
        # Protocol Buffers (API docs)
        ".proto",
    }
)


class GitSyncError(RuntimeError):
    """Raised when git operations fail during synchronization."""


@dataclass(slots=True)
class GitSourceConfig:
    """Configuration for cloning and exporting a git repository subtree.

    Attributes:
        repo_url: Git repository URL (https or ssh).
        branch: Branch to checkout (default: "main").
        subpaths: Specific paths within the repo to export.
        strip_prefix: Path prefix to remove from exported file paths.
        auth_token_env: Environment variable name containing auth token.
        shallow_clone: Use shallow clone for faster initial sync.
        include_extensions: File extensions to include. Defaults to
            DOCUMENTATION_EXTENSIONS if None. Pass empty frozenset to
            include all files.
    """

    repo_url: str
    branch: str = "main"
    subpaths: Sequence[str] | None = None
    strip_prefix: str | None = None
    auth_token_env: str | None = None
    shallow_clone: bool = True
    include_extensions: frozenset[str] | None = None


@dataclass(slots=True)
class GitSyncResult:
    """Summary data emitted after a synchronization cycle."""

    commit_id: str
    files_copied: int
    duration_seconds: float
    repo_updated: bool
    export_path: Path
    warnings: list[str]


class GitRepoSyncer:
    """Clones or updates a repository, then exports selected paths into storage."""

    def __init__(
        self,
        config: GitSourceConfig,
        repo_path: Path | str,
        export_path: Path | str,
        env_loader: Callable[[str], str | None] | None = None,
        logger_instance: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.repo_path = Path(repo_path)
        self.export_path = Path(export_path)
        self.repo_parent = self.repo_path.parent
        self._env_loader = env_loader or os.getenv
        self._lock = asyncio.Lock()
        self._logger = logger_instance or logger
        self._askpass_script: Path | None = None
        self._token_cache: str | None = None

        self._normalized_subpaths = self._normalize_subpaths(config.subpaths or [])
        if not self._normalized_subpaths:
            raise GitSyncError("At least one subpath must be provided for git sync")
        self._strip_prefix = self._normalize_optional_path(config.strip_prefix)

        # Resolve extension filter: None -> use defaults, empty set -> include all
        if config.include_extensions is None:
            self._include_extensions: frozenset[str] | None = DOCUMENTATION_EXTENSIONS
        else:
            self._include_extensions = config.include_extensions or None

    async def sync(self) -> GitSyncResult:
        """Synchronize the repository and export the requested paths."""

        async with self._lock:
            start = perf_counter()
            repo_updated = await self._prepare_repository()
            await self._configure_sparse_checkout()
            commit_id = await self._rev_parse("HEAD")
            files_copied, warnings = await self._export_subpaths()
            duration = perf_counter() - start
            self._logger.info(
                "Git sync complete: commit=%s files=%s duration=%.2fs updated=%s",
                commit_id,
                files_copied,
                duration,
                repo_updated,
            )
            return GitSyncResult(
                commit_id=commit_id,
                files_copied=files_copied,
                duration_seconds=duration,
                repo_updated=repo_updated,
                export_path=self.export_path,
                warnings=warnings,
            )

    async def _prepare_repository(self) -> bool:
        """Ensure repository exists locally and is reset to the requested branch."""

        repo_exists = (self.repo_path / ".git").exists()
        self.repo_parent.mkdir(parents=True, exist_ok=True)

        if not repo_exists:
            await self._clone_repository()
            return True

        before = await self._rev_parse("HEAD")
        await self._run_git("fetch", "--depth=1", "origin", self.config.branch)
        await self._run_git("checkout", self.config.branch)
        await self._run_git("reset", "--hard", f"origin/{self.config.branch}")
        await self._run_git("clean", "-fdx")
        after = await self._rev_parse("HEAD")
        return before != after

    async def _clone_repository(self) -> None:
        """Clone the configured repository into the working directory."""

        if self.repo_path.exists():
            await asyncio.to_thread(shutil.rmtree, self.repo_path)

        args: list[str] = ["clone"]
        if self.config.shallow_clone:
            args += ["--depth", "1", "--filter=blob:none", "--single-branch"]
        args.append("--sparse")
        args += ["--branch", self.config.branch, self.config.repo_url, str(self.repo_path)]

        await self._run_git(*args, use_repo=False, cwd=self.repo_parent)

    async def _configure_sparse_checkout(self) -> None:
        """Configure sparse checkout to limit working tree to configured subpaths."""

        await self._run_git("config", "core.sparseCheckout", "true")
        await self._run_git("sparse-checkout", "set", *self._normalized_subpaths)

    async def _export_subpaths(self) -> tuple[int, list[str]]:
        """Copy selected files into the export directory (atomically)."""

        staging_dir = self.export_path.parent / f".{self.export_path.name}.git-staging"

        def _copy() -> tuple[int, list[str]]:
            file_count = 0
            warnings: list[str] = []

            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            staging_dir.mkdir(parents=True, exist_ok=True)

            for subpath in self._normalized_subpaths:
                source = self._subpath_to_fs(subpath)
                if not source.exists():
                    warning = f"Subpath '{subpath}' not found in repository"
                    self._logger.warning(warning)
                    warnings.append(warning)
                    continue

                for item in source.rglob("*"):
                    if not item.is_file():
                        continue
                    # Filter by extension if configured (None means include all)
                    if self._include_extensions is not None:
                        if item.suffix.lower() not in self._include_extensions:
                            continue
                    rel = item.relative_to(self.repo_path)
                    stripped = self._apply_strip_prefix(rel)
                    dest = staging_dir / stripped
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)
                    file_count += 1

            if self.export_path.exists():
                shutil.rmtree(self.export_path)
            staging_dir.rename(self.export_path)
            return file_count, warnings

        return await asyncio.to_thread(_copy)

    def _apply_strip_prefix(self, relative_path: Path) -> Path:
        """Strip configured prefix from a path if present."""

        if not self._strip_prefix:
            return relative_path

        pure = PurePosixPath("/".join(relative_path.parts))
        try:
            stripped = pure.relative_to(self._strip_prefix)
            return Path(*stripped.parts) if stripped.parts else Path()
        except ValueError:
            return Path(*pure.parts)

    async def _rev_parse(self, ref: str) -> str:
        return (await self._run_git("rev-parse", ref)).strip()

    def _subpath_to_fs(self, subpath: str) -> Path:
        return self.repo_path.joinpath(*PurePosixPath(subpath).parts)

    def _normalize_subpaths(self, raw_paths: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in raw_paths:
            candidate = self._normalize_optional_path(raw)
            if candidate is None:
                continue
            posix_value = candidate.as_posix()
            if posix_value not in seen:
                seen.add(posix_value)
                normalized.append(posix_value)
        return normalized

    def _normalize_optional_path(self, raw: str | None) -> PurePosixPath | None:
        if not raw:
            return None
        trimmed = raw.strip()
        if not trimmed:
            return None
        candidate = PurePosixPath(trimmed)
        if ".." in candidate.parts:
            raise GitSyncError(f"Path '{raw}' cannot traverse outside repository")
        parts = [part for part in candidate.parts if part not in ("", ".")]
        if not parts:
            return None
        return PurePosixPath("/".join(parts))

    async def _run_git(self, *args: str, use_repo: bool = True, cwd: Path | None = None) -> str:
        cmd = ["git"] + [arg for arg in args if arg]
        working_dir = cwd or (self.repo_path if use_repo else self.repo_parent)
        env = self._build_git_env()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(working_dir), env=env, stdout=PIPE, stderr=PIPE
            )
        except FileNotFoundError as err:
            raise GitSyncError("git executable not found") from err

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            stderr_text = stderr.decode().strip()
            stdout_text = stdout.decode().strip()
            detail = stderr_text or stdout_text or "unknown error"
            raise GitSyncError(f"git command failed ({' '.join(cmd)}): {detail}")

        return stdout.decode()

    def _build_git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        token = self._resolve_token()
        if token:
            if self._askpass_script is None:
                self._askpass_script = self.repo_parent / ".git-sync-askpass.sh"
                self._askpass_script.write_text('#!/bin/sh\nprintf "%s" "$GIT_SYNC_TOKEN"\n', encoding="utf-8")
                self._askpass_script.chmod(0o700)
            env["GIT_ASKPASS"] = str(self._askpass_script)
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_SYNC_TOKEN"] = token
        return env

    def _resolve_token(self) -> str | None:
        if not self.config.auth_token_env:
            return None
        if self._token_cache is not None:
            return self._token_cache
        token = self._env_loader(self.config.auth_token_env)
        if not token:
            raise GitSyncError(
                f"Environment variable '{self.config.auth_token_env}' is not set but auth_token_env was provided"
            )
        self._token_cache = token
        return token
