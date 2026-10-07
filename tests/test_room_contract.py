"""Exercise the persisted-room contract at the browser normalization boundary."""

import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from home.store import Store

NODE = shutil.which("node")
ROOM_MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "room.js"

NORMALIZE_ROOM = """
import { readFileSync } from 'node:fs';
const { normalizeRoom } = await import(process.argv[1]);
const room = JSON.parse(readFileSync(0, 'utf8'));
const before = JSON.stringify(room);
const normalized = normalizeRoom(room);
process.stdout.write(JSON.stringify({
  normalized,
  source: room,
  sourceUnchanged: JSON.stringify(room) === before,
  separateRoom: normalized !== room,
}));
"""

RECOVERY_INFO = """
import { readFileSync } from 'node:fs';
const { recoveryInfo } = await import(process.argv[1]);
const rounds = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(rounds.map(recoveryInfo)));
"""


@unittest.skipUnless(NODE, "Node.js is required for the browser room-contract regression")
class RoomContractTests(unittest.TestCase):
    def normalize(self, room):
        result = subprocess.run(
            [NODE, "--input-type=module", "--eval", NORMALIZE_ROOM, ROOM_MODULE.as_uri()],
            input=json.dumps(room, ensure_ascii=False),
            capture_output=True,
            encoding="utf-8",
            timeout=10,
            check=False,
            shell=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_saved_original_and_revision_survive_browser_normalization(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(Store(Path(directory) / "home.sqlite3")) as store,
        ):
            room = store.create_room("Script workshop")
            original = store.save_artifact(
                room["id"], "Opening", "Original hook.\nThe promise needs evidence. 🌱"
            )
            revision = store.save_artifact(
                room["id"],
                "Opening revised",
                "Revised hook.\nShow the saved action before the claim. 🌿",
                artifact_id=original["id"],
                expected_version=original["version"],
            )
            persisted = store.room(room["id"])

        # Trusted full readback nests all bodies; the browser also accepts paged metadata.
        self.assertEqual(1, len(persisted["artifacts"]))
        self.assertEqual(revision["content"], persisted["artifacts"][0]["content"])
        self.assertEqual(2, len(persisted["artifacts"][0]["versions"]))

        browser = self.normalize(persisted)
        self.assertEqual([original, revision], browser["normalized"]["artifacts"])
        self.assertEqual(
            [(original["id"], 1), (original["id"], 2)],
            [(version["id"], version["version"])
             for version in browser["normalized"]["artifacts"]],
        )
        self.assertTrue(browser["separateRoom"])
        self.assertTrue(browser["sourceUnchanged"])
        self.assertEqual(persisted, browser["source"])
        self.assertEqual(1, len(browser["source"]["artifacts"]))
        self.assertEqual([original, revision], browser["source"]["artifacts"][0]["versions"])
        self.assertEqual(persisted["id"], browser["normalized"]["id"])
        self.assertEqual(persisted["messages"], browser["normalized"]["messages"])
        self.assertEqual(persisted["rounds"], browser["normalized"]["rounds"])

    def test_browser_metadata_keeps_latest_version_and_history_cursor_without_bodies(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(Store(Path(directory) / "home.sqlite3")) as store,
        ):
            room = store.create_room("Bounded studio")
            saved = store.save_artifact(room["id"], "Opening", "Original text")
            store.save_artifact(room["id"], "Opening", "Revised text", saved["id"], 1)
            payload = store.room_for_browser(room["id"])
        browser = self.normalize(payload)["normalized"]
        self.assertEqual(payload["artifacts"], browser["artifacts"])
        self.assertTrue(all("content" not in item for item in browser["artifacts"]))
        self.assertTrue(all(item["latest_version"] == 2 for item in browser["artifacts"]))
        self.assertIsNone(browser["next_artifact_cursor"])

    def test_flat_version_payload_remains_usable_without_nested_versions(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            closing(Store(Path(directory) / "home.sqlite3")) as store,
        ):
            room = store.create_room("Single saved draft")
            saved = store.save_artifact(room["id"], "Draft", "Keep this content unchanged.")
            payload = {**store.room(room["id"]), "artifacts": [saved]}

        browser = self.normalize(payload)
        self.assertEqual([saved], browser["normalized"]["artifacts"])
        self.assertTrue(browser["sourceUnchanged"])
        self.assertEqual(payload, browser["source"])

    def test_recovery_distinguishes_unstarted_work_from_uncertain_native_outcomes(self):
        def turn(phase, status, launched):
            return {"phase": phase, "status": status, "launched": launched}

        def round_state(mode, turns, status="cancelled"):
            return {"mode": mode, "status": status,
                    "participants": ["editor"] if mode == "direct" else ["editor", "planner"],
                    "turns": turns}

        cases = [
            round_state("direct", [turn("reply", "cancelled", False)]),
            round_state("direct", [turn("reply", "cancelled", True)]),
            round_state("direct", [turn("reply", "running", True)]),
            round_state("council", [turn("proposal", "completed", True),
                                    turn("proposal", "completed", True),
                                    turn("critique", "interrupted", True),
                                    turn("critique", "cancelled", False)], "interrupted"),
            round_state("council", [turn("proposal", "completed", True),
                                    turn("proposal", "completed", True),
                                    turn("critique", "completed", True),
                                    turn("critique", "completed", True),
                                    turn("synthesis", "interrupted", True)], "interrupted"),
            round_state("direct", [turn("reply", "completed", True)], "completed"),
        ]
        result = subprocess.run(
            [NODE, "--input-type=module", "--eval", RECOVERY_INFO, ROOM_MODULE.as_uri()],
            input=json.dumps(cases), capture_output=True, encoding="utf-8",
            timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        unstarted, uncertain, finishing, council, synthesis, completed = json.loads(result.stdout)
        self.assertTrue(unstarted["canResume"])
        self.assertEqual(1, unstarted["maxNewCalls"])
        self.assertFalse(uncertain["canResume"])
        self.assertEqual((1, 0), (uncertain["unknownCalls"], uncertain["maxNewCalls"]))
        self.assertTrue(finishing["waiting"])
        self.assertFalse(finishing["canResume"])
        self.assertTrue(council["canResume"])
        self.assertEqual((1, 2), (council["unknownCalls"], council["maxNewCalls"]))
        self.assertFalse(synthesis["canResume"])
        self.assertEqual(0, synthesis["maxNewCalls"])
        self.assertIsNone(completed)


if __name__ == "__main__":
    unittest.main()
