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
const { HOMES_PER_DISTRICT, districtGeometry, layoutResidents, layoutTown } = await import(process.argv[1]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const before = JSON.stringify(input);
const layouts = input.variants.map(agents => layoutResidents(agents));
const towns = input.variants.map(agents => layoutTown(agents, new Set(input.extraDistricts)));
const geometry = input.districtIds.map(id => districtGeometry(id));
const filterIds = input.filterIds === null ? null : new Set(input.filterIds);
const filtered = filterIds === null ? null : layoutResidents(
  input.variants[0].filter(agent => filterIds.has(agent.id))
);
process.stdout.write(JSON.stringify({
  layouts,
  towns,
  geometry,
  homesPerDistrict: HOMES_PER_DISTRICT,
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
    def layouts(self, *variants, filter_ids=None, district_ids=(), extra_districts=()):
        payload = {"variants": variants, "filterIds": filter_ids, "districtIds": list(district_ids),
                   "extraDistricts": list(extra_districts)}
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
        self.assertEqual(8, result["homesPerDistrict"])
        return result

    def by_id(self, layout):
        return {entry["agent"]["id"]: entry for entry in layout}

    def location(self, entry):
        return {key: entry[key] for key in ("slot", "district", "plot", "appearance")}

    def assert_valid_home(self, entry):
        self.assertIsInstance(entry["slot"], int)
        self.assertGreaterEqual(entry["slot"], 0)
        self.assertLess(entry["slot"], 64)
        self.assertEqual(entry["slot"] // 8, entry["district"])
        self.assertIsInstance(entry["appearance"], int)
        self.assertGreaterEqual(entry["appearance"], 0)
        self.assertLess(entry["appearance"], 5)
        plot = entry["plot"]
        self.assertEqual({"x", "y", "feet"}, set(plot))
        self.assertEqual(2, len(plot["feet"]))
        for coordinate in (plot["x"], plot["y"], *plot["feet"]):
            self.assertIsInstance(coordinate, (float, int))
            self.assertTrue(math.isfinite(coordinate))
        self.assertEqual([plot["x"], plot["y"] + 38], plot["feet"])

    def test_empty_small_and_full_towns_all_receive_unique_homes(self):
        for count in (0, 1, 5, 16, 64):
            with self.subTest(population=count):
                agents = [resident(number, number) for number in reversed(range(count))]
                result = self.layouts(agents)
                layout = result["layouts"][0]
                self.assertEqual(count, len(layout))
                self.assertEqual({a["id"] for a in agents}, set(self.by_id(layout)))
                self.assertEqual(set(range(count)), {entry["slot"] for entry in layout})
                self.assertEqual(count, len({(entry["plot"]["x"], entry["plot"]["y"]) for entry in layout}))
                for entry in layout:
                    self.assertEqual(entry["agent"]["home_slot"], entry["slot"])
                    self.assert_valid_home(entry)
                self.assert_valid_town(result["towns"][0], count)

    def assert_valid_town(self, town, count):
        self.assertEqual(count, len(town["entries"]))
        self.assertEqual(count, sum(district["count"] for district in town["districts"]))
        self.assertIn(0, {district["id"] for district in town["districts"]})
        bounds = town["bounds"]
        self.assertEqual(bounds["maxX"] - bounds["minX"], bounds["width"])
        self.assertEqual(bounds["maxY"] - bounds["minY"], bounds["height"])
        for number in bounds.values():
            self.assertTrue(math.isfinite(number))
        for district in town["districts"]:
            self.assertEqual(8, len(district["plots"]))
            self.assertGreaterEqual(district["bounds"]["minX"], bounds["minX"] + 40)
            self.assertGreaterEqual(district["bounds"]["minY"], bounds["minY"] + 40)
            self.assertLessEqual(district["bounds"]["maxX"], bounds["maxX"] - 40)
            self.assertLessEqual(district["bounds"]["maxY"], bounds["maxY"] - 40)
        points = [entry["plot"]["feet"] for entry in town["entries"]]
        points += [[town["commons"]["x"], town["commons"]["y"]],
                   [town["studio"]["x"], town["studio"]["y"]]]
        for x, y in points:
            self.assertLessEqual(bounds["minX"], x)
            self.assertLessEqual(bounds["minY"], y)
            self.assertGreaterEqual(bounds["maxX"], x)
            self.assertGreaterEqual(bounds["maxY"], y)

    def test_sparse_outer_slot_keeps_its_saved_location_and_central_landmarks(self):
        result = self.layouts([resident(1, 63)])
        entry = result["layouts"][0][0]
        town = result["towns"][0]
        self.assertEqual((63, 7), (entry["slot"], entry["district"]))
        self.assertEqual([0, 7], [district["id"] for district in town["districts"]])
        self.assertEqual([0, 1], [district["count"] for district in town["districts"]])
        self.assertEqual({"x": 0, "y": 100}, town["commons"])
        self.assertEqual({"x": 210, "y": -20}, town["studio"])
        self.assert_valid_home(entry)
        self.assert_valid_town(town, 1)

    def test_districts_follow_a_fixed_square_spiral_and_have_unique_names(self):
        geometry = self.layouts([], district_ids=range(25))["geometry"]
        first_ring = [(0, 0), (0, -1), (1, -1), (1, 0), (1, 1),
                      (0, 1), (-1, 1), (-1, 0), (-1, -1)]
        self.assertEqual(first_ring, [(district["x"] // 1150, district["y"] // 1080)
                                      for district in geometry[:9]])
        self.assertEqual(25, len({(district["x"], district["y"]) for district in geometry}))
        self.assertEqual(25, len({district["name"] for district in geometry}))
        self.assertEqual({(x, y) for x in range(-2, 3) for y in range(-2, 3)},
                         {(district["x"] // 1150, district["y"] // 1080) for district in geometry})
        self.assertEqual("Commons Quarter", geometry[0]["name"])
        self.assertEqual("North Grove", geometry[1]["name"])
        for district in geometry:
            self.assertEqual([district["x"], district["y"] + 100], district["hub"])
            self.assertEqual(list(range(district["id"] * 8, district["id"] * 8 + 8)),
                             [plot["slot"] for plot in district["plots"]])

    def test_plot_offsets_are_fixed_inside_each_module(self):
        offsets = [(-320, -180), (0, -250), (320, -180), (-380, 100),
                   (380, 100), (-290, 340), (0, 380), (290, 340)]
        geometry = self.layouts([], district_ids=(0, 1, 7))["geometry"]
        for district in geometry:
            self.assertEqual(offsets, [(plot["x"] - district["x"], plot["y"] - district["y"])
                                      for plot in district["plots"]])

    def test_retired_neighborhood_remains_without_archived_identity(self):
        departed = resident(10, 63)
        before, after = self.layouts([departed], [], extra_districts=(7,))["towns"]
        self.assertEqual(before["bounds"], after["bounds"])
        self.assertEqual([0, 7], [district["id"] for district in after["districts"]])
        self.assertEqual([0, 0], [district["count"] for district in after["districts"]])
        self.assertEqual([], after["entries"])
        self.assertNotIn(departed["id"], json.dumps(after))
        self.assert_valid_town(after, 0)

    def test_visited_future_neighborhood_can_be_retained_once(self):
        town = self.layouts([], extra_districts=(8, 8, 0))["towns"][0]
        self.assertEqual([0, 8], [district["id"] for district in town["districts"]])
        self.assertEqual("Northwest Grove", town["districts"][1]["name"])
        self.assert_valid_town(town, 0)

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
