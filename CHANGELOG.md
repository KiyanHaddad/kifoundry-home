# Changelog

## Unreleased

- Rewrote the README around downloading and using the application, with an actual clean-demo screenshot.
- Added getting started, user, privacy/data and troubleshooting guides plus a documentation index. Separated demo and native data paths in the examples.
- Replaced the dense contract text with a structured Markdown reference; the old path remains a compatibility pointer. Corrected room response and bounded-readback details against the code.
- Hardened privacy checks to inspect actual Git index/HEAD blobs, reject sensitive tracked filenames and report findings without matched values. Added seven regression tests and a committed-tree check to CI.
- Documented the next setup, Council and export improvements, and the compatibility work required for a future rename.

## 0.1.0 — development

- Established the shared-home objective and bounded Council contracts.
- Started a portable core, native adapters and original world interface.
- Added contributor, extension, privacy and provenance documentation.
- Added schema-2 resident persistence, trusted binding selection and a limit of 64 active residents.
- Added archive/restore, stable home slots, participant snapshots and saved speaker/provider attribution.
- Added a searchable directory with Talk, Council invitations, Add resident, Move out and Bring back.
- Added generated transparent houses over modular terrain and paged five-home neighborhoods.
- Added regressions for resident lifecycle, registry HTTP boundaries, stable population layout and saved draft-version normalization.
- Kept full towns accessible when a newly configured resident must wait for a free home slot.
- Expanded Council to 64 selected residents with advertised limits, bounded concurrency and a visible `2N+1` call budget. Five visible seats are a scene rendering limit.
- Bounded peer prompts with fair, explicit excerpts while preserving every saved full reply and participant attribution.
- Included intervening saved Council discussion when resuming a direct resident conversation.
- Verified add, direct fixture reply, move out, restore, five-seat selection, new conversations and draft comparison through the browser. Reviewed desktop and phone fixture captures and corrected obscured house names.
- Verified a seven-resident fixture Council, Invite all, move out/restore and phone directory controls; corrected phone guest labels obscuring the commons.
- Verified actual Claude/Codex conversation, substantive Council critique, a saved original/revised script and exact direct-session continuation. A separate server process and browser continuation also passed.
- Passed 114 tests from source and a clean installed wheel, lint/type checks, browser-module syntax and packaged asset/license checks.
- Verified adding a native specialist through the directory, its separate actual provider reply, and archive/restore with unchanged homes and saved attribution.
- Enlarged desktop discussion and opened oversized replies at their beginning; verified reply readability and reachable lower controls on a short desktop viewport.
- Isolated authentication cookies by local server port, with a regression covering simultaneous servers and rejection of sibling cookies and CSRF tokens.
- Added a saved-round recovery selector with original participants, remaining call bounds and safe Resume; uncertain launched calls are never repeated through the interface.
- Restored lost keyboard focus after Send, Stop, Resume, Save and conversation changes, with an actual keyboard journey and reduced-motion runtime check.
- Verified Claude, Codex and a Claude-backed specialist together in a seven-call Council; saved its actual revised script as version 3 beside the preserved earlier versions.
- Verified live Stop and safe Resume for both native providers, owned process exit, separate-process reopening and exact-session continuation without duplicate calls.
- Passed the expanded 115-test suite from source and a clean installed wheel, including recovery eligibility and uncertain-call handling.
- Published the initial public source after a 63-file privacy review and staged/committed Git-blob checks; verified matching remote contents and GitHub noreply commit metadata.
- Passed all four GitHub jobs on Ubuntu/Windows with Python 3.11/3.13, each running 115 tests and the configured developer checks.

Native 64-person scale, abrupt-crash recovery and user acceptance remain open. This is a development alpha. Verification is recorded separately.
