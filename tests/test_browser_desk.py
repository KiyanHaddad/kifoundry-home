"""Exercise the actual desk actions and room adoption with controlled browser state."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[1] / "home" / "web"

SCENARIOS = r"""
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(process.argv[1], 'utf8');
const scenario = process.argv[2];
const {newestPageDraft} = await import(process.argv[3]);
const {normalizeRoom} = await import(process.argv[4]);
function extract(start, end) {
  if (source.split(start).length !== 2) throw Error('Ambiguous function boundary: ' + start);
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length);
  if (to < 0) throw Error('Missing function boundary: ' + end);
  return source.slice(from, to);
}
const functions = [
  extract('function continueConversation() {', 'async function sendMessage(event) {'),
  extract('function adoptRoom(', 'function renderRooms() {'),
  extract('async function selectArtifact(key) {', 'async function loadOlderArtifacts() {'),
  extract('function renderActivity() {', 'function renderRecovery() {'),
  extract('function activeRound() {', 'function storageRead(key) {'),
].join('\n');
const events = [], selectedKeys = [], errors = [], storage = new Map();
const documentState = {body:{}, activeElement:{}, querySelector:() => new Element()};
class Element {
  constructor(tag = 'div', text = '') {
    this.tag = tag; this.textContent = text; this.value = ''; this.children = [];
    this.dataset = {}; this.open = false; this.disabled = false;
    this.hidden = false;
    this.classList = {toggle() {}, contains:() => this.hidden};
  }
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  querySelector(tag) {
    for (const child of this.children) {
      if (child.tag === tag) return child;
      const nested = child.querySelector(tag); if (nested) return nested;
    }
    return null;
  }
  focus() {events.push('focus:' + this.tag); documentState.activeElement = this;}
  scrollIntoView() {events.push('scroll:' + this.tag);}
}
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}
const artifactKey = artifact => artifact.id + ':' + artifact.version;
const old = {id:'older-work', title:'Earlier saved work', version:1, latest_version:1};
const recent = {id:'newer-work', title:'Newest saved work', version:7, latest_version:7};
const room = (id, artifacts = [], rounds = []) => ({id, title:id, artifacts, rounds, messages:[]});
const state = {
  room:room('synthetic-room', [old, recent]), rooms:[], recentArtifact:recent,
  editKey:'older-work:1', editDirty:false, unresolvedArtifact:false,
  loading:false, loadingArtifact:false, saving:false, connected:true,
  artifactLoadEpoch:0, artifactPages:1, artifactCursor:'older-page',
  artifactBodies:new Map(), activityRoundId:'', activityKey:'',
};
element('artifactTitle').value = 'Current editor';
element('artifactContent').value = 'Keep this editor text';
let deferred;
const context = {
  state, $:element, artifactKey, newestPageDraft, normalizeRoom,
  activeStatuses:new Set(['queued', 'running']),
  statusLabels:{completed:'Finished', running:'Thinking', interrupted:'Interrupted'},
  phaseLabels:{direct:'Reply'}, agentName:() => 'Synthetic resident',
  node:(tag, text = '') => new Element(tag, text),
  document:documentState,
  toggle() {}, showError:(_id, text = '') => errors.push(text),
  openStudio() {events.push('open-studio');},
  motionBehavior:() => 'auto',
  storageRead:key => storage.get(key) || null,
  storageWrite:(key, value) => storage.set(key, value),
  restoreDraft() {events.push('restore-draft');},
  renderRooms() {}, renderDiscussion() {}, renderArtifacts() {},
  updateHouseStates() {}, updateComposer() {}, persistDraft() {events.push('persist-draft');},
  preserveEditedWork() {events.push('preserve-editor');},
  async loadArtifactBody(metadata) {
    selectedKeys.push(artifactKey(metadata));
    if (['late-room-switch', 'focus-restored', 'focus-preserved', 'focus-closed'].includes(scenario)) {
      return new Promise(resolve => {deferred = resolve;});
    }
    return {...metadata, content:'Exact saved revision ' + metadata.version};
  },
  api() {throw Error('Desk actions must not submit provider work');},
};
runInNewContext(functions + '\nglobalThis.deskFunctions={continueConversation,continueDeskDraft,viewDeskActivity,adoptRoom,renderActivity};', context);
const {continueConversation, continueDeskDraft, viewDeskActivity, adoptRoom, renderActivity} = context.deskFunctions;
let result;
if (['dirty', 'unresolved', 'empty', 'clean', 'blocked'].includes(scenario)) {
  if (scenario === 'dirty') state.editDirty = true;
  if (scenario === 'unresolved') state.unresolvedArtifact = true;
  if (scenario === 'empty') state.recentArtifact = null;
  if (scenario === 'blocked') {
    result = [];
    for (const flag of ['loading', 'saving', 'loadingArtifact']) {
      state[flag] = true; await continueDeskDraft();
      result.push({flag, events:[...events], selectedKeys:[...selectedKeys]}); state[flag] = false;
    }
    state.room = null; await continueDeskDraft();
    result.push({flag:'no-room', events:[...events], selectedKeys:[...selectedKeys]});
  } else await continueDeskDraft();
} else if (['late-room-switch', 'focus-restored', 'focus-preserved', 'focus-closed'].includes(scenario)) {
  const pending = continueDeskDraft();
  if (!deferred || !state.loadingArtifact) throw Error('Exact version lookup did not become pending');
  documentState.activeElement = scenario === 'focus-preserved' ? element('composerText') : documentState.body;
  if (scenario === 'focus-closed') element('studioPanel').hidden = true;
  if (scenario === 'late-room-switch') {
    state.room = room('second-room'); ++state.artifactLoadEpoch; state.loadingArtifact = false;
    state.editKey = 'second-room-work:2';
    element('artifactTitle').value = 'Second room editor';
    element('artifactContent').value = 'Second room unsaved text';
  }
  deferred({...recent, content:'Late first room revision'}); await pending;
} else if (scenario === 'activity' || scenario === 'active-before-latest') {
  const stopped = {id:'older-stopped', status:'interrupted', mode:'direct', turns:[]};
  const latest = {id:'latest-finished', status:'completed', mode:'direct', turns:[
    {agent_id:'synthetic-latest', phase:'direct', status:'completed'}],
    participant_snapshots:{'synthetic-latest':{name:'Latest saved speaker'}}};
  const active = {id:'actually-running', status:'running', mode:'direct', turns:[
    {agent_id:'synthetic-active', phase:'direct', status:'running'}],
    participant_snapshots:{'synthetic-active':{name:'Currently replying'}}};
  state.room.rounds = scenario === 'activity' ? [stopped, latest] : [stopped, active, latest];
  state.activityRoundId = stopped.id; renderActivity();
  viewDeskActivity();
  const details = element('roundActivity').querySelector('details');
  const list = details.children[1];
  result = {id:state.activityRoundId, expanded:details.open,
    turnText:list.children.map(turn => turn.children.map(item => item.textContent).join(' ')).join(' ')};
} else if (scenario === 'fresh-page') {
  state.recentArtifact = old;
  adoptRoom(room('synthetic-room', [recent]));
  result = {recent:state.recentArtifact, mergedKeys:state.room.artifacts.map(artifactKey), cursor:state.artifactCursor};
} else if (scenario === 'local-round-update') {
  adoptRoom({...state.room, rounds:[{id:'confirmed-resume', status:'running', mode:'direct', turns:[]}]}, false, false);
  result = {recent:state.recentArtifact, mergedKeys:state.room.artifacts.map(artifactKey), round:state.room.rounds[0].id};
} else if (scenario === 'new-room') {
  adoptRoom(room('second-room'), true);
  result = {recent:state.recentArtifact, keys:state.room.artifacts.map(artifactKey), cursor:state.artifactCursor};
} else if (scenario === 'conversation') {
  continueConversation();
  state.loading = true; continueConversation();
  state.loading = false; state.room = null; continueConversation();
} else throw Error('Unknown scenario');
process.stdout.write(JSON.stringify({result, events, selectedKeys, errors,
  state:{roomId:state.room?.id, editKey:state.editKey, editDirty:state.editDirty,
    unresolvedArtifact:state.unresolvedArtifact, loadingArtifact:state.loadingArtifact},
  editor:{title:element('artifactTitle').value, content:element('artifactContent').value}}));
"""


@unittest.skipUnless(NODE, "Node.js is required for browser desk integration checks")
class BrowserDeskTests(unittest.TestCase):
    def scenario(self, name):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", SCENARIOS, str(WEB / "app.js"), name,
             (WEB / "working-desk.js").as_uri(), (WEB / "room.js").as_uri()],
            capture_output=True, encoding="utf-8", timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        return json.loads(process.stdout)

    def test_continue_editing_preserves_dirty_or_unresolved_work_without_loading(self):
        for name in ("dirty", "unresolved"):
            with self.subTest(name=name):
                result = self.scenario(name)
                self.assertEqual(["open-studio"], result["events"])
                self.assertEqual([], result["selectedKeys"])
                self.assertEqual("older-work:1", result["state"]["editKey"])
                self.assertEqual("Keep this editor text", result["editor"]["content"])
                self.assertTrue(result["state"]["editDirty" if name == "dirty" else "unresolvedArtifact"])

    def test_open_saved_draft_loads_the_exact_recent_revision(self):
        result = self.scenario("clean")
        self.assertEqual(["newer-work:7"], result["selectedKeys"])
        self.assertEqual("newer-work:7", result["state"]["editKey"])
        self.assertEqual("Exact saved revision 7", result["editor"]["content"])
        self.assertEqual("Newest saved work", result["editor"]["title"])
        self.assertFalse(result["state"]["loadingArtifact"])
        self.assertEqual([], [error for error in result["errors"] if error])

    def test_bring_first_draft_opens_the_existing_editor_without_loading(self):
        result = self.scenario("empty")
        self.assertEqual(["open-studio"], result["events"])
        self.assertEqual([], result["selectedKeys"])
        self.assertEqual("Keep this editor text", result["editor"]["content"])

    def test_loading_or_saving_blocks_desk_draft_actions(self):
        result = self.scenario("blocked")
        for attempt in result["result"]:
            with self.subTest(flag=attempt["flag"]):
                self.assertEqual([], attempt["events"])
                self.assertEqual([], attempt["selectedKeys"])

    def test_late_draft_lookup_cannot_replace_a_different_rooms_editor(self):
        result = self.scenario("late-room-switch")
        self.assertEqual(["newer-work:7"], result["selectedKeys"])
        self.assertEqual("second-room", result["state"]["roomId"])
        self.assertEqual("second-room-work:2", result["state"]["editKey"])
        self.assertEqual("Second room unsaved text", result["editor"]["content"])
        self.assertEqual("Second room editor", result["editor"]["title"])
        self.assertFalse(result["state"]["loadingArtifact"])
        self.assertNotIn("persist-draft", result["events"])
        self.assertNotIn("focus:artifactTitle", result["events"])

    def test_exact_version_completion_restores_lost_editor_focus(self):
        result = self.scenario("focus-restored")
        self.assertIn("focus:artifactTitle", result["events"])
        self.assertEqual("newer-work:7", result["state"]["editKey"])

    def test_exact_version_completion_preserves_deliberate_focus_elsewhere(self):
        result = self.scenario("focus-preserved")
        self.assertNotIn("focus:artifactTitle", result["events"])
        self.assertEqual("newer-work:7", result["state"]["editKey"])

    def test_exact_version_completion_cannot_focus_an_editor_closed_during_loading(self):
        result = self.scenario("focus-closed")
        self.assertNotIn("focus:artifactTitle", result["events"])
        self.assertEqual("newer-work:7", result["state"]["editKey"])

    def test_view_replies_replaces_an_older_recovery_round_with_the_latest_round(self):
        result = self.scenario("activity")
        self.assertEqual("latest-finished", result["result"]["id"])
        self.assertTrue(result["result"]["expanded"])
        self.assertIn("Latest saved speaker", result["result"]["turnText"])
        self.assertEqual(["focus:summary", "scroll:roundActivity"], result["events"])

    def test_view_replies_prioritizes_current_work_over_a_newer_completed_record(self):
        result = self.scenario("active-before-latest")
        self.assertEqual("actually-running", result["result"]["id"])
        self.assertTrue(result["result"]["expanded"])
        self.assertIn("Currently replying", result["result"]["turnText"])

    def test_fresh_page_sets_recent_work_before_merging_older_editor_history(self):
        result = self.scenario("fresh-page")["result"]
        self.assertEqual("newer-work", result["recent"]["id"])
        self.assertEqual(["older-work:1", "newer-work:7"], result["mergedKeys"])
        self.assertEqual("older-page", result["cursor"])

    def test_confirmed_local_resume_preserves_recent_work_without_treating_merge_as_fresh(self):
        result = self.scenario("local-round-update")["result"]
        self.assertEqual("newer-work", result["recent"]["id"])
        self.assertEqual("confirmed-resume", result["round"])
        self.assertEqual(["older-work:1", "newer-work:7"], result["mergedKeys"])

    def test_switching_to_an_empty_room_clears_previous_recent_work(self):
        result = self.scenario("new-room")
        self.assertIsNone(result["result"]["recent"])
        self.assertEqual([], result["result"]["keys"])
        self.assertIsNone(result["result"]["cursor"])
        self.assertEqual(["restore-draft"], result["events"])

    def test_continue_conversation_only_focuses_and_scrolls_the_existing_composer(self):
        result = self.scenario("conversation")
        self.assertEqual(["focus:composerText", "scroll:composer"], result["events"])
        self.assertEqual([], result["selectedKeys"])
