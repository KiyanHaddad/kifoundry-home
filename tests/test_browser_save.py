"""Exercise actual browser save/recovery functions with controlled transport failures."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
APP = Path(__file__).resolve().parents[1] / "home" / "web" / "app.js"

SCENARIOS = r"""
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source = readFileSync(process.argv[1], 'utf8');
const scenario = process.argv[2];
function extract(start, end) {
  if (source.split(start).length !== 2) throw Error('Function boundary is ambiguous: ' + start);
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length);
  if (to < 0) throw Error('Function boundary is missing: ' + end);
  return source.slice(from, to);
}
const functions = [
  extract('async function saveArtifact(event) {', 'async function createRoom(event) {'),
  extract('function persistDraft() {', 'function restoreDraft() {'),
  extract('function recoverEditedWork() {', 'function useMessageAsDraft(content) {'),
].join('\n');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:'', textContent:'', disabled:false, focus() {}});
  return elements.get(id);
}
element('artifactTitle').value = 'Synthetic edited draft';
element('artifactContent').value = 'Synthetic edited text';
const state = {room:{id:'synthetic-room', artifacts:[]}, editKey:'', editDirty:true,
  attachedId:'', saving:false, loadingArtifact:false, unresolvedArtifact:false,
  artifactLoadEpoch:0, artifactBodies:new Map()};
const saved = new Map(), storage = new Map(), requests = [], notices = [];
let created = 0, deferred;
const artifactKey = artifact => artifact.id + ':' + artifact.version;
function selectedArtifact() {
  return state.room.artifacts.find(item => artifactKey(item) === state.editKey) || null;
}
function saveOnServer(body) {
  const id = body.artifact_id || 'synthetic-created-' + (++created);
  const versions = saved.get(id) || [];
  const current = versions.at(-1)?.version || 0;
  if (body.artifact_id && body.expected_version !== current) throw Error('Stale version conflict');
  const artifact = {id, version:current + 1, title:body.title, content:body.content, sha256:'synthetic-hash'};
  versions.push(artifact); saved.set(id, versions);
  return artifact;
}
if (scenario === 'revision' || scenario === 'post-failure') {
  const existing = {id:'synthetic-existing', version:4, title:'Synthetic saved draft', content:'Synthetic saved text'};
  saved.set(existing.id, [existing]);
  state.room.artifacts.push({...existing, latest_version:4});
  state.editKey = artifactKey(existing); state.attachedId = existing.id;
}
const context = {state, TextEncoder, console, $:element, artifactKey, selectedArtifact,
  document:{body:{}, activeElement:{}},
  cacheArtifact: artifact => state.artifactBodies.set(artifactKey(artifact), artifact),
  renderArtifacts() {}, updateComposer() {}, toggle() {},
  adoptRoom() {throw Error('A failing readback must not be adopted');},
  recoveryKey: () => 'synthetic-recovery',
  storageRead: key => storage.get(key) || null,
  storageWrite: (key, value) => value === null ? storage.delete(key) : storage.set(key, value),
  showError: (_id, message='') => notices.push(message),
  async api(path, body) {
    requests.push({path, body});
    if (body === undefined) throw Error('Synthetic readback unavailable');
    if (scenario === 'post-failure') throw Error('Synthetic POST unavailable');
    if (scenario === 'pending-recovery') return new Promise(resolve => {deferred = () => resolve(saveOnServer(body));});
    return saveOnServer(body);
  },
};
runInNewContext(functions + '\nglobalThis.auditFunctions={saveArtifact,recoverEditedWork};', context);
const {saveArtifact, recoverEditedWork} = context.auditFunctions;
const event = {preventDefault() {}};
let afterFirst, duringSave;
if (scenario === 'pending-recovery') {
  const recovery = JSON.stringify({editKey:'', title:'Synthetic recovery', content:'Synthetic recovered text'});
  storage.set('synthetic-recovery', recovery);
  const pending = saveArtifact(event);
  if (!state.saving || typeof deferred !== 'function') throw Error('Save did not reach the controlled pending POST');
  recoverEditedWork();
  duringSave = {saving:state.saving, editor:element('artifactContent').value,
    recovery:storage.get('synthetic-recovery'), expectedRecovery:recovery};
  deferred(); await pending;
} else {
  await saveArtifact(event);
  afterFirst = {key:state.editKey, dirty:state.editDirty, attachedId:state.attachedId,
    storedDraft:storage.get('kifoundry-home:draft:synthetic-room'),
    cacheKeys:[...state.artifactBodies.keys()], notices:[...notices]};
  if (scenario !== 'post-failure') {
    element('artifactContent').value = 'Synthetic next edit'; state.editDirty = true;
    await saveArtifact(event);
  }
}
process.stdout.write(JSON.stringify({afterFirst, duringSave, state:{key:state.editKey, dirty:state.editDirty,
  saving:state.saving, attachedId:state.attachedId, editor:element('artifactContent').value},
  posts:requests.filter(request => request.body !== undefined),
  server:[...saved.values()], notices, recovery:storage.get('synthetic-recovery')}));
"""


@unittest.skipUnless(NODE, "Node.js is required for browser save/recovery checks")
class BrowserSaveTests(unittest.TestCase):
    def scenario(self, name):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", SCENARIOS, str(APP), name],
            capture_output=True, encoding="utf-8", timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        return json.loads(process.stdout)

    def test_confirmed_new_draft_survives_failed_refresh_and_next_save_is_a_revision(self):
        result = self.scenario("new")
        first = result["afterFirst"]
        self.assertEqual("synthetic-created-1:1", first["key"])
        self.assertFalse(first["dirty"])
        self.assertEqual("synthetic-created-1", first["attachedId"])
        self.assertIn(first["key"], first["cacheKeys"])
        stored = json.loads(first["storedDraft"])
        self.assertEqual((first["key"], False), (stored["editKey"], stored["dirty"]))
        self.assertIn("was saved", first["notices"][-1])
        self.assertNotIn("artifact_id", result["posts"][0]["body"])
        self.assertEqual(("synthetic-created-1", 1),
                         (result["posts"][1]["body"]["artifact_id"],
                          result["posts"][1]["body"]["expected_version"]))
        self.assertEqual(1, len(result["server"]), "A failed readback must not create another draft")
        self.assertEqual([1, 2], [version["version"] for version in result["server"][0]])

    def test_confirmed_revision_advances_expected_version_before_failed_refresh(self):
        result = self.scenario("revision")
        self.assertEqual("synthetic-existing:5", result["afterFirst"]["key"])
        self.assertFalse(result["afterFirst"]["dirty"])
        self.assertEqual([4, 5], [post["body"]["expected_version"] for post in result["posts"]])
        self.assertEqual([4, 5, 6], [version["version"] for version in result["server"][0]])
        self.assertNotIn("Stale version conflict", " ".join(result["notices"]))

    def test_failed_post_keeps_the_original_selection_and_unsaved_edit(self):
        result = self.scenario("post-failure")
        self.assertEqual("synthetic-existing:4", result["state"]["key"])
        self.assertTrue(result["state"]["dirty"])
        self.assertEqual("Synthetic edited text", result["state"]["editor"])
        self.assertEqual([], result["afterFirst"]["cacheKeys"])
        self.assertEqual([4], [version["version"] for version in result["server"][0]])
        self.assertIn("draft is kept", result["notices"][-1])
        self.assertFalse(result["state"]["saving"])

    def test_recovery_cannot_replace_or_erase_an_edit_while_its_save_is_pending(self):
        result = self.scenario("pending-recovery")
        during = result["duringSave"]
        self.assertTrue(during["saving"])
        self.assertEqual("Synthetic edited text", during["editor"])
        self.assertEqual(during["expectedRecovery"], during["recovery"])
        self.assertEqual(during["expectedRecovery"], result["recovery"])
        self.assertEqual("synthetic-created-1:1", result["state"]["key"])
        self.assertFalse(result["state"]["saving"])
