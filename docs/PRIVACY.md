# Privacy and data

## What is stored where?

| Data | Location |
| --- | --- |
| Saved conversations, residents, rounds, sessions and draft versions | `home.sqlite` in your selected `--data-dir` |
| Unsaved composer/editor recovery | Browser local storage for this local app |
| Executable paths, workspaces, roles and provider bindings | Your local TOML configuration |
| Native provider sign-in and provider session files | The installed provider CLI's own storage |
| Source, original artwork, examples and documentation | This repository |

Home serves on loopback and uses a private cookie plus a separate origin-scoped browser proof, Host/Origin checks and CSRF protection. Every private API read/action requires both the cookie and proof. The proof stays in the tab's session storage; cookies alone cannot authenticate across localhost ports. Reload the authenticated tab, or restart the server for a fresh launcher when opening a new tab. See [security boundaries](../SECURITY.md).

New POSIX data roots/database files are created with private permissions. Existing permissions remain unchanged; check access to an existing/shared folder yourself. Windows uses inherited filesystem ACLs. Home does not encrypt the database.

## What leaves your computer?

Demo mode uses scripted fixtures and makes no AI calls.

In native mode, sending a message invokes your configured provider CLI. Your message, selected draft versions and bounded conversation context are supplied to that provider. Council also supplies the other participants' saved contributions for challenge and synthesis. Local storage does not mean offline AI inference.

Home does not collect API keys or copy authentication files. Native integrations and hooks have their own behavior; see [provider boundaries](PROVIDERS.md#execution-boundaries).

## Back up and restore your home

1. Stop active work, save important drafts, then stop the server with **Ctrl+C**.
2. Copy the entire selected data directory to a private backup location.
3. Keep the local provider configuration separately. Re-establish native CLI sign-in on the destination device.
4. Restore the copy and start Home with `--data-dir` pointing to it.

Saved text and versions travel with the database. Direct native continuation also depends on provider-owned session files; copying only the database or signing in on another device does not recreate those sessions. Cross-device native-session migration and a session-rebinding interface are not implemented. Treat this as a backup of saved records, not a complete provider migration. Unsaved browser drafts are not part of the database backup.

Do not run two Home processes against the same database. The application rejects cooperating duplicate ownership.

## Before publishing your own changes

Keep these private: `.env` files, local config, authentication, databases, histories, transcripts, provider output, launch URLs and diagnostic receipts. Screenshots can reveal conversation text even when a secret scanner passes.

The documented `.demo-data` and `.home-data` directories are ignored by Git. Ignore rules reduce accidents; force-adding a file can override them. Review the actual staged files and commit identity before pushing:

```sh
git diff --cached --stat
python scripts/check_public_tree.py --staged
python scripts/check_public_tree.py --history
```

The scanner reports paths and finding categories rather than matched secret values. History mode inspects all reachable commit trees and metadata from a complete checkout; a shallow clone is rejected. Known patterns and reviewed binary hashes still need human review for private prose, unknown credential formats and image contents. Deleting private content from the latest version alone does not remove older commits. See [publication coverage](../SECURITY.md#publication-checks).
