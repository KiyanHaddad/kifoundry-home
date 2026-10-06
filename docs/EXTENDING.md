# Extend the home

## Add a resident

Open the resident directory and choose **Add resident**. Give them a name and role, then select an existing provider connection. The town supports up to 64 active residents. Use **Talk** for a direct conversation, **Invite to Council** for individual guests, or **Invite all** for the available town. The composer shows the `2N+1` call budget before Send. A specialist backed by Claude remains labelled Claude; fixture residents remain explicitly marked as simulated.

Use **Move out** to archive a resident while keeping their conversations and saved sessions. **Bring back** restores the same ID, preferring the previous home slot if free. Other active homes stay where they are. Changes wait for all current conversations and owned calls to finish.

## Configure a provider connection

Add a `[[agents]]` entry to your ignored local TOML with a unique ID, display name, supported provider, role and existing workspace. The current native providers are `claude` and `codex`. Native configuration accepts one to five entries; each supplies a trusted binding and an initial resident, and can create further residents through the directory. Each managed resident receives a separate adapter; direct session continuity is stored per room and resident.

Keep roles short and concrete. Executable paths, workspace, timeout and provider settings remain trusted local setup. The browser selects an existing binding ID and cannot replace these settings. Removing a binding makes its registered residents unavailable without deleting them. Add a config validation case when introducing a new field.

## Change the town layout

Use saved `home_slot` values as the location authority. `home/web/world-layout.js` maps them into five-home neighborhoods; `world.js` renders homes, avatars and saved execution state. Preserve ID-based avatar appearance and existing slots when filtering or changing the population. Keep the visible Council cast bounded while preserving every selected guest in actual dispatch and the directory. Check 7- and 64-resident cases, slot reuse and archived residents. Asset variants and transparency are documented in ASSETS.md.

Changing registry fields requires a numbered Store migration, updated HTTP/consumer contracts and migration tests. Preserve participant snapshots and saved speaker attribution. Do not rewrite historical replies from the current roster.

## Add a provider

Implement the protocol in `home/models.py`: `generate(prompt, session_id, cancel)` returns the actual `Reply`, and `identity_key(session_id)` identifies a cooperating session for serialization. Use the native adapters as an example of bounded process handling. Preserve identity, cancellation, finite limits and sanitized failures.

Add contract tests proving actual reply parsing, wrong-session rejection, timeout, output limits and owned cancellation. Register the adapter in the local CLI factory and supported config validation. This registration is explicit; there is no dynamic third-party code loader.

Fixtures test mechanics. A separate opt-in real-provider check is necessary before advertising verified integration.

## Add a Council policy

First implement a real second policy with an owner outcome and meaningful test. Its first context must be explicit; attribution and saved outcomes must remain intact. Then extract the smallest shared phase contract. Do not create a policy framework for hypothetical plugins.

## Add a skill or capability

Define the user action, supported invocation, authority boundary, expected result and failure behavior. Keep conversation as the ordinary entrance. Do not expose an attractive control until it performs that actual invocation and returns its result inside the home.
