"""Check declared source files for obvious private data; not a universal secret scanner."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", "data", "build", "dist", ".mypy_cache", ".ruff_cache", "mocks", "review"}
# Reviewed artifacts only. A changed binary must have its provenance reviewed again.
REVIEWED_ASSETS = {
    "home/web/town-dusk.webp": "75917de1078cdbba6f17ea1c620517c898fe217ff16863c8075fcc759f21e226",
    "home/web/residents.webp": "4a4573411ccc3c0e1b879fda18140acfea449edb1a7aa575f6f88b7c8d8fbe71",
    "home/web/town-terrain.webp": "b3801a4e82066b909ff83fdd744303b288dca96836482b37f8a0783105251afe",
    "home/web/houses.webp": "eb777b71fef42c478e49276ce456151e1e07b504883088a956afa9975ab11742",
    "home/web/fraunces-500.ttf": "0c2fad18ed36cc400041f1e281ee79954a329b345caffc38dfaa3bb8bcef57de",
    "home/web/manrope-400.ttf": "a13d9b41b0a471ce58f0e46d377fa3cc76615e4632c3b15eb397caadf7a13f0a",
    "home/web/manrope-600.ttf": "6bad1a774228464cc88b8b0271555b266f7a3c64a7bedf15e165fdab4f6ac0ce",
}
PATTERNS = {
    "personal Windows path": re.compile(r"[A-Z]:[/\\]Users[/\\]", re.IGNORECASE),
    "likely API token": re.compile(r"\b(?:sk-proj-|gho_|ghp_)[A-Za-z0-9_-]{20,}"),
    "private provider auth file": re.compile(r"(?:auth\.json|credentials\.json)\s*[:=]\s*[{\[]"),
}


def main() -> int:
    findings: list[str] = []
    inspected = 0
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.is_dir():
            continue
        if path.is_symlink():
            findings.append(f"{relative}: symbolic link requires review")
            continue
        if path.name.startswith(".env") or path.name.startswith("local-config."):
            continue  # Explicit ignored local setup is not a public candidate.
        expected_hash = REVIEWED_ASSETS.get(relative.as_posix())
        if expected_hash:
            inspected += 1
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                findings.append(f"{relative}: reviewed asset hash changed; review provenance")
            continue
        if path.suffix in {".sqlite", ".db", ".mp4", ".png", ".jpg"}:
            findings.append(f"{relative}: binary/runtime file requires explicit provenance")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            findings.append(f"{relative}: unreviewed binary")
            continue
        inspected += 1
        for line_number, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{relative}:{line_number}: {label}")
    if findings:
        print("\n".join(findings))
        return 1
    print(f"PASS: {inspected} candidate source files; manual exact-tree review still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
