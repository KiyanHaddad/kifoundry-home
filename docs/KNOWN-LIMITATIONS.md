# Known limitations

This development alpha is progressing toward the full shared-home journey. Hands-on user acceptance remains open.

- Download is source code; no desktop installer or guided provider setup is shipped. Binding availability does not establish native sign-in or quota.
- Demo and native modes share the default data folder. Use the separate explicit paths in [getting started](QUICKSTART.md).
- Commons currently selects all available residents. Review the guest list and call bound before Send.
- There is no conversation/draft export interface or complete cross-device native-session migration. Database backups preserve saved records; provider sessions require their own continuity.

- Native Claude/Codex Council, a three-resident Council including a Claude-backed specialist, and exact direct-session continuation passed on Windows; see [verification](VERIFICATION.md). Actual 64-provider scale and synthesis quality with short excerpts remain unverified.
- Private exact-session integration is not included. App-owned native sessions are separate.
- Native action-event rejection is detection, not prevention of every inherited hook/integration.
- Live Claude and Codex Stop, safe Resume and separate-process reopening passed without repeating uncertain calls. Abrupt server crashes, OS reboot and remote provider abort or charge reversal remain unverified.
- The interface currently consumes persisted phase/reply state. Token-level streaming is a separate adapter/UI capability and must not be claimed from polling.
- Fixture text demonstrates mechanics, not AI quality, video playback or audio review.
- Desktop, phone, directory, keyboard, reduced motion, recovery controls and actual saved-version comparison have runtime evidence. The complete owner journey still needs hands-on acceptance.
- Clean source/installed-wheel tests and package checks passed locally. The initial 63-file public tree passed privacy review and exact Git-blob verification. GitHub checks passed on Ubuntu/Windows with Python 3.11/3.13. Changes require renewed review and CI.
- Cross-platform process supervision has controlled tests; genuine Linux/macOS provider integration has not been established by Windows checks.

Update these entries with concrete receipts when resolved. Do not delete a limitation because a prompt sounds confident.
