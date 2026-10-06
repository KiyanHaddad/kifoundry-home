# Privacy and data

## What is stored where?

| Data | Location |
| --- | --- |
| Saved conversations, residents, rounds, sessions and draft versions | `home.sqlite` in your selected `--data-dir` |
| Unsaved composer/editor recovery | Browser local storage for this local app |
| Executable paths, workspaces, roles and provider bindings | Your local TOML configuration |
| Native provider sign-in and provider session files | The installed provider CLI's own storage |
| Source, original artwork, examples and documentation | This repository |

Home serves on loopback and uses a private launch cookie, Host/Origin checks and CSRF protection. It is intended for local use. Do not expose the server through a public tunnel as a multi-user service.

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
```

The scanner reports paths and finding categories rather than matched secret values. It checks known patterns and reviewed binary hashes; a clean result still needs human review for private prose, unknown credential formats and image contents. Check Git history as well as the current files if private content was ever committed. Deleting it from the latest version alone does not remove older commits.
