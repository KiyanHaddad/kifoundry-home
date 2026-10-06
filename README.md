# KiFoundry Home

A shared local AI home: talk with residents, gather a Council, keep useful work, and return to the same discussion.

**Development alpha.** Fixture checks, real provider verification, owner acceptance and GitHub publication are separate milestones. See [known limitations](docs/KNOWN-LIMITATIONS.md) before making release claims.

## Quickstart

Python 3.11 or newer is the only application runtime dependency. From this repository:

```sh
python -m home.cli --demo --open
```

Demo residents are explicitly labelled fixtures. They exercise the interface and saved lifecycle; they do not contact AI providers.

For native providers, sign in through your installed Claude Code and Codex CLIs, copy `examples/agents.toml` to ignored `local-config.toml`, set the workspaces and executable paths, then run:

```sh
python -m home.cli --config local-config.toml --open
```

Native replies consume your provider usage. The app shows a one-call conversation or a Council bound of `2N+1` calls before starting. Same-provider specialists are identified by their actual provider. These are app-owned native sessions, separate from a desktop chat or another private session.

Use **Residents** to add someone through a configured connection, invite guests, move someone out or bring them back. Saved homes and conversations stay attached to their resident IDs. The town supports 64 active residents in neighborhoods of five homes, and Council can include the whole available town.

## The experience we are building

Enter the town, approach a resident, bring a script, gather the Council, discuss and revise it, compare the versions, then reopen and continue. Saying hello requires no project form. The world remains present while the discussion happens.

Council participants make independent proposals from the same saved context, challenge the actual replies, and produce an attributed synthesis. Disagreement stays visible. A failed participant does not erase another participant's work.

After Stop or an interrupted round, **Continue saved work** shows the saved participants and remaining call bound. **Resume saved round** reuses saved replies and starts only work that never launched. Calls with uncertain outcomes stay recorded and are not repeated; if no safe work remains, send a new message to continue.

Use `examples/script.txt` for the public demonstration. Your real histories and drafts remain in your selected local data directory; they are not source files.

## Project map

- [Architecture](docs/ARCHITECTURE.md): responsibilities and decisions.
- [Contracts](docs/CONTRACTS.txt): storage, adapters, Council and HTTP integration.
- [Provider setup](docs/PROVIDERS.md): native sign-in and execution boundaries.
- [Extensions](docs/EXTENDING.md): add a resident, provider or policy.
- [Contributing](CONTRIBUTING.md): meaningful checks and change workflow.
- [Roadmap](docs/ROADMAP.md): full destination and unfinished gates.
- [Verification](docs/VERIFICATION.md): executed checks and their limits.
- [Asset provenance](ASSETS.md) and [license](LICENSE).

The application code, assets, examples and contributor documentation live in this repository. Assets have documented provenance. Keep local provider configuration, authentication and conversation data outside the published source.
