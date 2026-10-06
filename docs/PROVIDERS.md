# Connect real providers

Home currently supports Claude Code and Codex through their installed command-line tools. Either provider is enough for direct conversations. Multiple residents can share a provider connection while keeping separate app-owned sessions.

## 1. Prepare the provider CLI

Install and sign in through the provider's supported flow:

- [Claude Code documentation](https://code.claude.com/docs/en/overview).
- [Codex documentation](https://developers.openai.com/codex/cli/).

Verify that the provider works in a terminal before connecting Home. Authentication, network access and available account usage are provider prerequisites. Home does not ask for passwords, copy authentication files or create API keys.

To find installed commands:

```powershell
# Windows PowerShell
Get-Command claude,codex | Select-Object Name,Source
```

```sh
# macOS/Linux
command -v claude codex
```

Native provider journeys have been verified on Windows. Hosted Linux tests establish controlled behavior; they do not establish genuine Linux/macOS provider integration.

Home requires a directly executable CLI. On Windows, a command discovered as a `.cmd` or `.bat` wrapper is rejected; configure the actual binary, typically an `.exe`. Command discovery alone does not prove Home can launch it.

## 2. Create local configuration

From the source folder, copy `examples/agents.toml` to `local-config.toml`:

```powershell
# Windows PowerShell
Copy-Item examples/agents.toml local-config.toml
```

```sh
# macOS/Linux
cp examples/agents.toml local-config.toml
```

Edit the copy. Keep the entries for providers you have installed; the file accepts one to five entries. A minimal example is:

```toml
[[agents]]
id = "claude"
name = "Claude"
provider = "claude"
role = "Explore concrete ideas and improve the work. Speak only for yourself."
executable = "claude"
workspace = "."
timeout = 180
```

| Field | Set it to |
| --- | --- |
| `id` | A unique lowercase identifier. Keep it stable for a returning resident. |
| `name` | The resident's display name. |
| `provider` | `claude` or `codex`. |
| `role` | A short, concrete responsibility. |
| `executable` | A directly executable installed command or binary path; no `.cmd`/`.bat` wrappers. |
| `workspace` | An existing directory, resolved relative to this TOML file. |
| `timeout` | Per-call deadline in seconds, from 5 to 600. |

TOML literal strings use single quotes, which are convenient for Windows paths containing backslashes. Use your own paths in the local copy. Keep credentials and native session IDs out of it. Native model selection follows the provider's configuration; there is no browser model picker.

Configuration is trusted local setup. Use a workspace appropriate for the provider's installed hooks/integrations. The browser cannot supply commands, change executable paths or choose an existing private session.

## 3. Start a separate native town

```sh
python -m home.cli --config local-config.toml --data-dir .home-data --open
```

The explicit data directory keeps this town separate from `.demo-data`. To return later, reuse the same config bindings and data directory. Each configuration entry supplies a connection and an initial resident; you can add further residents through **Residents → Add resident**.

Choose one resident and send a short greeting. A visible/configured resident means the binding is available locally; it does not prove successful sign-in or quota. Only a successful native reply establishes that invocation worked.

Native calls consume provider usage. Start Council with a small group and review the displayed bound before Send. A three-person Council can use seven calls even if two residents use the same provider account.

## Sessions and identity

New sessions belong to this application. A Claude-backed specialist is labelled Claude and speaks through a separate adapter. Adding a specialist does not create another account or change provider limits.

Direct conversations resume saved sessions per resident and conversation. Council phases use fresh sessions without replacing those direct sessions. This setup does not attach to an existing desktop chat or transfer a private identity.

## Execution boundaries

The adapters launch native CLIs without a shell, parse their completion/session metadata, limit input/output, enforce deadlines and supervise owned cancellation. A resumed reply reporting a different session is rejected.

Unexpected action events are rejected. Detection cannot undo an action already started, and inherited hooks/integrations may act outside that event boundary. The adapter is not a universal no-tool sandbox. See [the implemented limits](../home/adapters/LIMITATIONS.txt).

On Windows, the owned process starts before attaching its Job Object, leaving a startup interval. Stop targets owned work and prevents later phases; it does not prove remote request abort or charge reversal.

For failures, use [troubleshooting](TROUBLESHOOTING.md). For storage and sharing boundaries, read [privacy and data](PRIVACY.md).
