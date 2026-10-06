"""Public-source guards inspect Git bytes even when ignored or locally replaced."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_public_tree import scan


class PublicTreeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "ordinary project folder"
        self.root.mkdir()

    def write(self, name: str, body: str | bytes):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body.encode() if isinstance(body, str) else body)

    def git(self, *args: str, data: bytes | None = None) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], input=data,
            capture_output=True, check=True,
        )
        return result.stdout

    def repository(self):
        if not shutil.which("git"):
            self.skipTest("Git is needed for actual index/HEAD regression cases")
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def test_downloaded_source_without_git_and_path_with_spaces(self):
        self.write("README.md", "Public getting started guide\n")
        self.write("docs/guide.md", "Public setup instructions\n")
        self.write("__pycache__/generated.pyc", b"\0generated")
        self.write(".demo-data/home.sqlite", b"\0local fixture database")
        self.write(".home-data/home.sqlite", b"\0local private database")
        count, findings = scan(self.root)
        self.assertEqual((count, findings), (2, []))
        with self.assertRaises(ValueError):
            scan(self.root, "tracked")

    def test_force_added_ignored_sensitive_files_and_directories_are_rejected(self):
        self.repository()
        self.write(".gitignore", ".env*\nlocal-config*\ndata/\n.demo-data/\n.home-data/\n")
        names = (
            ".env.fixture", "local-config.toml", "data/history.json",
            ".demo-data/notes.txt", ".home-data/notes.txt",
        )
        for name in names:
            self.write(name, "synthetic placeholder\n")
        self.git("add", "-f", ".")
        _, findings = scan(self.root, "staged")
        for name in names:
            self.assertTrue(any(row.startswith(name + ":") for row in findings))

    def test_staged_secret_cannot_be_hidden_by_clean_working_copy(self):
        self.repository()
        token = "gh" + "p_" + "a" * 32
        self.write("notes.txt", "token=" + token + "\n")
        self.git("add", "notes.txt")
        self.write("notes.txt", "clean replacement\n")
        self.assertEqual(scan(self.root)[1], [])
        _, findings = scan(self.root, "staged")
        self.assertTrue(any("likely API token" in row for row in findings))
        self.assertNotIn(token, "\n".join(findings))

    def test_tracked_reads_head_instead_of_changed_index_or_working_tree(self):
        self.repository()
        token = "github_" + "pat_" + "b" * 32
        self.write("notes.txt", "value=" + token + "\n")
        self.git("add", "notes.txt")
        self.git("commit", "-qm", "Synthetic fixture")
        self.write("notes.txt", "clean replacement\n")
        self.git("add", "notes.txt")
        self.assertEqual(scan(self.root, "staged")[1], [])
        self.assertTrue(any("likely API token" in row for row in scan(self.root, "tracked")[1]))

    def test_git_symlink_rejected_without_following_target(self):
        self.repository()
        oid = self.git("hash-object", "-w", "--stdin", data=b"private-target").decode().strip()
        entry = ("120000 " + oid + "\tlink.txt\n").encode()
        self.git("update-index", "--index-info", data=entry)
        _, findings = scan(self.root, "staged")
        self.assertEqual(len(findings), 1)
        self.assertIn("link, submodule", findings[0])

    def test_sensitive_names_private_shapes_and_binary_report_locations_only(self):
        fixtures = {
            "plain.txt": "-----BEGIN " + "PRIVATE KEY-----\n",
            "url.txt": "https://" + "example:dummy-secret@host.invalid/\n",
            "profile.txt": "C:/" + "Users/Example/private.txt\n",
            "auth.json": "{}\n",
            "history.jsonl": "{}\n",
            "picture.png": b"\x89PNG\0fixture",
        }
        for name, body in fixtures.items():
            self.write(name, body)
        _, findings = scan(self.root)
        for name in fixtures:
            self.assertTrue(any(row.startswith(name + ":") for row in findings), name)
        self.assertNotIn("dummy-secret", "\n".join(findings))
        self.assertNotIn("Example/private", "\n".join(findings))

    def test_relative_repository_module_links_are_not_personal_paths(self):
        self.write("guide.md", "[Adapters](../home/adapters/) and [browser](../home/web/)\n")
        self.assertEqual(scan(self.root)[1], [])
        self.write("absolute.txt", "See /" + "home/example/private/config\n")
        self.assertTrue(any("personal profile path" in row for row in scan(self.root)[1]))


if __name__ == "__main__":
    unittest.main()
