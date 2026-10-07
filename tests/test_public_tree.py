"""Public-source guards inspect Git bytes even when ignored or locally replaced."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def commit(self, message="Synthetic fixture"):
        self.git("add", "-A")
        self.git("commit", "-qm", message)

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

    def test_history_finds_supported_secret_deleted_by_later_commit(self):
        self.repository()
        value = "gh" + "p_" + "c" * 32
        self.write("notes.txt", value + "\n")
        self.commit()
        self.write("notes.txt", "Clean replacement\n")
        self.commit()
        self.assertEqual(scan(self.root, "tracked")[1], [])
        _, findings = scan(self.root, "history")
        self.assertTrue(any("notes.txt [history " in row and "likely API token" in row
                            for row in findings))
        self.assertNotIn(value, "\n".join(findings))

    def test_history_scans_other_branches_and_every_sensitive_path(self):
        self.repository()
        self.write("README.md", "Shared public bytes\n")
        self.commit()
        original = self.git("branch", "--show-current").decode().strip()
        self.git("checkout", "-qb", "fixture-side-branch")
        # The same blob at a different path must retain that path's privacy check.
        self.write("credentials.json", "Shared public bytes\n")
        value = "github_" + "pat_" + "d" * 32
        self.write("notes.txt", value + "\n")
        self.commit()
        self.git("checkout", "-q", original)
        self.assertEqual(scan(self.root, "tracked")[1], [])
        _, findings = scan(self.root, "history")
        self.assertTrue(any("credentials.json [history " in row and "sensitive" in row
                            for row in findings))
        self.assertTrue(any("likely API token" in row for row in findings))
        self.assertNotIn(value, "\n".join(findings))

    def test_history_also_checks_commit_messages(self):
        self.repository()
        self.write("README.md", "Public source\n")
        value = "gh" + "p_" + "e" * 32
        self.commit("Synthetic note " + value)
        self.assertEqual(scan(self.root, "tracked")[1], [])
        _, findings = scan(self.root, "history")
        self.assertTrue(any(row.startswith("commit ") and "likely API token" in row
                            for row in findings))
        self.assertNotIn(value, "\n".join(findings))

    def test_history_preserves_multiple_reviewed_asset_versions(self):
        self.repository()
        old = b"\0synthetic older image bytes"
        new = b"\0synthetic newer image bytes"
        self.write("picture.png", old)
        self.commit()
        self.write("picture.png", new)
        self.commit()
        reviewed = {"picture.png": {hashlib.sha256(old).hexdigest(),
                                    hashlib.sha256(new).hexdigest()}}
        with patch("scripts.check_public_tree.REVIEWED_ASSETS", reviewed):
            self.assertEqual(scan(self.root, "history")[1], [])
            self.write("picture.png", b"\0unreviewed replacement")
            self.assertTrue(any("reviewed asset hash changed" in row
                                for row in scan(self.root)[1]))

    def test_literal_credentials_are_reported_without_values(self):
        fields = ["pass" + "word", "API" + "_KEY", "client" + "Secret", "access" + "Token"]
        value = "audit-" + "private-" + "probe"
        bodies = [field + ' = "' + value + '"\n' for field in fields]
        bodies.extend([
            '"' + fields[0] + '": "' + value + '"\n',
            fields[1] + "=" + value + "\n",
            fields[0] + ' = "abc"\n',
        ])
        for number, body in enumerate(bodies):
            self.write(f"settings-{number}.toml", body)
        self.write("settings.py", fields[1] + ' = "' + value + '"\n')
        _, findings = scan(self.root)
        self.assertEqual(sum("literal credential assignment" in row for row in findings),
                         len(bodies) + 1)
        self.assertNotIn(value, "\n".join(findings))

    def test_named_placeholders_env_lookups_and_code_expressions_are_allowed(self):
        field = "API" + "_KEY"
        placeholders = ["${PROVIDER_KEY}", "$PROVIDER_KEY", "%PROVIDER_KEY%",
                        "<set locally>", "YOUR_KEY_HERE", "fixture-token",
                        "synthetic-password", "{{ secrets.PROVIDER_KEY }}", "env:PROVIDER_KEY"]
        self.write("settings.toml", "\n".join(field + ' = "' + value + '"'
                                              for value in placeholders))
        token = "to" + "ken"
        self.write("settings.py", "\n".join([
            field + ' = os.environ["PROVIDER_KEY"]',
            token + ' = value_from_environment',
            token + ' = "gh" + "p_" + "a" * 32',
            'headers = {"X-CSRF-Token": csrf_value}',
            'headers = {"X-CSRF-Token": "wrong"}',
        ]))
        self.assertEqual(scan(self.root)[1], [])

    def test_size_limits_fail_closed_for_working_and_git_bytes(self):
        self.repository()
        self.write("notes.txt", "Content larger than this test's reduced budget\n")
        self.commit()
        with patch("scripts.check_public_tree.MAX_FILE_BYTES", 8):
            for mode in ("working", "staged", "tracked", "history"):
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    scan(self.root, mode)

    def test_unreadable_root_or_subdirectory_cannot_pass_an_incomplete_scan(self):
        self.write("README.md", "Visible public source\n")
        self.write("hidden-source/notes.txt", "Another file needing inspection\n")
        original = os.scandir
        for denied in (self.root, self.root / "hidden-source"):
            def enumerate_directory(path, denied_directory=denied):
                if Path(path) == denied_directory:
                    raise PermissionError("Synthetic inaccessible directory")
                return original(path)

            with (
                self.subTest(denied=denied.name),
                patch("scripts.check_public_tree.os.scandir", side_effect=enumerate_directory),
                self.assertRaises(PermissionError),
            ):
                scan(self.root)

    def test_shallow_history_fails_closed_instead_of_claiming_full_scan(self):
        self.repository()
        self.write("README.md", "Initial public source\n")
        self.commit()
        self.write("README.md", "Later public source\n")
        self.commit()
        shallow = self.root.parent / "shallow clone"
        subprocess.run(["git", "clone", "-q", "--depth", "1", self.root.as_uri(), str(shallow)],
                       capture_output=True, check=True)
        self.assertEqual(scan(shallow, "tracked")[1], [])
        with self.assertRaises(ValueError):
            scan(shallow, "history")


if __name__ == "__main__":
    unittest.main()
