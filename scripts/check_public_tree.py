"""Check source or actual Git blobs for private data; never print matched values."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git", ".venv", "__pycache__", "build", "dist", ".mypy_cache", ".ruff_cache",
    ".demo-data", ".home-data",
}
# Reviewed artifacts only. A changed binary must have its provenance reviewed again.
REVIEWED_ASSETS = {
    "home/web/town-dusk.webp": "75917de1078cdbba6f17ea1c620517c898fe217ff16863c8075fcc759f21e226",
    "home/web/residents.webp": "4a4573411ccc3c0e1b879fda18140acfea449edb1a7aa575f6f88b7c8d8fbe71",
    "home/web/town-terrain.webp": "b3801a4e82066b909ff83fdd744303b288dca96836482b37f8a0783105251afe",
    "home/web/houses.webp": "eb777b71fef42c478e49276ce456151e1e07b504883088a956afa9975ab11742",
    "home/web/fraunces-500.ttf": "0c2fad18ed36cc400041f1e281ee79954a329b345caffc38dfaa3bb8bcef57de",
    "home/web/manrope-400.ttf": "a13d9b41b0a471ce58f0e46d377fa3cc76615e4632c3b15eb397caadf7a13f0a",
    "home/web/manrope-600.ttf": "6bad1a774228464cc88b8b0271555b266f7a3c64a7bedf15e165fdab4f6ac0ce",
    "docs/images/town-demo.jpg": "ed36ca3b0191b949d96a2cb7285d498b44853efcfa360b51e1843664b67432d6",
}
PATTERNS = {
    "personal profile path": re.compile(
        r"(?:[A-Z]:[/\\]+Users[/\\]+|(?<![A-Za-z0-9_.])/(?:Users|home)/[A-Za-z0-9._-]+/)",
        re.IGNORECASE,
    ),
    "likely API token": re.compile(
        r"\b(?:sk-(?:ant-|proj-)?|gh[opusr]_|github_pat_|glpat-|xox[baprs]-)[A-Za-z0-9_-]{16,}"
    ),
    "private key material": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "AWS credential": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Google credential": re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    "bearer credential": re.compile(r"\bBearer\s+[A-Za-z0-9_.-]{20,}", re.IGNORECASE),
    "JWT credential": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
    "credential in URL": re.compile(
        r"\b(?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
        r"[^/\s:@]+:[^@\s/]+@", re.IGNORECASE
    ),
    "private provider auth file": re.compile(r"(?:auth\.json|credentials\.json)\s*[:=]\s*[{\[]"),
}
SENSITIVE_NAME = re.compile(
    r"(?:^|/)(?:\.env[^/]*|local-config[^/]*|\.?auth\.json|\.?credentials\.json|"
    r"\.?secrets\.json|id_rsa[^/]*|id_ed25519[^/]*|\.claude|\.codex|\.impeccable|"
    r"data|\.demo-data|\.home-data|sessions|logs|history(?:\.[^/]*)?)(?:/|$)|"
    r"(?:^|/)evidence/private(?:/|$)|"
    r"\.(?:pem|key|p12|pfx|keystore|sqlite[^/]*|db(?:-[^/]*)?|log|pyc|pyo)$",
    re.IGNORECASE,
)
BINARY_SUFFIXES = {
    ".bin", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ttf", ".woff", ".woff2",
    ".mp4", ".mp3", ".wav", ".pdf", ".zip", ".gz", ".exe", ".dll",
}


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("Git could not read the requested source tree")
    return result.stdout


def _git_files(root: Path, mode: str) -> list[tuple[str, bytes | None]]:
    """Read the actual index or HEAD; working-copy edits cannot hide their content."""
    raw = _git(root, "ls-files", "--stage", "-z") if mode == "staged" else _git(
        root, "ls-tree", "-rz", "--full-tree", "HEAD"
    )
    entries: list[tuple[str, str | None]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        first, second, third = header.decode("ascii").split()
        name = path.decode("utf-8")
        regular = first in {"100644", "100755"}
        if mode == "staged":
            object_id = second if regular and third == "0" else None
        else:
            object_id = third if regular and second == "blob" else None
        entries.append((name, object_id))
    object_ids = [oid for _, oid in entries if oid is not None]
    stream = io.BytesIO(_git(
        root, "cat-file", "--batch", data=("\n".join(object_ids) + "\n").encode("ascii")
    )) if object_ids else io.BytesIO()
    files: list[tuple[str, bytes | None]] = []
    for name, oid in entries:
        if oid is None:
            files.append((name, None))
            continue
        actual, kind, length = stream.readline().decode("ascii").split()
        if actual != oid or kind != "blob":
            raise ValueError("Git returned an unexpected source object")
        body = stream.read(int(length))
        if len(body) != int(length) or stream.read(1) != b"\n":
            raise ValueError("Git returned an incomplete source object")
        files.append((name, body))
    if stream.read():
        raise ValueError("Git returned extra source object data")
    return files


def _working_files(root: Path) -> list[tuple[str, bytes | None]]:
    """ZIP downloads need no Git installation; generated development caches are skipped."""
    files: list[tuple[str, bytes | None]] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(current) / name
            if name == ".git":
                directories.remove(name)
            elif path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                files.append((path.relative_to(root).as_posix(), None))
                directories.remove(name)
            elif name in SKIP_DIRS or name.endswith(".egg-info"):
                directories.remove(name)
        for name in filenames:
            path = Path(current) / name
            if name == ".git":
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                files.append((relative, None))
            else:
                files.append((relative, path.read_bytes()))
    return files


def scan(root: Path, mode: str = "working") -> tuple[int, list[str]]:
    files = _working_files(root) if mode == "working" else _git_files(root, mode)
    findings: list[str] = []
    for name, body in sorted(files):
        if body is None:
            findings.append(f"{name}: link, submodule or conflicted Git entry requires review")
            continue
        if SENSITIVE_NAME.search(name):
            findings.append(f"{name}: sensitive or runtime filename is not public source")
        expected_hash = REVIEWED_ASSETS.get(name)
        if expected_hash:
            if hashlib.sha256(body).hexdigest() != expected_hash:
                findings.append(f"{name}: reviewed asset hash changed; review provenance")
            continue
        if Path(name).suffix.lower() in BINARY_SUFFIXES or b"\0" in body:
            findings.append(f"{name}: unreviewed binary")
            continue
        try:
            content = body.decode("utf-8")
        except UnicodeError:
            findings.append(f"{name}: unreviewed binary")
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{name}:{line_number}: {label}")
    return len(files), findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true", help="scan actual Git index blobs")
    modes.add_argument("--tracked", action="store_true", help="scan actual committed HEAD blobs")
    args = parser.parse_args(argv)
    mode = "staged" if args.staged else "tracked" if args.tracked else "working"
    try:
        inspected, findings = scan(ROOT, mode)
    except (OSError, ValueError, UnicodeError):
        print("FAIL: requested source tree could not be inspected")
        return 1
    if findings:
        print("\n".join(findings))
        return 1
    print(f"PASS: {inspected} {mode} source files; manual exact-tree review still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
