"""Shared utilities, constants, and base exception for gitcode-workflow scripts."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── path classification constants ──────────────────────────────────────
DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
SOURCE_SUFFIXES = {
    ".java", ".kt", ".py", ".go", ".js", ".jsx", ".ts", ".tsx",
    ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs",
}
SCOPE_SKIP_PARTS = {
    "src", "main", "test", "tests", "java", "kotlin", "python", "go",
    "pkg", "cmd", "internal", "app", "apps", "service", "services",
    "module", "modules", "backend", "frontend", "server", "client",
    "web", "resources", "static", "templates", "docs", "doc",
    "com", "org", "net", "io", "github", "gitlab",
}

# ── commit-message constants ────────────────────────────────────────────
VALID_COMMIT_TYPES = {"feat", "fix", "docs", "style", "refactor", "perf", "test", "chore", "revert"}
COMMIT_MESSAGE_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|chore|revert)(\([^)]+\))?: (.+)$"
)
REVIEW_MANIFEST_FILENAME = "gitcode-workflow-review.json"


class BootstrapError(RuntimeError):
    """Non-recoverable error during bootstrap/publish workflows."""
    pass


def deep_copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def read_json_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def expand_path(value: str) -> str:
    return str(Path(value).expanduser())


def run(
    cmd: Sequence[str], *, cwd: Optional[Path] = None, check: bool = True
) -> "CommandResult":
    proc = subprocess.run(
        list(cmd), cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, check=False,
    )
    result = CommandResult(proc.stdout.rstrip("\n"), proc.stderr.rstrip("\n"), proc.returncode)
    if check and proc.returncode != 0:
        raise BootstrapError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def file_is_text(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except (FileNotFoundError, OSError):
        return False
    return b"\x00" not in chunk


def truncate_text(
    text: str, max_lines: int, max_chars: int
) -> Tuple[str, bool]:
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    joined = "\n".join(lines)
    if len(joined) > max_chars:
        joined = joined[:max_chars]
        if "\n" in joined:
            joined = joined.rsplit("\n", 1)[0]
        truncated = True
    if truncated:
        joined = joined.rstrip("\n") + "\n...[truncated]"
    return joined, truncated


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def log_info(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[gitcode-workflow][{timestamp}] {message}", file=sys.stderr)


def ensure_tool(name: str, error_message: Optional[str] = None) -> None:
    if shutil.which(name) is None:
        raise BootstrapError(error_message or f"{name} is not installed or not available in PATH")


# ── path classification helpers ────────────────────────────────────────

def is_doc_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        pure.suffix.lower() in DOC_SUFFIXES
        or pure.name.lower().startswith("readme")
        or "docs" in {part.lower() for part in pure.parts}
    )


def is_test_path(path: str) -> bool:
    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    if any(token in lower.split("/") for token in ["test", "tests", "__tests__"]):
        return True
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.js")
    )


def is_source_path(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES


def is_build_or_config_path(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    build_names = {
        "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
        "pyproject.toml", "setup.py", "poetry.lock", "go.mod", "go.sum",
        "dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "makefile", ".gitignore", ".gitattributes",
    }
    if name in build_names:
        return True
    first = pure.parts[0].lower() if pure.parts else ""
    return first in {".github", "ci", "scripts", "deploy", "ops"}


def infer_scope_from_path(path: str) -> str:
    pure = PurePosixPath(path)
    name = pure.name.lower()
    # well-known config/build files → scope "deps"
    if name in {
        "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
        "pyproject.toml", "setup.py", "poetry.lock", "go.mod", "go.sum",
        "package.json", "package-lock.json", "pnpm-lock.yaml",
    }:
        return "deps"
    if name in {"dockerfile", "makefile", ".gitignore", ".gitattributes"}:
        return "repo"
    parts: List[str] = []
    for part in pure.parts[:-1]:
        lower = part.lower()
        if lower in SCOPE_SKIP_PARTS or lower.startswith("."):
            continue
        parts.append(lower)
    if parts:
        scope = re.sub(r"[^a-z0-9-]+", "-", parts[-1]).strip("-")
        if scope:
            return scope
    stem = re.sub(r"[^a-z0-9-]+", "-", pure.stem.lower()).strip("-")
    if stem in {"readme", "license", "git-commit", "main", "index"}:
        return "global"
    return stem or "global"


# ── dataclass ──────────────────────────────────────────────────────────

class CommandResult:
    __slots__ = ("stdout", "stderr", "returncode")
    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
