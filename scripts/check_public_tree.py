"""Check source or actual Git blobs for private data; never print matched values."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import subprocess
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git", ".venv", "__pycache__", "build", "dist", ".mypy_cache", ".ruff_cache",
    ".demo-data", ".home-data",
}
# Retain older reviewed digests when replacing an asset: history stays inspectable.
# A new digest requires provenance review before adding it to this allowlist.
REVIEWED_ASSETS = {
    "home/web/town-dusk.webp": {"75917de1078cdbba6f17ea1c620517c898fe217ff16863c8075fcc759f21e226"},
    "home/web/residents.webp": {"4a4573411ccc3c0e1b879fda18140acfea449edb1a7aa575f6f88b7c8d8fbe71"},
    "home/web/town-terrain.webp": {"b3801a4e82066b909ff83fdd744303b288dca96836482b37f8a0783105251afe"},
    "home/web/houses.webp": {"eb777b71fef42c478e49276ce456151e1e07b504883088a956afa9975ab11742"},
    "home/web/town-props.webp": {"5db01f5d76f1c8d00c59285ec9faf3017afd80d28bd5244b9e695b22e95ba84e"},
    "home/web/fraunces-500.ttf": {"0c2fad18ed36cc400041f1e281ee79954a329b345caffc38dfaa3bb8bcef57de"},
    "home/web/manrope-400.ttf": {"a13d9b41b0a471ce58f0e46d377fa3cc76615e4632c3b15eb397caadf7a13f0a"},
    "home/web/manrope-600.ttf": {"6bad1a774228464cc88b8b0271555b266f7a3c64a7bedf15e165fdab4f6ac0ce"},
    "docs/images/town-demo.jpg": {
        "ed36ca3b0191b949d96a2cb7285d498b44853efcfa360b51e1843664b67432d6",
        "b799ed93f3d0426cfd52f94ee6f8596a5f68843e000d643ac06df95c9027f20c",
        "6638d376620db0bb420c333f397d5acc67375c3ee18b24ce36a35f1c690dcd64",
    },
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
MAX_FILES = 100_000
MAX_COMMITS = 10_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
CREDENTIAL_ASSIGNMENT = re.compile(
    r'''(?ix)(?<![a-z0-9_"']) (?P<key_quote>["']?)
    (?P<key>(?:[a-z0-9]+[_-])*(?:password|passwd|passphrase|secret|token|api[_-]?key)
       |(?:client|access|refresh|auth|bearer)[_-]?(?:secret|token)) (?P=key_quote)
    \s*[:=]\s*
    (?: "(?P<double>[^"\r\n]+)" | '(?P<single>[^'\r\n]+)'
      | (?P<bare>[a-z0-9_+/=.:-]+)) (?=\s*(?:[,}\];)]|\#|$))
    '''
)
PLACEHOLDER_VALUE = re.compile(
    r'''(?ix)(?:
    none|null|true|false|unset|not[_-]set|redacted|\[redacted\]|placeholder
    |(?:your|example|dummy|fixture|replace|insert)[_-][a-z0-9_-]+
    |(?:synthetic|test)[_-](?:password|passwd|secret|token|key|credential)(?:[_-]only)?
    |<[^<>\r\n]+>|\$\{[a-z_][a-z0-9_]*\}|\$[a-z_][a-z0-9_]*|%[a-z_][a-z0-9_]*%
    |\{\{\s*(?:secrets|env)\.[a-z_][a-z0-9_]*\s*\}\}
    |env:[a-z_][a-z0-9_]*
    )'''
)


class SourceFile(NamedTuple):
    name: str
    body: bytes | None
    origin: str = ""


def _git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args], input=data, capture_output=True,
            check=False, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Git inspection exceeded its time limit") from None
    if result.returncode:
        raise ValueError("Git could not read the requested source tree")
    if len(result.stdout) > MAX_TOTAL_BYTES:
        raise ValueError("Git inspection exceeded the review limit")
    return result.stdout


def _git_entries(root: Path, mode: str, revision: str = "HEAD") -> list[tuple[str, str | None]]:
    raw = _git(root, "ls-files", "--stage", "-z") if mode == "staged" else _git(
        root, "ls-tree", "-rz", "--full-tree", revision
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
        if len(entries) > MAX_FILES:
            raise ValueError("Source tree exceeds the review limit")
    return entries


def _git_objects(root: Path, object_ids: list[str]) -> dict[str, bytes]:
    """Check object sizes before loading content. Never truncate an inspected object."""
    if len(object_ids) > MAX_FILES:
        raise ValueError("Source tree exceeds the review limit")
    if not object_ids:
        return {}
    request = ("\n".join(object_ids) + "\n").encode("ascii")
    metadata = _git(root, "cat-file", "--batch-check", data=request).splitlines()
    if len(metadata) != len(object_ids):
        raise ValueError("Git returned incomplete source metadata")
    total = 0
    for oid, line in zip(object_ids, metadata, strict=True):
        actual, kind, length = line.decode("ascii").split()
        size = int(length)
        total += size
        if actual != oid or kind not in {"blob", "commit"} or size < 0:
            raise ValueError("Git returned unexpected source metadata")
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Source content exceeds the review limit")
    stream = io.BytesIO(_git(
        root, "cat-file", "--batch", data=request
    ))
    objects: dict[str, bytes] = {}
    for oid in object_ids:
        actual, kind, length = stream.readline().decode("ascii").split()
        if actual != oid or kind not in {"blob", "commit"}:
            raise ValueError("Git returned an unexpected source object")
        body = stream.read(int(length))
        if len(body) != int(length) or stream.read(1) != b"\n":
            raise ValueError("Git returned an incomplete source object")
        objects[oid] = body
    if stream.read():
        raise ValueError("Git returned extra source object data")
    return objects


def _git_files(root: Path, mode: str) -> list[SourceFile]:
    """Read actual index/HEAD blobs, or every reachable commit and path version."""
    if mode != "history":
        entries = [(name, oid, "") for name, oid in _git_entries(root, mode)]
    else:
        if _git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
            raise ValueError("History inspection requires a complete Git clone")
        commits = _git(root, "rev-list", "--all", f"--max-count={MAX_COMMITS + 1}")
        revisions = commits.decode("ascii").splitlines()
        if len(revisions) > MAX_COMMITS:
            raise ValueError("Git history exceeds the review limit")
        entries = []
        seen: set[tuple[str, str | None]] = set()
        for revision in revisions:
            entries.append((f"commit {revision[:12]} metadata", revision, ""))
            for name, oid in _git_entries(root, "tracked", revision):
                if (name, oid) not in seen:
                    seen.add((name, oid))
                    entries.append((name, oid, f" [history {revision[:12]}]"))
            if len(entries) > MAX_FILES:
                raise ValueError("Git history exceeds the review limit")
    objects = _git_objects(root, list(dict.fromkeys(oid for _, oid, _ in entries if oid)))
    return [SourceFile(name, objects[oid] if oid else None, origin)
            for name, oid, origin in entries]


def _working_files(root: Path) -> list[SourceFile]:
    """ZIP downloads need no Git installation; generated development caches are skipped."""
    def reject_unreadable_directory(error: OSError) -> None:
        # os.walk otherwise skips failed directory enumeration silently.
        raise error

    files: list[SourceFile] = []
    total = 0
    for current, directories, filenames in os.walk(
            root, followlinks=False, onerror=reject_unreadable_directory):
        for name in list(directories):
            path = Path(current) / name
            if name == ".git":
                directories.remove(name)
            elif path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                files.append(SourceFile(path.relative_to(root).as_posix(), None))
                directories.remove(name)
            elif name in SKIP_DIRS or name.endswith(".egg-info"):
                directories.remove(name)
        for name in filenames:
            path = Path(current) / name
            if name == ".git":
                continue
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                files.append(SourceFile(relative, None))
            else:
                size = path.stat().st_size
                total += size
                if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("Source content exceeds the review limit")
                body = path.read_bytes()
                if len(body) != size:
                    raise ValueError("Source changed during inspection")
                files.append(SourceFile(relative, body))
            if len(files) > MAX_FILES:
                raise ValueError("Source tree exceeds the review limit")
    return files


def scan(root: Path, mode: str = "working") -> tuple[int, list[str]]:
    files = _working_files(root) if mode == "working" else _git_files(root, mode)
    findings: list[str] = []
    for name, body, origin in sorted(files, key=lambda entry: (entry.name, entry.origin)):
        location = name + origin
        if body is None:
            findings.append(f"{location}: link, submodule or conflicted Git entry requires review")
            continue
        if SENSITIVE_NAME.search(name):
            findings.append(f"{location}: sensitive or runtime filename is not public source")
        expected_hashes = REVIEWED_ASSETS.get(name)
        if expected_hashes:
            if hashlib.sha256(body).hexdigest() not in expected_hashes:
                findings.append(f"{location}: reviewed asset hash changed; review provenance")
            continue
        if Path(name).suffix.lower() in BINARY_SUFFIXES or b"\0" in body:
            findings.append(f"{location}: unreviewed binary")
            continue
        try:
            content = body.decode("utf-8")
        except UnicodeError:
            findings.append(f"{location}: unreviewed binary")
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{location}:{line_number}: {label}")
            for match in CREDENTIAL_ASSIGNMENT.finditer(line):
                # Bare names in code are expressions, not declared secret values.
                if match.group("bare") and Path(name).suffix.lower() in {".py", ".js"}:
                    continue
                value = next(match.group(group) for group in ("double", "single", "bare")
                             if match.group(group) is not None).strip()
                # Short invalid-token fixtures are not plausible access credentials.
                if match.group("key").lower().endswith("token") and len(value) < 8:
                    continue
                if not PLACEHOLDER_VALUE.fullmatch(value):
                    findings.append(f"{location}:{line_number}: literal credential assignment")
    return len(files), findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true", help="scan actual Git index blobs")
    modes.add_argument("--tracked", action="store_true", help="scan actual committed HEAD blobs")
    modes.add_argument("--history", action="store_true", help="scan all reachable Git history")
    args = parser.parse_args(argv)
    mode = ("staged" if args.staged else "tracked" if args.tracked
            else "history" if args.history else "working")
    try:
        inspected, findings = scan(ROOT, mode)
    except (OSError, ValueError, UnicodeError):
        print("FAIL: requested source tree could not be inspected")
        return 1
    if findings:
        print("\n".join(findings))
        return 1
    print(f"PASS: {inspected} {mode} source entries; manual exact-tree review still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
