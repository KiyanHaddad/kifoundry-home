# Roadmap

## Full objective

A persistent RPG home with natural individual conversations, real Council brainstorming, saved work/version comparison and understandable continuation. Independently installable, documented, extensible and published under actual owner authority.

## Next product improvements

These are proposed work, not shipped features. The objective stays the same: a useful shared AI home.

| Priority | User outcome | Completion check |
| --- | --- | --- |
| 1. Guided setup and readiness | A newcomer knows how to start, where their data lives, and whether the configured executable exists before Send. | Fresh download → demo → one real resident → reopen, without developer help. Local checks make no AI call; a provider test is explicit. |
| 2. Intentional Council and readable results | Starting Council opens a manageable guest choice; its conclusion, disagreements and saved next action are easy to find. | Test a small group and a large town; opening the commons never silently invites the whole town. Review the call bound before sending. |
| 3. Export and return | Users can take a selected draft or discussion out of the home and find a safe backup path. | Exported text matches the selected saved version; restart preserves it; backup restores saved records without claiming to migrate provider sessions. |

The documentation now provides download/setup, separate demo/native data paths, a complete work/revision walkthrough, privacy guidance and troubleshooting. Documentation improvements do not complete these in-app features.

## Rename before a wider release

Choose one public product name and update the repository, download filenames, package name, installed command and visible interface together. The download should clearly identify whether it is source code or an installer.

Preserve the old installed command as a temporary alias. Keep database/resident/session IDs stable, preserve or explicitly migrate existing data directories, and read old browser-storage keys so a rename cannot make a saved home appear empty. The internal `home` Python module can remain stable independently of branding. Update license-file installation paths, docs and links deliberately. Check an upgrade using existing saved conversations and unsaved-draft recovery before announcing the rename.

## Delivery milestones

1. **Core:** durable rooms/versions, request idempotency, bounded Council, explicit fixtures and failure/recovery checks.
2. **Native conversations:** actual Claude and Codex replies and two-turn exact continuity in app-owned sessions.
3. **Council:** actual independent proposals, peer critique and synthesis; Stop/Resume and interrupted recovery without repeated completed calls.
4. **Home:** complete town journey, original/revised work comparison, reopen, compact-screen/keyboard/reduced-motion checks and owner acceptance.
5. **GitHub:** clean-install verification, exact public-tree/privacy/provenance review, authorized repository release and destination readback.

The work remains incomplete until the full journey and publication gates are proven. A fixture implementation is a step, not a redefinition of the objective.

The resident registry and paged town now support 64 residents; their fixture checks are an implemented part of the Home milestone. After the complete journey: actionable skills/plugins, optional judge/review, richer houses and exploration. Each feature must name the owner moment it improves and its acceptance evidence.

Current evidence covers native individual continuity, a three-resident Council, live Stop/safe Resume for both native providers, separate-process reopening, three immutable script versions, and browser keyboard/phone/reduced-motion checks. The initial public repository passed exact-tree privacy review, remote readback and four GitHub CI jobs. Hands-on user acceptance remains open. See [verification](VERIFICATION.md) for the limits of each check.
