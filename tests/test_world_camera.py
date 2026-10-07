"""Keep the RPG viewport stable while the town grows and native scrolling changes it."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
CAMERA_MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "world-camera.js"
LAYOUT_MODULE = CAMERA_MODULE.with_name("world-layout.js")

CAMERA_SCENARIOS = """
import {readFileSync} from 'node:fs';
const {WorldCamera} = await import(process.argv[1]);
const {layoutTown} = await import(process.argv[2]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const decode = value => value === 'NaN' ? NaN : value === 'Infinity' ? Infinity : value;
const bounds = input.slots === undefined && input.population === undefined ? input.bounds : layoutTown(
  (input.slots || Array.from({length:input.population}, (_, index) => index)).map(slot => ({
    id:'synthetic-resident-' + slot, home_slot:slot,
  }))
).bounds;
const before = JSON.stringify(bounds);
let camera;
try { camera = new WorldCamera(bounds, input.width, input.height); }
catch(error) { process.stdout.write(JSON.stringify({error:error.name})); process.exit(0); }
const snapshot = () => ({x:camera.x, y:camera.y, zoom:camera.zoom,
  bounds:camera.bounds, viewportWidth:camera.viewportWidth,
  viewportHeight:camera.viewportHeight, frame:camera.frame()});
const results = [snapshot()];
for (const action of input.actions || []) {
  if(action.method === 'roundtrip') {
    const frame = camera.frame(); camera.readScroll(frame.scrollLeft, frame.scrollTop);
  } else {
    try { camera[action.method](...(action.args || []).map(decode)); }
    catch(error) { results.push({error:error.name}); continue; }
  }
  results.push(snapshot());
}
process.stdout.write(JSON.stringify({results, sourceUnchanged:before === JSON.stringify(bounds)}));
"""


def bounds(min_x=-2000, min_y=-1500, max_x=3000, max_y=2500):
    return {
        "minX": min_x,
        "minY": min_y,
        "maxX": max_x,
        "maxY": max_y,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def action(method, *args):
    return {"method": method, "args": args}


@unittest.skipUnless(NODE, "Node.js is required for the browser world-camera regression")
class WorldCameraTests(unittest.TestCase):
    def camera(self, *actions, world=None, width=800, height=520, population=None, slots=None):
        payload = {"bounds": world or bounds(), "width": width, "height": height, "actions": actions}
        if population is not None:
            payload["population"] = population
        if slots is not None:
            payload["slots"] = slots
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", CAMERA_SCENARIOS,
             CAMERA_MODULE.as_uri(), LAYOUT_MODULE.as_uri()],
            input=json.dumps(payload), capture_output=True, encoding="utf-8", timeout=10,
            check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        if "error" not in result:
            self.assertTrue(result["sourceUnchanged"], "The camera changed caller-owned bounds")
            return result["results"]
        return result

    def assert_center(self, state, x, y):
        self.assertAlmostEqual(x, state["x"])
        self.assertAlmostEqual(y, state["y"])

    def test_negative_origin_and_native_scroll_roundtrip(self):
        initial, moved, readback = self.camera(action("moveTo", 125, -275), action("roundtrip"))
        self.assert_center(initial, 0, 0)
        self.assertEqual(0.8, initial["zoom"])
        self.assert_center(moved, 125, -275)
        self.assertEqual(1300, moved["frame"]["scrollLeft"])
        self.assertEqual(720, moved["frame"]["scrollTop"])
        self.assertEqual(moved, readback)

    def test_growth_to_the_left_keeps_the_same_world_place(self):
        enlarged = bounds(-7000, -4500, 3000, 2500)
        states = self.camera(action("moveTo", 170, 230), action("setBounds", enlarged),
                             action("roundtrip"))
        before, after, readback = states[1:]
        self.assert_center(after, 170, 230)
        self.assertAlmostEqual(4000, after["frame"]["scrollLeft"] - before["frame"]["scrollLeft"])
        self.assertAlmostEqual(2400, after["frame"]["scrollTop"] - before["frame"]["scrollTop"])
        self.assertEqual(after, readback)

    def test_pointer_drag_follows_screen_distance_at_each_zoom(self):
        states = self.camera(action("pan", 80, -40), action("setZoom", 1), action("pan", -50, 25))
        self.assert_center(states[1], -100, 50)
        self.assert_center(states[2], -100, 50)
        self.assert_center(states[3], -50, 25)

    def test_zoom_and_pan_clamp_to_reachable_world_coordinates(self):
        states = self.camera(action("setZoom", 100), action("pan", 100000, -100000),
                             action("readScroll", -100, 100000), action("setZoom", -10))
        self.assertEqual(1.35, states[1]["zoom"])
        self.assert_center(states[2], -2000 + 800 / 2.7, 2500 - 520 / 2.7)
        self.assertAlmostEqual(0, states[3]["frame"]["scrollLeft"])
        self.assertAlmostEqual(states[3]["frame"]["height"] - 520,
                               states[3]["frame"]["scrollTop"])
        self.assertEqual(0.08, states[4]["zoom"])
        self.assert_center(states[4], 500, 500)

    def test_fit_can_show_all_64_homes_with_padding(self):
        _, fitted, readback = self.camera(action("fit"), action("roundtrip"), population=64)
        world = fitted["bounds"]
        self.assertLessEqual(world["width"] * fitted["zoom"], 800 - 64 + 1e-9)
        self.assertLessEqual(world["height"] * fitted["zoom"], 520 - 64 + 1e-9)
        self.assertGreaterEqual(fitted["frame"]["offsetX"], 32 - 1e-9)
        self.assertGreaterEqual(fitted["frame"]["offsetY"], 32 - 1e-9)
        self.assert_center(fitted, world["minX"] + world["width"] / 2,
                           world["minY"] + world["height"] / 2)
        self.assertEqual(fitted, readback)

    def test_fit_includes_a_distant_sparse_home_after_removals(self):
        _, fitted = self.camera(action("fit"), slots=[0, 63])
        world = fitted["bounds"]
        self.assertLessEqual(world["width"] * fitted["zoom"], 800 - 64 + 1e-9)
        self.assertLessEqual(world["height"] * fitted["zoom"], 520 - 64 + 1e-9)
        self.assert_center(fitted, world["minX"] + world["width"] / 2,
                           world["minY"] + world["height"] / 2)

    def test_small_world_centers_with_native_scroll_disabled(self):
        states = self.camera(action("moveTo", 9999, -9999), action("readScroll", 45, 50),
                             action("fit"), action("roundtrip"), world=bounds(-100, -50, 300, 150))
        for state in states:
            self.assert_center(state, 100, 50)
            self.assertEqual(800, state["frame"]["width"])
            self.assertEqual(520, state["frame"]["height"])
            self.assertEqual(0, state["frame"]["scrollLeft"])
            self.assertEqual(0, state["frame"]["scrollTop"])
        self.assertEqual(240, states[0]["frame"]["offsetX"])
        self.assertEqual(180, states[0]["frame"]["offsetY"])
        self.assertEqual(0.9, states[-1]["zoom"])

    def test_resize_keeps_place_and_updates_native_scroll(self):
        states = self.camera(action("moveTo", 400, 300), action("setViewport", 400, 300),
                             action("roundtrip"), action("setViewport", 6000, 4000))
        before, resized, readback, huge = states[1:]
        self.assert_center(resized, 400, 300)
        self.assertEqual(200, resized["frame"]["scrollLeft"] - before["frame"]["scrollLeft"])
        self.assertEqual(110, resized["frame"]["scrollTop"] - before["frame"]["scrollTop"])
        self.assertEqual(resized, readback)
        self.assert_center(huge, 500, 500)

    def test_bad_actions_leave_the_camera_usable_and_bounds_fail_atomically(self):
        invalid_world = bounds()
        invalid_world["width"] = -1
        states = self.camera(action("pan", "NaN", 1), action("setZoom", "Infinity"),
                             action("moveTo", None, 5), action("readScroll", 0, "NaN"),
                             action("setViewport", -1, 400), action("setBounds", invalid_world),
                             action("roundtrip"))
        for state in states[1:6]:
            self.assertEqual(states[0], state)
        self.assertEqual({"error": "TypeError"}, states[6])
        self.assertEqual(states[0], states[7])
        self.assertEqual({"error": "TypeError"}, self.camera(world=invalid_world))

    def test_constructor_rejects_invalid_extents_without_coercing_them(self):
        for replacement in ({"minX": None}, {"maxX": -2000}, {"width": 0},
                            {"width": "5000"}, {"height": 42}):
            with self.subTest(replacement=replacement):
                invalid = {**bounds(), **replacement}
                self.assertEqual({"error": "TypeError"}, self.camera(world=invalid))

    def test_invalid_initial_viewport_uses_centered_defaults(self):
        initial, = self.camera(world=bounds(1000, 1000, 1400, 1200), width=0, height="bad")
        self.assertEqual(800, initial["viewportWidth"])
        self.assertEqual(520, initial["viewportHeight"])
        self.assert_center(initial, 1200, 1100)

    def test_tiny_viewports_still_produce_finite_clamped_frames(self):
        states = self.camera(action("fit"), action("roundtrip"), width=20, height=10)
        self.assertEqual(0.08, states[1]["zoom"])
        self.assertEqual(states[1], states[2])
        for coordinate in states[-1]["frame"].values():
            self.assertIsInstance(coordinate, (float, int))


if __name__ == "__main__":
    unittest.main()
