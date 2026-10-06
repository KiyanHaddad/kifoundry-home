# Native providers

Install and sign in to Claude Code or Codex through the provider's supported flow. Home does not collect passwords, API keys or auth files. Executable and workspace bindings live in ignored local configuration.

The adapters invoke native CLIs without a shell, parse actual completion/session metadata, bound input/output, enforce a deadline and supervise owned cancellation. They omit hardcoded model selection. A resumed result must report the requested session; a mismatch is a failure.

Claude's programmatic interface supports print mode, structured output and exact session resume. [Official Claude Code documentation](https://code.claude.com/docs/en/headless).

Codex's non-interactive interface supports JSON events and exact resume. Read-only execution is its documented default. [Official Codex documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

## Important limits

Conversation adapters reject unexpected action events. This detection cannot undo an action already started. Native hooks and inherited integrations may act outside that event boundary; read-only/never policy is not a universal no-tool guarantee. See `home/adapters/LIMITATIONS.txt` for the implemented boundary.

Owned process-tree cancellation is tested separately from provider behavior. Windows starts a process before attaching its owned Job Object, leaving a startup interval. No saved PID is treated as authority to kill an unrelated process.

New sessions belong to this application. They do not become an existing private Claude identity or the current desktop Codex chat. Binding an existing private session requires an explicit private integration and ownership checks; it is not shipped in example configuration.

Binary presence, authentication, successful reply and continuity are different evidence. Fixture tests do not establish account access. Live smoke checks are opt-in and their private receipts remain outside the public source tree.
