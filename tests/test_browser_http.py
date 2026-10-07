"""Exercise the browser transport against controlled fetch/storage boundaries."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "http.js"

SCENARIOS = """
const {requestJSON, readSessionProof, saveSessionProof} = await import(process.argv[1]);
const proof = 'synthetic-browser-proof';
const data = new Map();
globalThis.sessionStorage = {getItem: key => data.get(key), setItem: (key, value) => data.set(key, value)};
saveSessionProof(proof);
const readBack = readSessionProof();
let captured;
globalThis.fetch = async (path, options) => {
  captured = {path, credentials: options.credentials, headers: options.headers, method: options.method, body: options.body};
  return {ok:true, json: async () => ({saved:true})};
};
const result = await requestJSON('/api/state', {csrf:readBack});
const get = captured;
await requestJSON('/api/rooms', {csrf:readBack, body:{title:'Synthetic room'}});
const post = captured;
globalThis.sessionStorage = {getItem: () => {throw Error('blocked');}, setItem: () => {throw Error('blocked');}};
saveSessionProof(proof);
const blockedStorage = readSessionProof();
globalThis.fetch = (_path, options) => new Promise((_resolve, reject) => {
  options.signal.addEventListener('abort', () => reject(Error('aborted')), {once:true});
});
let timeout;
try {await requestJSON('/api/state', {csrf:proof, timeoutMs:20});} catch(error) {timeout=error.message;}
globalThis.fetch = async (_path, options) => ({ok:true, json: () => new Promise((_resolve, reject) => {
  options.signal.addEventListener('abort', () => reject(Error('body stalled')), {once:true});
})});
let bodyTimeout;
try {await requestJSON('/api/state', {csrf:proof, timeoutMs:20});} catch(error) {bodyTimeout=error.message;}
globalThis.fetch = async () => ({ok:false, status:404, json:async () => ({error:'Safe rejection'})});
let rejection, rejectionStatus;
try {await requestJSON('/api/state', {csrf:proof});} catch(error) {rejection=error.message; rejectionStatus=error.status;}
process.stdout.write(JSON.stringify({result, get, post, readBack, blockedStorage, timeout, bodyTimeout, rejection, rejectionStatus}));
"""


@unittest.skipUnless(NODE, "Node.js is required for browser transport checks")
class BrowserHTTPTests(unittest.TestCase):
    def test_proof_headers_reload_storage_and_finite_fetch_body_wait(self):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", SCENARIOS, MODULE.as_uri()],
            capture_output=True, encoding="utf-8", timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual({"saved": True}, result["result"])
        self.assertEqual(result["readBack"], result["get"]["headers"]["X-CSRF-Token"])
        self.assertEqual("same-origin", result["get"]["credentials"])
        self.assertNotIn("method", result["get"])
        self.assertEqual("POST", result["post"]["method"])
        self.assertEqual({"title": "Synthetic room"}, json.loads(result["post"]["body"]))
        self.assertEqual("", result["blockedStorage"])
        self.assertIn("timed out", result["timeout"])
        self.assertIn("timed out", result["bodyTimeout"])
        self.assertEqual("Safe rejection", result["rejection"])
        self.assertEqual(404, result["rejectionStatus"])
