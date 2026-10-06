"""Local TOML and cooperating data-directory ownership boundary tests."""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from home.config import load_bindings
from home.ownership import DataOwner


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "home.toml"

    def tearDown(self):
        self.directory.cleanup()

    def write_agents(self, agents, extra=""):
        lines = [extra]
        for agent in agents:
            lines.append("[[agents]]")
            for key, value in agent.items():
                if isinstance(value, dict):
                    encoded = "{" + ", ".join(f"{k}={json.dumps(v)}" for k, v in value.items()) + "}"
                elif isinstance(value, float) and math.isnan(value):
                    encoded = "nan"
                elif value == float("inf"):
                    encoded = "inf"
                else:
                    encoded = json.dumps(value)
                lines.append(f"{key} = {encoded}")
        self.path.write_text("\n".join(lines), encoding="utf-8")

    def valid(self, **changes):
        value = {"id": "claude", "name": "Claude", "provider": "claude", "workspace": "."}
        value.update(changes)
        return value

    def reject(self, agents, extra=""):
        self.write_agents(agents, extra)
        with self.assertRaises(ValueError):
            load_bindings(self.path)

    def test_valid_minimal_config_and_relative_workspace(self):
        self.write_agents([self.valid()])
        binding = load_bindings(self.path)[0]
        self.assertEqual((binding.id, binding.provider, binding.executable, binding.timeout),
                         ("claude", "claude", "claude", 180))
        self.assertEqual(binding.workspace, self.root.resolve())

    def test_explicit_native_executable_role_and_timeout(self):
        self.write_agents([self.valid(executable="owned-cli", role="Challenge claims", timeout=5)])
        binding = load_bindings(self.path)[0]
        self.assertEqual((binding.executable, binding.role, binding.timeout),
                         ("owned-cli", "Challenge claims", 5))

    def test_unknown_top_level_and_resident_keys_reject(self):
        self.reject([self.valid()], extra="unexpected = true")
        self.reject([self.valid(extra_args=["--unsafe"])])
        self.reject([self.valid(session_id="private")])

    def test_agents_must_be_array_of_tables(self):
        for source in ('agents = "wrong"', 'agents = 1', 'agents = ["wrong"]', 'agents = []'):
            with self.subTest(source=source):
                self.path.write_text(source, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_bindings(self.path)

    def test_duplicate_unsafe_and_invalid_type_ids_reject(self):
        self.reject([self.valid(), self.valid(name="Other")])
        for value in ("../agent", "Claude", "", "a" * 41, "--exec", 1, True, ["claude"]):
            with self.subTest(id=value):
                self.reject([self.valid(id=value)])

    def test_more_than_five_residents_reject(self):
        self.reject([self.valid(id=f"agent{i}") for i in range(6)])

    def test_provider_types_and_unknown_provider_reject_cleanly(self):
        for value in ("unknown", "", 1, True, ["claude"], {"name": "claude"}):
            with self.subTest(provider=value):
                self.reject([self.valid(provider=value)])

    def test_invalid_name_role_and_executable_types_reject(self):
        for field, values in (
            ("name", ("", "x" * 61, 1, True)),
            ("role", ("x" * 4097, 1, True, ["wrong"])),
            ("executable", ("", "x" * 4097, 1, True, ["wrong"]))):
            for value in values:
                with self.subTest(field=field, value=str(value)[:20]):
                    self.reject([self.valid(**{field: value})])

    def test_workspace_must_exist_and_be_directory(self):
        file = self.root / "ordinary-file"
        file.write_text("content", encoding="utf-8")
        for value in ("missing", "ordinary-file", 1, True, ["wrong"]):
            with self.subTest(workspace=value):
                self.reject([self.valid(workspace=value)])

    def test_timeout_bounds_types_nan_and_infinity_reject(self):
        for value in (4.99, 600.01, -1, 0, "180", True, float("nan"), float("inf")):
            with self.subTest(timeout=value):
                self.reject([self.valid(timeout=value)])
        for value in (5, 600):
            self.write_agents([self.valid(timeout=value)])
            self.assertEqual(load_bindings(self.path)[0].timeout, value)

    def test_malformed_toml_rejects(self):
        self.path.write_text('[[agents]\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_bindings(self.path)


class DataOwnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_same_directory_is_exclusive_and_release_is_reusable(self):
        first = DataOwner(self.root)
        try:
            with self.assertRaises(RuntimeError):
                DataOwner(self.root)
        finally:
            first.close()
        first.close()  # Idempotent shutdown.
        with DataOwner(self.root) as second:
            self.assertFalse(second.file.closed)
        self.assertTrue(second.file.closed)

    def test_separate_data_directories_are_independently_owned(self):
        with DataOwner(self.root / "one"), DataOwner(self.root / "two"):
            self.assertTrue((self.root / "one" / "server.lock").exists())
            self.assertTrue((self.root / "two" / "server.lock").exists())

    def test_context_exception_releases_lock(self):
        with self.assertRaises(ValueError), DataOwner(self.root):
            raise ValueError("controlled")
        with DataOwner(self.root):
            pass

    def test_exclusivity_across_an_actual_process(self):
        code = (
            "from pathlib import Path\nfrom home.ownership import DataOwner\n" +
            f"with DataOwner(Path({str(self.root)!r})):\n    print('acquired')\n")
        with DataOwner(self.root):
            denied = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                    timeout=3, text=True, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("already has an active", denied.stderr)
        admitted = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                  timeout=3, text=True, check=False)
        self.assertEqual(admitted.returncode, 0)
        self.assertEqual(admitted.stdout.strip(), "acquired")


if __name__ == "__main__":
    unittest.main()
