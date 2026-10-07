# Security and resource boundaries

KiFoundry Home is a local application for one owner. Version 0.1.1 fixes a localhost cookie-isolation flaw and adds resource bounds. Upgrade older copies before using them with private records, then restart the server and launch a fresh browser session.

## What protects the local API

- The listener binds to `127.0.0.1`. Host and Origin checks reject unexpected browser destinations.
- A one-use launch token establishes an HttpOnly, SameSite cookie and a separate proof. The browser keeps that proof in origin-scoped `sessionStorage` and sends it in `X-CSRF-Token` on **every** private API request, including reads and session renewal.
- Cookies are shared across ports. A cookie alone cannot renew the session, read records or invoke providers. The proof supplies the missing port/origin boundary.
- Reloading the authenticated tab works. A new tab without its proof needs a fresh launcher; restart the server to generate one. If browser storage is blocked, the current page works but a reload may require relaunching.
- Model/owner text is rendered as text, without HTML execution. Content Security Policy restricts page resources and framing. API errors omit raw provider stderr and internal exception details.
- HTTP actions cannot choose executables, process flags, workspaces, models or native session IDs. Provider bindings come from trusted local configuration.

These controls do not protect against an administrator, a compromised browser/extension, malicious native provider software or code already running with access to the owner's files. Native CLI hooks, MCP integrations and inherited settings remain trusted execution boundaries; see [provider limitations](docs/PROVIDERS.md#execution-boundaries). Conversation adapters are not a security sandbox. Keep the listener local rather than exposing it through a tunnel or proxy.

## Finite resource limits

| Resource | Bound |
| --- | --- |
| Admitted HTTP handler threads | 16; excess connections close before another handler starts |
| Socket inactivity | 10 seconds |
| Browser API wait | 15 seconds, including response-body reading |
| Active round drivers across rooms | 8 by default; Python integration may set 1–64 |
| Provider workers | 4 by default; Python integration may set 1–32 |
| Residents / Council participants | 64 / 2–64 |
| Calls per Council | At most `2N+1` |
| Room/version metadata page | 100 entries |
| Recent discussion / rounds | 200 messages / 50 round summaries |
| Draft/reply body | 64 KiB each |
| Provider prompt | 128 KiB |

Overloaded round submission fails before saving a new message or reactivating a stopped round. An identical request ID still returns its existing round. Calls waiting for the same provider identity do not occupy provider workers. With the default limits, a phase has at most 512 submitted calls across eight active rounds; actual execution remains limited to four workers.

Polling reads version metadata and progress summaries. Exact draft bodies load individually; a small browser cache retains recent bodies. Older conversation/version pages are requested explicitly. No history is deleted to enforce these read limits. Schema 3 adds room lookup indexes while retaining existing records.

These bounds do not establish large multi-user capacity. A deliberate local client can occupy the finite socket slots. Extremely large same-room version history still increases SQLite metadata sorting cost. Archived resident metadata is not paginated, saved history has no automatic disk quota, and explicitly loading many metadata pages increases browser work. Native provider quotas and latency remain independent limits.

## Protect stored data

Keep the database, provider configuration, native session files, launch URLs and browser recovery data private. New POSIX data roots use `0700`; new database/lock files use `0600`. Existing permissions are preserved. Windows privacy depends on inherited filesystem ACLs; POSIX mode bits do not establish Windows access control. The database is not encrypted by this application.

Use the backup procedure in [Privacy and data](docs/PRIVACY.md). Copying Home's database preserves records; it does not recreate native provider sessions on another device.

## Publication checks

```sh
python scripts/check_public_tree.py
python scripts/check_public_tree.py --staged
python scripts/check_public_tree.py --tracked
python scripts/check_public_tree.py --history
```

The modes inspect working files, the actual index, actual HEAD blobs and all reachable commit trees/metadata, respectively. History mode requires a complete Git checkout and rejects shallow history. Checks have finite file/object/byte limits and fail closed when inspection cannot finish. Findings report path/category, without matched values.

CI uses full history, reviewed action commit pins, read-only repository permissions and no persisted checkout credentials. Runtime has no third-party Python dependencies. Build/developer dependencies remain version ranges. Review prose, binaries, image metadata, commit identity and private content manually; pattern scanning cannot establish the absence of every possible secret. It does not inspect unreachable objects, deleted remote material, external services or provider-owned storage.

## Reporting

For a suspected credential exposure, revoke/rotate it through its provider and review history and other published copies. Removing the latest file alone does not remove old commits.

Do not place credentials, private transcripts or launch URLs in a public issue. Use private vulnerability reporting when the repository offers it, or agree on a private reporting route with its maintainer. A sanitized public bug report can describe affected versions and a synthetic reproduction.
