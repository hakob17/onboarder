import json
import os
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


def _find_shallow(root: Path, filename: str, max_depth: int = 6) -> bool:
    """True if `filename` exists under `root`, pruning SKIP_DIRS and stopping at the first
    hit. Replaces root.glob('**/'+filename), which walks node_modules/target/build in full."""
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if filename in filenames:
            return True
    return False


def _classify_root(root: Path) -> str:
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        text = _read(root / "pom.xml") + _read(root / "build.gradle") + _read(root / "build.gradle.kts")
        if "com.android" in text or _find_shallow(root, "AndroidManifest.xml"):
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


# Manifests found under these subtrees of a project belong to fixtures / sample apps /
# vendored code, not to a separate project — so they never shadow their outer root.
_FIXTURE_DIRS = {
    "src", "test", "tests", "testdata", "test-data", "fixtures", "fixture",
    "examples", "example", "samples", "sample", "spec", "specs", "__tests__",
    "e2e", "demo", "demos", "docs", "doc", "resources", "node_modules",
}


def detect_projects(extract_root: Path, max_depth: int = 4) -> list[tuple[str, str]]:
    """Find project roots inside a tree.

    Returns a list of (relative_root, stack). A folder of repos — even one with a
    top-level manifest over them (a workspace/monorepo root) — yields one entry per
    real sub-project, so each repo is analyzed with its own stack.
    """
    # Walk top-down and prune as we go: never descend into vendored/build dirs
    # (node_modules, .git, target, …) or past max_depth. rglob can't prune, so on a
    # big multi-repo folder it would enumerate the whole tree and stall the request.
    manifest_dirs: list[Path] = []
    root_depth = len(extract_root.parts)
    manifests = set(MANIFESTS)
    for dirpath, dirnames, filenames in os.walk(extract_root):
        cur = Path(dirpath)
        depth = len(cur.parts) - root_depth  # 0 at the root folder
        if depth >= max_depth:
            dirnames[:] = []  # don't descend any deeper
        else:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if manifests.intersection(filenames):
            manifest_dirs.append(cur)

    uniq = sorted(set(manifest_dirs), key=lambda p: len(p.parts))
    # 1) drop manifests nested inside a src/test/fixtures/… subtree of an outer root —
    #    those are fixtures or vendored sample apps, not separate projects.
    kept: list[Path] = []
    for d in uniq:
        shadowed = False
        for parent in kept:
            if parent == d or parent not in d.parents:
                continue
            between = d.relative_to(parent).parts
            if between and between[0] in _FIXTURE_DIRS:
                shadowed = True
                break
        if not shadowed:
            kept.append(d)
    # 2) when a dir contains 2+ inner roots it's a workspace/monorepo container: keep the
    #    inner repos and drop the container (a lone nested manifest, e.g. tooling, stays).
    roots = [d for d in kept
             if sum(1 for o in kept if o != d and d in o.parents) < 2]
    if not roots:
        return [(".", "unknown")]
    return [(str(r.relative_to(extract_root)) or ".", _classify_root(r)) for r in roots]
