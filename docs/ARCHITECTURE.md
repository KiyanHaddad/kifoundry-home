# Architecture

## Decision: a separate portable core

The application separates saved data, provider adapters, Council orchestration and the town interface through small explicit contracts. Original assets and a self-contained runtime keep installation independent of other projects.

Python 3.11 and SQLite keep local process supervision and durable work in one application. Browser ES modules keep the first contributor setup small. Runtime dependencies are standard-library modules; developer checks are optional tools installed in a project environment. This is a deliberate starting decision, not a claim that this stack is universally best.

## Responsibilities

| Module | Owns |
| --- | --- |
| `models` | Agent identity, reply data and provider protocol |
| `store` | Schema migrations, resident registry/home slots, rooms, messages, rounds, turns, sessions and immutable draft versions |
| `residents` | Trusted adapter factories, provider-binding metadata and initial resident seeds |
| `council` | Registry dispatch, bounded phases, common context, attribution, partial failure and cancellation |
| `adapters` | Native command construction, actual output parsing, limits and owned process supervision |
| `config` | One to five trusted local provider bindings and initial seeds |
| `server` | Local HTTP authentication and validated route transport |
| `web/world-layout` and `web/world` | Saved-slot layout, paged neighborhoods, homes, avatars and displayed execution state |
| `web/resident-directory` | Search, Talk, Council invitations, add/archive/restore controls |
| `web/room` and `web/app` | Room payload normalization, conversations, selected guests and work comparison |

The browser selects residents and saved artifacts, never a process command, native session or arbitrary file. Model text remains inert. The server stores the owner message before scheduling work.

## Resident lifecycle

Trusted native TOML entries supply adapter factories and initial residents. Factories stay server-side; the browser receives a binding ID, label and provider. Adding a resident builds their own adapter and saves their ID, role and home slot. Registry mutations wait for all owned round drivers to finish, including calls exiting after Stop.

The town supports 64 active residents and Council can include all of them. Homes occupy persisted slots 0–63. The presentation groups those slots into five-home neighborhoods and renders transparent house illustrations over reusable terrain. Directory search covers every neighborhood. A neighborhood renders at most five selected guests, explicitly reporting any larger group. This rendering bound does not limit participation.

Archive releases the active slot and stops new dispatch while preserving history and per-room sessions. Restore uses the old slot if free, otherwise another free slot. Removing one resident never renumbers other active homes. A missing trusted binding leaves an active resident visible but unavailable. Restart seeds only IDs never registered, so archived configured residents remain archived.

## Council lifecycle

A request ID identifies one owner submission. Store uniqueness and payload comparison distinguish retries from mismatched reuse. An immutable context snapshot fixes the initial input and selected draft versions. Independent proposals precede peer critique; an attributed synthesis follows. The finite bound is `2N+1` calls for 2–64 participants, with four workers by default. The server advertises its actual limits to the browser.

Every assembled prompt fits 128 KiB. Fixed instructions, frozen context and every participant heading/status remain intact. The remaining space is divided fairly across saved peer replies, redistributing unused space from short replies. Long replies become explicit excerpts; their full text remains saved. The synthesis is told that excerpts may omit qualifications and cannot establish agreement. A request whose fixed framing cannot fit is refused before saving or launching.

Direct prompts always include bounded saved room history, including intervening Council discussion. They resume the resident's own direct session. Fresh Council phase sessions never replace that direct-session identity.

Failure/cancellation retain saved contributions. Startup recovery must mark uncertain work interrupted and must not automatically replay it. Cooperative session serialization does not control unrelated native terminal sessions. The database lock prevents two cooperating Home servers from performing competing recovery.

## Storage and migration

Schema versions are explicit. Schema 2 adds the resident registry, unique active home slots, round participant snapshots and historical message names/providers through an incremental migration from schema 1. A future unknown schema is rejected without rewriting it. Existing history is retained; older rows have no new identity snapshot and use fallback attribution.

New rounds freeze each participant's name, provider and role. Completed replies record their speaker name and reported provider, so archive/restore and later registry changes cannot rewrite saved attribution. Draft updates append a version and require the expected previous version. Context captures exact selected versions so editing a draft cannot silently change a running Council. HTTP room payloads nest all versions under each latest artifact; the browser normalizes this shape at one boundary.

Store owns the cooperating database lock. It prevents a second Home process from performing competing recovery against that database; it does not control unrelated provider terminals.

Future data imports require an explicit migration that preserves the source. Provider memory and session histories are never copied implicitly.

## Extension discipline

Residents are persisted data created through trusted bindings. Providers implement one protocol. Council policy remains one explicit state machine until a second real policy justifies an abstraction. Skills/plugins later expose a named usable capability through a documented invocation.

Registry, layout and fixture tests establish mechanics. Actual native-provider journeys, current-revision visual checks, owner acceptance and publication remain separate evidence gates.
