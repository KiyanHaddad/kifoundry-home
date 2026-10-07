# Contributor contracts

This is the integration reference for contributors changing the backend or town interface. For installation and everyday use, start with the [README](../README.md). For the reasoning behind the module boundaries, see [Architecture](ARCHITECTURE.md).

The runtime uses Python 3.11+, SQLite and browser ES modules. It requires no frontend build or third-party Python runtime package. Update these contracts and their consumers together when changing behavior.

## Terms

| Term | Meaning |
| --- | --- |
| Resident | A saved identity with a name, role, provider binding and home slot. |
| Binding | Trusted server-side setup that constructs a provider adapter. Several residents may use one binding. |
| Room | A saved conversation, its rounds and its versioned work. |
| Round | One submitted message and its bounded provider calls. |
| Turn | One resident's provider call in a round phase. |
| Artifact | A saved text draft with immutable versions. |
| Fixture | An explicitly labelled resident that returns scripted replies. |

## 1. Module boundaries

| Module | Responsibility |
| --- | --- |
| [`home/models.py`](../home/models.py) | Frozen identity/reply types, provider protocol, limits and safe errors. |
| [`home/store.py`](../home/store.py) | SQLite migrations, transactions, registry, rooms, turns, sessions, draft versions and startup recovery. |
| [`home/residents.py`](../home/residents.py) | Trusted adapter factories and initial resident seeds. |
| [`home/config.py`](../home/config.py) | Trusted local TOML configuration. |
| [`home/council.py`](../home/council.py) | Resident dispatch, bounded phases, attribution, cancellation and resume. |
| [`home/adapters/`](../home/adapters/) | Native command construction, response parsing, limits and owned processes. |
| [`home/server.py`](../home/server.py), [`home/cli.py`](../home/cli.py) | Local transport, authentication and application startup. Domain behavior stays in Store and Council. |
| [`home/web/`](../home/web/) | Town navigation, directory, conversation, Council selection and draft editor. |

Keep SQL in Store. The browser sends the documented HTTP actions; it does not construct provider commands or access arbitrary files.

### Provider interface

`Agent` and `Reply` are frozen dataclasses with these fields:

```text
Agent(id: str, name: str, provider: str, role: str = "")
Reply(text: str, provider: str,
      session_id: str | None = None, model: str | None = None)
```

An adapter implements:

```python
provider: str

def generate(prompt: str, session_id: str | None,
             cancel: threading.Event) -> Reply: ...

def identity_key(session_id: str | None) -> str: ...
```

- `generate` observes cancellation. It raises `ProviderError` with a safe summary, or `Cancelled`, instead of returning partial text as a completed reply.
- `identity_key` serializes aliases of the same actual provider session across residents and rooms. Fresh resident sessions must have distinct keys.
- Council validates the returned provider, session identity, non-empty text and reply size before saving it. Session/model fields describe what the provider reported.
- Each managed resident receives a separate adapter instance. Native CLI authentication remains with the installed CLI; this project does not request or copy an API key.
- Native conversation adapters reject unexpected tool events. Event detection cannot undo an action a CLI already started, so it is not a sandbox guarantee. Process cancellation targets only the process tree launched by the adapter; it never kills a saved PID from an earlier run.

### Trusted resident construction

`ResidentBinding(id, label, provider, factory, addable=True)` keeps `factory(name)` on the server. Its browser representation contains only `id`, `label` and `provider`. `Seed(agent, binding_id)` registers an initial resident.

Native TOML uses one to five `[[agents]]` entries for bindings and initial seeds. This setup limit is separate from the town's 64 active residents. Each binding can construct additional residents; provider account quotas still apply. Legacy static adapters remain supported, but are not offered as addable bindings.

## 2. Resident lifecycle

| Action | Required behavior |
| --- | --- |
| Add | Generate a stable resident ID on the server and assign the first free active home slot. Accept an existing addable `binding_id` only. |
| Archive / Move out | Remove the resident from active selection and dispatch; preserve messages, rounds, draft history and per-room sessions. Release the active slot. |
| Restore / Bring back | Require the matching trusted binding and a free slot. Prefer the previous slot; otherwise choose the first free slot. |
| Restart seeds | Insert only IDs never registered. Preserve saved rows and archives. If the town is full, defer new seeds until a later restart with space. Existing homes still open and bindings remain available. |
| Missing binding | Keep the active resident visible and mark them unavailable for dispatch. |

Active `home_slot` values are unique integers from 0 through 63. Adding, archiving or restoring one resident never moves other active residents.

Names must be non-empty and no longer than 60 characters. Roles are limited to 4 KiB of UTF-8 text. Fixture names remain explicitly marked. Browser actions cannot set a provider, executable, workspace, model or native session ID.

Registry changes require every owned round driver to finish, including calls still exiting after Stop. A round freezes each participant's `{name, provider, role}`. New messages save speaker names and providers, so later registry changes cannot rewrite attribution. Schema-1 messages have no new snapshot data and use fallback attribution.

## 3. Conversation and Council behavior

### Starting a round

1. Validate the input, participant uniqueness and availability, room ownership of selected artifacts, and fixed prompt framing before a provider launch.
2. Save the message, request ID, participant snapshots, exact selected artifact versions and bounded starting context in a transaction.
3. Schedule the work and return the saved round without waiting for provider completion.

Only one round may be active in a room. Repeating a `request_id` with an identical payload returns its saved round; reusing it with a different payload is rejected. Unknown, archived, unavailable or duplicate participants are rejected before dispatch.

### Direct conversation

Direct mode selects exactly one participant and schedules at most one reply call. Each prompt includes bounded saved room history, including Council replies added since that resident last spoke directly. Direct mode resumes that resident's per-room session. Fresh Council sessions never replace the direct session.

### Council phases

For `N` participants, where `2 <= N <= 64`:

| Phase | Who speaks | What they receive |
| --- | --- | --- |
| Proposal | Every selected participant, independently and in parallel. | The same frozen starting context; only resident persona framing differs. |
| Critique | Participants whose proposals completed, if at least two proposals succeeded. | The frozen context and all saved proposal outcomes, with attribution and failure status. |
| Synthesis | First selected participant with a completed critique; otherwise the first with a completed proposal. | The frozen context and saved proposal/critique outcomes. |

The limit is **at most `2N+1` calls**, with four concurrent workers and eight active round drivers across rooms by default. Worker limits must be integers 1–32; active-driver limits 1–64. Capacity is checked before saving/reactivating, while identical request retries still return their saved round. Identity reservations happen before executor submission, so aliases waiting for a busy session do not occupy workers. There are no recursive automatic rounds. A Council with one successful proposal preserves it and skips critique/synthesis. With no successful proposals, it ends failed or interrupted according to the saved outcomes.

Actual replies retain speaker, provider, phase and reported session/model. Successful contributions survive other participants' failures. Synthesis is instructed to attribute points, preserve disagreements in an `Unresolved` section, and avoid inventing votes or agreement. These instructions do not guarantee model compliance.

### Budgets and context

Text size limits use UTF-8 bytes unless stated otherwise.

| Limit | Value |
| --- | --- |
| Active residents / Council participants | 64 / 2–64 |
| Calls per direct / maximum Council round | 1 / 129 |
| Owner message | 16 KiB |
| One artifact | 64 KiB |
| Selected artifacts per round | 8 distinct artifacts |
| Frozen shared context | 48 KiB |
| Assembled provider prompt | 128 KiB |
| Saved provider reply | 64 KiB |
| Room/artifact title | 200 characters |
| Request ID | 1–128 characters |

The message and selected work remain intact in the shared context. If they cannot fit, reject the request. Older history is omitted by whole message, with the omission stated. Native stdout/stderr and call duration are bounded; a call has a finite configured timeout.

For critique and synthesis, preserve fixed instructions/context and every participant heading/status. Divide remaining prompt space fairly among peer replies, redistributing unused space from short replies. Shortened replies are explicitly marked as excerpts, and full replies stay unchanged in storage. Instructions state that excerpts may omit qualifications and cannot establish agreement. Reject oversized fixed framing before saving or launching the round.

## 4. Stop, resume and restart recovery

Round and turn states are `queued`, `running`, `completed`, `failed`, `cancelled` and `interrupted`. A turn also records whether it was launched.

| Situation | Behavior |
| --- | --- |
| Stop | Signal owned work to cancel, keep completed replies and prevent later phases. An actual final reply that arrives during Stop can still be saved. |
| Server close | Request cancellation and join owned drivers with a time bound. Unfinished work is recovered at the next startup. |
| Startup recovery | Mark unfinished rounds/turns interrupted. Do not relaunch providers or kill an old stored PID. |
| Safe resume | Reuse completed/failed turns, run work that never launched, and continue eligible later stages. Do not repeat a launched call whose result is unknown. |
| Explicit Python integration retry | `retry_interrupted=True` may repeat uncertain calls, with a possible duplicate. This option is unavailable through the browser or HTTP route. |

Resume requires a cancelled/interrupted round, active and available participants, no driver still exiting for that round, and no other active round occupying its room. Its saved participant snapshots remain authoritative; a changed provider must not silently serve an old round.

Store owns a cooperating database lock to prevent two Home servers from performing competing recovery. Provider identity locks serialize cooperating in-app calls; they cannot control an unrelated terminal resuming the same native session.

## 5. Persistence interface

`Store(path: Path | str)` owns schema migrations and returns JSON-serializable dictionaries from its public record operations. Schema 2 adds the registry; schema 3 adds lookup indexes. Both incrementally preserve history. An unknown future schema is rejected without rewriting it.

| Operation | Result / rule |
| --- | --- |
| `create_room(title="Commons")` | `{id, title, created_at}`. |
| `list_rooms()` | Room summaries, including `active_round_id`. |
| `room(room_id)` | Room metadata, recent messages/rounds and all saved artifact versions. Default readback is the latest 200 messages and 50 rounds; `earlier_messages` counts omitted messages. This does not delete older records. |
| `list_rooms_page(before=None)` | Up to 100 newest room summaries and `next_room_cursor`. |
| `room_for_browser(room_id)` | Recent messages/round summaries plus 100 version metadata records and `next_artifact_cursor`; no duplicate turn bodies or native session IDs. |
| `artifact_page(room_id, before=None)` | Up to 100 version metadata records and a next cursor. Bodies are not read into the response. |
| `artifact_version(room_id, artifact_id, version)` | One exact immutable body with authoritative `latest_version`; reject cross-room access. |
| `save_artifact(room_id, title, content, artifact_id=None, expected_version=None)` | Create version 1 or append an immutable version. Updating requires the current `expected_version`; a conflict must not overwrite history. |
| `residents()` | All registry rows, including archives. |
| `seed_residents(rows)` | Apply the restart-seeding rules above. |
| `add_resident(resident_id, name, provider, role, binding_id)` | Persist a resident in the first free slot. Council performs public-action validation first. |
| `set_resident_archived(resident_id, archived)` | Persist archive/restore state without deleting history or shifting other homes. |

Store also owns the internal round/turn, session and recovery operations. Keep their transactional invariants here rather than spreading SQL through other modules. Importing provider memory or session history requires an explicit migration; it must never happen implicitly.

### Council interface

```python
Council(store, agents=None, adapters=None, max_workers=4,
        *, bindings=None, seeds=None, max_active_rounds=8)
```

Managed integrations supply `bindings` and `seeds`. The `agents`/`adapters` arguments remain supported for static integrations.

| Operation | Result / rule |
| --- | --- |
| `start(room_id, text, participants, request_id, mode="council", artifact_ids=None)` | Return a saved round after scheduling. |
| `cancel(round_id)` | Return the stopped round. |
| `resume(round_id, retry_interrupted=False)` | Return the resumed round under the recovery rules above. |
| `close(timeout=10.0)` | Stop and join owned work with a bound. |
| `agents_info(include_archived=False)` | Resident identity, role, binding ID, home slot, archive state and local `available` flag. No private configuration. |
| `bindings_info()` | Addable trusted bindings as `{id, label, provider}`. |
| `add_resident(name, role, binding_id)` / `archive_resident(id)` / `restore_resident(id)` | Validated registry changes and resident info. |
| `capabilities_info()` | Actual execution limits advertised to the browser. |

Construction recovers persisted unfinished rounds without relaunching them. `available` means a local adapter/binding exists; it does not verify native authentication or account quota.

## 6. Local HTTP API

The server binds to loopback only. Host/Origin validation, a private cookie and a separate origin-scoped proof guard the API. Cookies are `HttpOnly`, `SameSite=Strict` and named with the actual bound port. Cookies are shared across ports, so the cookie alone cannot authorize private requests. At most 16 HTTP handlers are admitted before reading headers; inactive sockets time out after 10 seconds.

`GET /api/session` exchanges a valid one-use launcher token for `{csrf}` and a cookie. Renewal requires both the existing cookie and `X-CSRF-Token`. The browser retains this proof in origin-scoped session storage and sends it on every private API GET/POST. All POST bodies must be JSON objects. Unexpected action fields are rejected. There is no arbitrary filesystem route. Reloading the authenticated tab works; a new tab without proof needs a fresh launcher.

| Method | Route | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/state` | — | Residents, archives, bindings, capabilities, 100 room summaries/next cursor, initial browser room and `fixture` flag. |
| GET | `/api/rooms?before=<cursor>` | — | 100 room summaries and `next_room_cursor`. |
| GET | `/api/rooms/<id>` | — | Saved room with bounded history, round summaries, 100 version metadata records and next cursor. |
| GET | `/api/rooms/<id>/artifacts?before=<cursor>` | — | 100 version metadata records and `next_artifact_cursor`. |
| GET | `/api/rooms/<id>/artifacts/<artifact>/versions/<version>` | — | Exact immutable body and authoritative `latest_version`. |
| POST | `/api/rooms` | `{title}` | New room summary. |
| POST | `/api/rooms/<id>/rounds` | `{text, participants, request_id, mode, artifact_ids?}` | Saved round. |
| POST | `/api/rounds/<id>/cancel` | `{}` | Stopped round. |
| POST | `/api/rounds/<id>/resume` | `{}` | Safely resumed round; no uncertain-call retry option. |
| POST | `/api/agents` | `{name, role, binding_id}` | New resident info. |
| POST | `/api/agents/<id>/archive` | `{}` | Archived resident info. |
| POST | `/api/agents/<id>/restore` | `{}` | Restored resident info. |
| POST | `/api/rooms/<id>/artifacts` | `{title, content, artifact_id?, expected_version?}` | Saved artifact version. |

Errors use `{"error": "human-readable safe summary"}` with an appropriate 4xx/5xx status. Raw provider stderr, credentials and private configuration must not appear in error summaries.

### Example: submit a Council

This is an illustrative JSON body, not a complete authenticated request. Replace IDs with values from the current local state; `artifact_ids` may be omitted.

```json
{
  "text": "Compare these two directions and keep any disagreements visible.",
  "participants": ["resident-a", "resident-b"],
  "request_id": "example-submission-1",
  "mode": "council",
  "artifact_ids": []
}
```

Keep the same request ID for retrying the same submission. Use a new ID for a new message.

### Example: save a revision

```json
{
  "title": "Opening draft",
  "content": "The revised opening goes here.",
  "artifact_id": "example-artifact-id",
  "expected_version": 1
}
```

For a new artifact, omit both `artifact_id` and `expected_version`. A stale `expected_version` returns a conflict; reload and compare before saving.

### Response shapes shared with the frontend

| Record | Stable fields |
| --- | --- |
| State | `agents`, `archived_agents`, `resident_bindings`, `capabilities`, `rooms`, `next_room_cursor`, `room`, `fixture`. |
| Capabilities | `max_residents`, `max_participants`, `max_provider_calls`, `max_workers`, `max_active_rounds`, `max_prompt_bytes`. Standard registry limits are 64, 64, 129 and 131072 bytes; worker/driver counts reflect configuration. |
| Resident | `id`, `name`, `provider`, `role`, `binding_id`, `home_slot`, `archived`, `available`. |
| Message | `id`, `role` (`owner`/`agent`/`system`), `agent_id`, `agent_name`, `agent_provider`, `phase`, `content`, `round_id`, `created_at`. Speaker/phase fields may be null. |
| Round | `id`, `room_id`, `request_id`, `status`, `mode`, `participants`, `participant_snapshots`, `artifacts`, `context_sha256`, `context_bytes`, `owner_message_id`, `max_calls`, `synthesizer`, `note`, timestamps and `turns`. |
| Browser turn | `id`, `round_id`, `agent_id`, `phase`, `status`, `launched`, `error`, `provider`, timestamps. Full trusted Store readback also contains `content`, `session_id` and `model`. |
| Artifact metadata | `id`, `title`, `version`, `latest_version`, `sha256`, `created_at`. Exact-body lookup additionally contains `content`. |

Browser room `artifacts` are flat version metadata, newest 100 first; `next_artifact_cursor` enables explicit older-page requests. Bodies load on selection/comparison and are cached with a small bound. Attachment eligibility uses authoritative `latest_version`, not the newest version currently loaded in the browser. Trusted `Store.room` still nests every immutable body under the latest artifact's `versions` array; [`room.js`](../home/web/room.js) accepts either shape. Selected artifacts in a round identify exact frozen versions. Browser round snapshots retain name/provider, omitting private roles.

## 7. Frontend integration rules

- Render user/model content as text. Do not execute it as HTML, code or a provider command.
- Use saved slots for layout. `world-layout.js` groups homes into neighborhoods of five plots, and appearance stays stable by resident ID.
- Rendering at most five selected guests does not cap Council participation. Report additional participants and use the server's advertised execution limits for budgets.
- Reopen the browser's remembered room when available. If creating a room succeeds but its readback fails, retry opening that confirmed room rather than creating another.
- `recoveryInfo(round)` derives safe eligibility, uncertain launched-call count and a conservative remaining-call bound from saved states. The recovery selector uses saved participant snapshots and preserves the current draft.
- Post `{}` for resume. Adopt a confirmed resume response before optional readback, so a failed readback does not prompt duplicate dispatch.
- When temporarily disabled controls are restored, restore lost keyboard focus only if focus fell to the document body. Keep focus visible and preserve keyboard, reduced-motion and compact-screen access.

## 8. Evidence and public-data boundary

Examples, tests and assets must contain no private histories, real provider sessions, credentials or private binding configuration. Fixture mode stays visibly labelled and never establishes live-provider success. Parsing/process tests establish adapter mechanics; real-provider journeys require separate evidence. Keep private smoke receipts outside the public tree.

See [Verification](VERIFICATION.md) for checks already performed and [Known limitations](KNOWN-LIMITATIONS.md) for unverified behavior.
