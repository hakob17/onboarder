import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from ..config import MAX_FILE_MB, MAX_FILES, MAX_UNCOMPRESSED_MB
from .languages import SKIP_DIRS


class IngestError(Exception):
    pass


MANIFESTS = (
    "pom.xml", "build.gradle", "build.gradle.kts", "package.json", "go.mod",
    "composer.json", "requirements.txt", "pyproject.toml", "pubspec.yaml",
    "Package.swift", "Gemfile",
)

_SYMLINK_MODE = 0o120000


def _safe_member_path(name: str) -> PurePosixPath | None:
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        return None
    if any(part in SKIP_DIRS for part in p.parts):
        return None
    return p


def extract_zip(zip_path: Path, dest: Path) -> int:
    """Safely extract a zip (zip-slip, symlink, bomb guards). Returns file count."""
    dest.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    count = 0
    max_total = MAX_UNCOMPRESSED_MB * 1024 * 1024
    max_file = MAX_FILE_MB * 1024 * 1024
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise IngestError(f"not a valid zip file: {e}") from e
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE:
                continue
            member = _safe_member_path(info.filename)
            if member is None:
                continue
            if info.file_size > max_file:
                continue
            count += 1
            if count > MAX_FILES:
                raise IngestError(f"zip contains more than {MAX_FILES} files")
            total_bytes += info.file_size
            if total_bytes > max_total:
                raise IngestError(f"zip expands to more than {MAX_UNCOMPRESSED_MB} MB")
            target = dest / Path(*member.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                remaining = max_file
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise IngestError("zip member exceeds declared size")
                    dst.write(chunk)
    if count == 0:
        raise IngestError("zip contains no extractable files")
    return count


def _read(path: Path, limit: int = 512 * 1024) -> str:
    try:
        return path.read_text("utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _classify_root(root: Path) -> str:
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        text = _read(root / "pom.xml") + _read(root / "build.gradle") + _read(root / "build.gradle.kts")
        if "com.android" in text or list(root.glob("**/AndroidManifest.xml"))[:1]:
            return "android"
        if "springframework" in text or "spring-boot" in text:
            return "spring"
        return "java"
    if (root / "package.json").exists():
        try:
            pkg = json.loads(_read(root / "package.json") or "{}")
        except ValueError:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "@nestjs/core" in deps:
            return "nestjs"
        if "react-native" in deps:
            return "react-native"
        if "express" in deps:
            return "express"
        if "next" in deps:
            return "nextjs"
        return "node"
    if (root / "go.mod").exists():
        return "go"
    if (root / "composer.json").exists():
        return "laravel" if "laravel/framework" in _read(root / "composer.json") else "php"
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        text = _read(root / "requirements.txt") + _read(root / "pyproject.toml")
        for fw in ("django", "fastapi", "flask"):
            if re.search(rf"\b{fw}\b", text, re.I):
                return fw
        return "python"
    if (root / "pubspec.yaml").exists():
        return "flutter"
    if (root / "Package.swift").exists() or list(root.glob("*.xcodeproj"))[:1]:
        return "ios"
    if (root / "Gemfile").exists():
        return "rails" if "rails" in _read(root / "Gemfile") else "ruby"
    if list(root.glob("*.tf"))[:1] or (root / "template.yaml").exists() or (root / "template.yml").exists():
        return "terraform"
    return "unknown"


def detect_projects(extract_root: Path, max_depth: int = 4) -> list[tuple[str, str]]:
    """Find project roots inside an extracted tree.

    Returns a list of (relative_root, stack). A monorepo with several build
    manifests yields one entry per manifest root; otherwise a single entry.
    """
    manifest_dirs: list[Path] = []
    for path in sorted(extract_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(extract_root)
        if len(rel.parts) > max_depth + 1:
            continue
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in MANIFESTS:
            manifest_dirs.append(path.parent)
    roots: list[Path] = []
    for d in sorted(set(manifest_dirs), key=lambda p: len(p.parts)):
        if not any(other != d and other in d.parents for other in roots):
            roots.append(d)
    if not roots:
        return [(".", "unknown")]
    return [(str(r.relative_to(extract_root)) or ".", _classify_root(r)) for r in roots]
