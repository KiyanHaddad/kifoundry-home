"""Keep the return-to-work summary grounded in ordered saved metadata and actual execution."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
DESK_MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "working-desk.js"
APP_MODULE = DESK_MODULE.with_name("app.js")

DESK_SCENARIOS = """
import { readFileSync } from 'node:fs';
const { newestPageDraft, deskActivity } = await import(process.argv[1]);
const input = JSON.parse(readFileSync(0, 'utf8'));
const before = JSON.stringify(input);
function freeze(value) {
  if (!value || typeof value !== 'object') return;
  Object.freeze(value);
  for (const child of Object.values(value)) freeze(child);
}
freeze(input);
const results = input.map(item => item.kind === 'draft' ? newestPageDraft(item.artifacts) :
  deskActivity(item.room, item.connected, item.fixture));
process.stdout.write(JSON.stringify({results, unchanged:before === JSON.stringify(input)}));
"""

BOOT_SCENARIOS = """
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(process.argv[1], 'utf8'), scenario = process.argv[2];
const {newestPageDraft} = await import(process.argv[3]);
const {normalizeRoom} = await import(process.argv[4]);
function extract(start, end) {
  if (source.split(start).length !== 2) throw Error('Ambiguous function boundary: ' + start);
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length);
  if (to < 0) throw Error('Missing function boundary: ' + end);
  return source.slice(from, to);
}
const elements = new Map(), requests = [], errors = [];
const element = id => {
  if (!elements.has(id)) elements.set(id, {
    value:'', textContent:'', classList:{toggle(){}}, replaceChildren(){},
  });
  return elements.get(id);
};
const version = {id:'synthetic-draft', title:'Saved draft', version:1, latest_version:1};
const makeRoom = id => ({id, title:id, messages:[], rounds:[], artifacts:[version]});
const current = makeRoom('current-room'), initial = makeRoom('initial-room');
const state = {
  room:scenario === 'first-boot' ? null : current, rooms:[], agents:[], selected:new Set(),
  connected:false, loading:false, saving:false, sending:false, resuming:false,
  editKey:'synthetic-draft:1', editDirty:true, artifactLoadEpoch:0, artifactPages:1,
  artifactBodies:new Map([['synthetic-draft:1', {...version, content:'Cached exact body'}]]),
};
element('composerText').value = 'Unsent in-memory message';
element('artifactTitle').value = 'Unsaved in-memory title';
element('artifactContent').value = 'Unsaved in-memory draft';
const storedDraft = {
  text:'Stored unsent message', editKey:'synthetic-draft:1', title:'Stored edited title',
  content:'Stored unsaved edit', dirty:true, attachedId:'',
};
const context = {
  state, $:element, newestPageDraft, normalizeRoom,
  artifactKey:artifact => artifact.id + ':' + artifact.version,
  document:{querySelector:() => ({classList:{toggle(){}}})},
  location:{hash:'', pathname:'/', search:''}, URLSearchParams,
  history:{replaceState(){}},
  storageRead(key) {
    if (key === 'kifoundry-home:last-room') return scenario === 'first-boot' ? 'remembered-room' :
      scenario === 'stale-pointer' ? 'stale-stored-room' : null;
    if (scenario === 'first-boot' && key === 'kifoundry-home:draft:remembered-room') {
      return JSON.stringify(storedDraft);
    }
    return null;
  },
  storageWrite(){}, saveSessionProof(){},
  async api(path) {
    requests.push(path);
    if (path === '/api/session') return {csrf:'synthetic-browser-proof'};
    if (path === '/api/state') return {
      agents:[{id:'synthetic-resident'}], rooms:[initial], room:initial, fixture:true,
    };
    if (path === '/api/rooms/current-room') return current;
    if (path === '/api/rooms/remembered-room') return makeRoom('remembered-room');
    if (path === '/api/rooms/stale-stored-room') return makeRoom('stale-stored-room');
    throw Error('Unexpected route: ' + path);
  },
  applyResidents(data){state.agents = data.agents;},
  updateComposer(){}, showError(_id, text=''){if(text)errors.push(text);}, toggle(){},
  updateHouseStates(){}, renderHouses(){}, renderParticipants(){}, renderRooms(){},
  renderDiscussion(){}, renderActivity(){}, renderArtifacts(){}, schedulePoll(){},
};
runInNewContext(extract('async function boot() {', 'function renderHouses() {') + '\\n' +
  extract('function restoreDraft() {', 'function renderRooms() {') + '\\n' +
  'globalThis.runBoot=boot;', context);
let attempts;
if (scenario === 'mutation-guards') {
  attempts = [];
  for (const flag of ['loading', 'saving', 'sending', 'resuming']) {
    state[flag] = true; await context.runBoot();
    attempts.push({flag, requests:[...requests]}); state[flag] = false;
  }
} else await context.runBoot();
process.stdout.write(JSON.stringify({requests, errors, attempts,
  roomId:state.room?.id, connected:state.connected, dirty:state.editDirty,
  composer:element('composerText').value, title:element('artifactTitle').value,
  draft:element('artifactContent').value, cachedBodies:state.artifactBodies.size,
  loadedPages:state.artifactPages}));
"""


def artifact(identity, version, timestamp, latest=None):
    return {"id": identity, "title": "Draft " + identity, "version": version,
            "latest_version": version if latest is None else latest, "created_at": timestamp}


def turn(identity="editor", status="running", phase="reply"):
    return {"agent_id": identity, "status": status, "phase": phase}


def activity(rounds=None, *, connected=True, fixture=False):
    return {"kind": "activity", "room": {"rounds": rounds or []},
            "connected": connected, "fixture": fixture}


@unittest.skipUnless(NODE, "Node.js is required for browser working-desk checks")
class WorkingDeskTests(unittest.TestCase):
    def scenarios(self, *items):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", DESK_SCENARIOS, DESK_MODULE.as_uri()],
            input=json.dumps(items), capture_output=True, encoding="utf-8", timeout=10,
            check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertTrue(result["unchanged"], "Summarizing work mutated saved records")
        return result["results"]

    def boot_scenario(self, name):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", BOOT_SCENARIOS, str(APP_MODULE), name,
             DESK_MODULE.as_uri(), DESK_MODULE.with_name("room.js").as_uri()],
            capture_output=True, encoding="utf-8", timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual([], result["errors"])
        return result

    def test_reconnect_preserves_open_room_and_in_memory_edits_when_storage_is_unavailable(self):
        result = self.boot_scenario("blocked-storage")
        self.assertEqual("current-room", result["roomId"])
        self.assertEqual(["/api/session", "/api/state", "/api/rooms/current-room"],
                         result["requests"])
        self.assertEqual("Unsent in-memory message", result["composer"])
        self.assertEqual("Unsaved in-memory title", result["title"])
        self.assertEqual("Unsaved in-memory draft", result["draft"])
        self.assertTrue(result["dirty"])
        self.assertTrue(result["connected"])
        self.assertEqual(1, result["cachedBodies"])
        self.assertEqual(1, result["loadedPages"])

    def test_reconnect_prefers_open_conversation_to_stale_browser_pointer(self):
        result = self.boot_scenario("stale-pointer")
        self.assertEqual("current-room", result["roomId"])
        self.assertNotIn("/api/rooms/stale-stored-room", result["requests"])
        self.assertEqual("Unsaved in-memory draft", result["draft"])
        self.assertEqual("Unsent in-memory message", result["composer"])

    def test_first_boot_still_restores_remembered_conversation_and_browser_draft(self):
        result = self.boot_scenario("first-boot")
        self.assertEqual("remembered-room", result["roomId"])
        self.assertEqual("Stored unsent message", result["composer"])
        self.assertEqual("Stored edited title", result["title"])
        self.assertEqual("Stored unsaved edit", result["draft"])
        self.assertTrue(result["dirty"])
        self.assertTrue(result["connected"])

    def test_reconnect_cannot_begin_during_loading_or_an_in_flight_mutation(self):
        result = self.boot_scenario("mutation-guards")
        self.assertEqual([], result["requests"])
        for attempt in result["attempts"]:
            with self.subTest(flag=attempt["flag"]):
                self.assertEqual([], attempt["requests"])
        self.assertEqual("Unsaved in-memory draft", result["draft"])

    def test_server_page_order_wins_over_equal_timestamps_and_clock_reversal(self):
        stamp = "2026-01-01T12:00:00Z"
        first = artifact("first", 1, stamp)
        same_time = artifact("second", 8, stamp)
        earlier_clock = artifact("clock-reversed", 1, "2025-12-31T12:00:00Z")
        results = self.scenarios(
            {"kind": "draft", "artifacts": [first, same_time]},
            {"kind": "draft", "artifacts": [earlier_clock, first]},
        )
        self.assertEqual([first, earlier_clock], results)

    def test_draft_selection_skips_stale_and_malformed_metadata_without_sorting(self):
        stale = artifact("old", 1, "2026-01-02T12:00:00Z", latest=3)
        saved = artifact("saved", 2, "2026-01-01T12:00:00Z")
        later = artifact("later", 7, "2026-01-03T12:00:00Z")
        result = self.scenarios({"kind": "draft", "artifacts": [
            None, {}, {**saved, "version": -1}, stale, saved, later,
        ]})[0]
        self.assertEqual(saved, result)

    def test_empty_missing_or_only_stale_pages_have_no_saved_draft(self):
        results = self.scenarios(
            {"kind": "draft", "artifacts": []},
            {"kind": "draft"},
            {"kind": "draft", "artifacts": [artifact("old", 1, "", latest=2)]},
        )
        self.assertEqual([None, None, None], results)

    def test_disconnected_saved_progress_never_claims_live_execution(self):
        result = self.scenarios(activity([
            {"status": "running", "mode": "direct", "turns": [turn()]},
        ], connected=False))[0]
        self.assertEqual("Connection unavailable", result["text"])
        self.assertIn("Saved progress only", result["detail"])
        self.assertEqual("offline", result["tone"])
        self.assertTrue(result["hasRound"])
        self.assertNotIn("Replying now", result["detail"])

    def test_empty_conversation_and_fixture_remain_explicit(self):
        empty, demo, offline = self.scenarios(
            activity(), activity(fixture=True), activity(connected=False, fixture=True),
        )
        self.assertEqual("No replies yet", empty["text"])
        self.assertFalse(empty["hasRound"])
        self.assertEqual("neutral", empty["tone"])
        self.assertTrue(demo["detail"].startswith("Demo responses. "))
        self.assertTrue(offline["detail"].startswith("Demo responses. "))
        self.assertFalse(offline["hasRound"])

    def test_pending_round_wins_over_newer_terminal_round(self):
        queued, running = self.scenarios(
            activity([{"status": "queued", "turns": [turn(status="queued")]},
                      {"status": "completed", "turns": [turn(status="completed")]}]),
            activity([{"status": "completed", "turns": [turn(status="completed")]},
                      {"status": "running", "mode": "direct", "turns": [turn()]}]),
        )
        self.assertEqual("Waiting to begin", queued["text"])
        self.assertEqual("Reply in progress", running["text"])
        self.assertEqual("working", running["tone"])

    def test_cancelled_round_with_pending_calls_is_still_stopping(self):
        result = self.scenarios(activity([
            {"status": "cancelled", "turns": [turn(status="completed"), turn("other")]},
            {"status": "completed", "turns": []},
        ]))[0]
        self.assertEqual("Stopping · waiting for calls to finish", result["text"])
        self.assertIn("1 reply saved", result["detail"])
        self.assertEqual("warning", result["tone"])

    def test_running_names_use_saved_snapshots_are_bounded_and_are_plain_strings(self):
        result = self.scenarios(activity([{
            "status": "running", "mode": "council",
            "participant_snapshots": {
                "editor": {"name": "Historical Editor"},
                "other": {"name": "<b>" + "Long Name " * 20 + "</b>"},
                "third": {"name": "Third"},
                "fourth": {"name": "Fourth"},
            },
            "turns": [turn(), turn(phase="critique"), turn("other"),
                      turn("third"), turn("fourth"), turn("finished", "completed")],
        }], fixture=True))[0]
        self.assertEqual("Council in progress", result["text"])
        self.assertTrue(result["detail"].startswith("Demo responses. "))
        self.assertIn("Historical Editor", result["detail"])
        self.assertIn("<b>", result["detail"])
        self.assertIn("… + 2 more", result["detail"])
        self.assertNotIn("Third", result["detail"])
        self.assertLess(len(result["detail"]), 170)

    def test_terminal_states_remain_distinct_and_latest_saved_round_is_used(self):
        statuses = ["completed", "partial", "failed", "interrupted", "cancelled"]
        results = self.scenarios(*(activity([
            {"status": "failed", "turns": []},
            {"status": status, "turns": [turn(status="completed")]},
        ]) for status in statuses))
        self.assertEqual([
            "Last reply finished", "Some replies received", "Last round could not finish",
            "Round interrupted", "Round stopped",
        ], [result["text"] for result in results])
        self.assertTrue(all("1 reply saved" in result["detail"] for result in results))
        self.assertTrue(all(result["hasRound"] for result in results))

    def test_finished_council_keeps_failed_calls_visible(self):
        result = self.scenarios(activity([{
            "status": "completed", "mode": "council",
            "turns": [turn(status="completed"), turn("other", "failed")],
        }]))[0]
        self.assertEqual("Last reply finished", result["text"])
        self.assertEqual("warning", result["tone"])
        self.assertIn("Some calls could not finish", result["detail"])


if __name__ == "__main__":
    unittest.main()
