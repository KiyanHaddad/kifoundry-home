"""Keep residents' homes stable while the configured population changes."""

import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
LAYOUT_MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "world-layout.js"

LAYOUT_RESIDENTS = """
import { readFileSync } from 'node:fs';
const { layoutResidents } = await import(process.argv[1]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const before = JSON.stringify(input);
const layouts = input.variants.map(agents => layoutResidents(agents));
const filterIds = input.filterIds === null ? null : new Set(input.filterIds);
const filtered = filterIds === null ? null : layoutResidents(
  input.variants[0].filter(agent => filterIds.has(agent.id))
);
process.stdout.write(JSON.stringify({
  layouts,
  filtered,
  source: input,
  sourceUnchanged: JSON.stringify(input) === before,
}));
"""


def resident(number, slot=None):
    agent = {
        "id": f"resident-{number:03d}",
        "name": f"Resident {number}",
        "provider": "fixture",
        "role": "Workshop resident",
    }
    if slot is not None:
        agent["home_slot"] = slot
    return agent


@unittest.skipUnless(NODE, "Node.js is required for the browser world-layout regression")
class WorldLayoutTests(unittest.TestCase):
    def layouts(self, *variants, filter_ids=None):
        payload = {"variants": variants, "filterIds": filter_ids}
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", LAYOUT_RESIDENTS, LAYOUT_MODULE.as_uri()],
            input=json.dumps(payload),
            capture_output=True,
            encoding="utf-8",
            timeout=10,
            check=False,
            shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result["sourceUnchanged"], "Laying out homes mutated the agent payload")
        self.assertEqual(json.loads(json.dumps(payload)), result["source"])
        return result

    def by_id(self, layout):
        return {entry["agent"]["id"]: entry for entry in layout}

    def location(self, entry):
        return {key: entry[key] for key in ("slot", "district", "plot", "appearance")}

    def assert_valid_home(self, entry):
        self.assertIsInstance(entry["slot"], int)
        self.assertGreaterEqual(entry["slot"], 0)
        self.assertLess(entry["slot"], 64)
        self.assertEqual(entry["slot"] // 5, entry["district"])
        self.assertIsInstance(entry["appearance"], int)
        self.assertGreaterEqual(entry["appearance"], 0)
        self.assertLess(entry["appearance"], 5)
        plot = entry["plot"]
        self.assertEqual({"x", "y", "feet"}, set(plot))
        self.assertEqual(2, len(plot["feet"]))
        for coordinate in (plot["x"], plot["y"], *plot["feet"]):
            self.assertIsInstance(coordinate, (float, int))
            self.assertTrue(math.isfinite(coordinate))

    def test_seven_and_sixty_four_residents_all_receive_homes(self):
        for count in (7, 64):
            with self.subTest(population=count):
                agents = [resident(number, number) for number in reversed(range(count))]
                layout = self.layouts(agents)["layouts"][0]
                self.assertEqual(count, len(layout))
                self.assertEqual({a["id"] for a in agents}, set(self.by_id(layout)))
                self.assertEqual(set(range(count)), {entry["slot"] for entry in layout})
                for entry in layout:
                    self.assertEqual(entry["agent"]["home_slot"], entry["slot"])
                    self.assert_valid_home(entry)

    def test_adding_and_removing_other_residents_preserves_existing_homes(self):
        original = [resident(number, number) for number in (2, 8, 26, 63)]
        added = [resident(90, 0), *reversed(original), resident(91, 39)]
        remaining = [agent for agent in added if agent["id"] != "resident-008"]
        first, second, third = self.layouts(original, added, remaining)["layouts"]
        first, second, third = map(self.by_id, (first, second, third))
        for agent in original:
            identity = agent["id"]
            self.assertEqual(self.location(first[identity]), self.location(second[identity]))
            if identity in third:
                self.assertEqual(self.location(first[identity]), self.location(third[identity]))

    def test_reused_slot_keeps_the_location_without_rendering_archived_resident(self):
        archived = resident(10, 17)
        keeper = resident(11, 29)
        replacement = resident(12, 17)
        before, after = self.layouts([archived, keeper], [keeper, replacement])["layouts"]
        before, after = self.by_id(before), self.by_id(after)
        self.assertNotIn(archived["id"], after)
        self.assertEqual({keeper["id"], replacement["id"]}, set(after))
        for key in ("slot", "district", "plot"):
            self.assertEqual(before[archived["id"]][key], after[replacement["id"]][key])
        self.assertEqual(self.location(before[keeper["id"]]), self.location(after[keeper["id"]]))

    def test_selection_and_filtering_preserve_source_and_home_assignments(self):
        agents = [resident(number, number) for number in (0, 6, 12, 38, 63)]
        selected_ids = [agents[1]["id"], agents[-1]["id"]]
        selected = [{**agent, "selected": agent["id"] in selected_ids} for agent in agents]
        result = self.layouts(agents, selected, filter_ids=selected_ids)
        original, selected_layout = map(self.by_id, result["layouts"])
        filtered = self.by_id(result["filtered"])
        self.assertEqual(set(selected_ids), set(filtered))
        for identity, entry in original.items():
            self.assertEqual(self.location(entry), self.location(selected_layout[identity]))
            if identity in filtered:
                self.assertEqual(self.location(entry), self.location(filtered[identity]))

    def test_legacy_payloads_use_id_order_independent_of_input_order(self):
        agents = [resident(number) for number in (30, 4, 21, 9, 55, 12, 2)]
        first, reordered = self.layouts(agents, list(reversed(agents)))["layouts"]
        first, reordered = self.by_id(first), self.by_id(reordered)
        for expected_slot, identity in enumerate(sorted(first)):
            self.assertEqual(expected_slot, first[identity]["slot"])
            self.assertEqual(self.location(first[identity]), self.location(reordered[identity]))
            self.assert_valid_home(first[identity])


if __name__ == "__main__":
    unittest.main()
