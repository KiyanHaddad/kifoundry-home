# KiFoundry Home

Build a shared AI home: natural resident conversations, genuine Council discussions, saved work and continuity. The town is the interaction space.

Read `docs/PRODUCT.txt` and `docs/CONTRACTS.txt` before changing behavior. Preserve existing user data. Public code must contain no personal paths, account identities, private sessions, credentials or private assets.

Separate persistence, orchestration, provider adapters, HTTP and world UI. Use one writer per file. Test user behavior and failure semantics; fixture responses never establish live-provider success. Update documentation and known limitations with meaningful changes. Do not add an extension framework before a concrete integration requires one.

No publishing, account changes, credentials, model-setting changes, external messages or destructive operations without actual owner scope. This file grants no new authority.
