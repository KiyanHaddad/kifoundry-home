# Verification — 6 October 2026

This is a local development alpha. These checks establish specific behavior. User acceptance, repository publication and remote CI have separate evidence.

## Working desk follow-up: version 0.1.2

An isolated browser fixture check covered exact saved-revision opening, saving a new revision, reloading with an unsent message and unsaved editor text, keyboard continuation, execution-detail navigation, and switching to a new conversation. Simulated connection loss and reconnection preserved both drafts and the open conversation. No native providers were invoked.

Desktop and 390-pixel phone views were inspected. The phone view had no horizontal overflow and the new desk actions had 44-pixel touch targets. The updated README image is an actual capture using only demonstration data. Controlled regressions cover metadata order, stale versions, saved execution states, dirty-editor preservation and asynchronous navigation. This establishes the implemented current-conversation desk; it does not establish a global task manager or owner usability acceptance.

The source suite discovered 182 tests and completed with one POSIX-only check skipped on Windows. Ruff, mypy, compilation and all seven browser-module syntax checks passed. Source and wheel builds passed; all 30 runtime files in the wheel matched the source, including the new desk module. The outgoing text and demonstration screenshot received a renewed privacy review.

## Security and growth follow-up: version 0.1.1

An independent review covered the then-public 71 files, 90 unique historical blobs across three commits, all five images and all three public CI logs. No sensitive data was found in that bounded review. The repaired scanner additionally checks reachable commit trees/metadata, literal credential assignments, shallow-history rejection, unreadable-directory failures and finite inspection limits; its suite now contains 16 tests.

Controlled regressions reproduced and fixed cross-port cookie authorization, unbounded HTTP/round admission, provider-alias worker starvation and full draft-history polling. A synthetic 500-version history previously returned about 33 MB and used about 99 MB peak Python memory; the browser metadata projection returned about 22 KB and used about 177 KB, with all versions retrievable. This is one local benchmark, not a capacity guarantee.

The expanded source suite ran 154 tests successfully on Windows, with one explicit skip for a POSIX permission check. Ruff, mypy for Windows/Linux targets and all six browser-module syntax checks passed. Browser fixture checks confirmed authenticated reload, room/version pagination, exact revision loading/comparison, saving a new immutable revision, restoring an older off-page selection, and disabling attachment for that old version. Controlled browser-function regressions also cover a confirmed save followed by failed readback and recovery during a pending save. Native providers were not invoked for this security follow-up; earlier native evidence below remains dated to its original runtime.

## Documentation and privacy follow-up

The published baseline was independently rescanned across all 63 files and 69 unique blobs in its two-commit history. The review covered known credential/private-path patterns, private transcript/session comparisons, asset metadata, exact remote-tree identity and GitHub security settings; no material privacy finding was detected. Public GitHub ownership and noreply attribution remain intentionally visible.

At that revision, the publication scanner began reading actual Git index or committed HEAD blobs and rejecting sensitive tracked paths even when force-added. Seven repository-tooling regressions covered ignored sensitive files, staged/committed values hidden by clean working copies, links, private-data shapes, no-Git downloads and legitimate relative module links. The source suite passed 122 tests locally. That documentation update retained the earlier verified runtime; version 0.1.1 changes runtime behavior as described above.

The README screenshot is an actual fresh, offline two-resident fixture town. A browser greeting completed with an explicitly labelled fixture reply. Setup and user instructions were checked against the CLI, configuration and interface, and local documentation links were reviewed. These checks do not establish newcomer usability acceptance or native-session migration.

## Resident lifecycle and town

- Controlled tests cover 64 active residents, stable home slots, archive/restore, missing bindings, migration, attribution and registry HTTP boundaries.
- A real browser fixture journey used seven residents across two neighborhoods. Council saved seven proposals, seven challenges and one synthesis. Moving a resident out removed their home and selection while retaining their replies; restoring them returned their home.
- Desktop and 390-pixel phone captures were reviewed. The phone view has no horizontal overflow, and the commons control remains readable with five visible guests. Search and compact guest selection cover the whole roster.

## Native conversations and saved work

On Windows, installed Claude Code and Codex CLIs completed 11 actual calls through authenticated local HTTP: individual greetings, a two-person Council, direct continuation after Council, and service reopen. Council used five distinct fresh phase sessions; each resident's direct session stayed separate and resumed exactly.

The participants challenged specific points in each other's actual replies. The attributed synthesis retained a wording disagreement. Its actual 63-word revised script was saved as version 2, with version 1 and both content hashes preserved. Independent review confirmed those properties.

A separate server process then reopened the same saved data. A twelfth actual call, sent through the browser to Claude, correctly quoted the revised opening and described the remaining disagreement. The browser displayed versions 1 and 2 side by side.

The browser then added Scribe through the existing Claude connection. Its house appeared automatically, and a thirteenth actual call returned a genuine Claude reply in a separate native session. Moving Scribe out and bringing it back preserved that reply, its identity and home; all three residents' home IDs and positions matched afterward.

Claude, Codex and Scribe then completed a seven-call Council: three proposals, three critiques of the actual other replies, and one attributed synthesis that retained disagreements. All seven phase sessions were fresh and separate from the residents' saved direct sessions. The actual 74-word script was saved through the browser as version 3. Versions 1 and 2, their hashes and earlier rounds remained unchanged. The browser compared versions 2 and 3.

The desktop discussion was enlarged after a real reply opened with only its tail visible. Oversized replies now open at their speaker and beginning. At 1280×720, the complete short reply was readable and normal page scrolling reached Send and the lower town controls. The 390-pixel phone layout retained its width and controls.

These checks used fresh app-owned native sessions. Model selection follows the configured providers. Marker recall establishes that saved room discussion is supplied to resumed conversations; it does not establish unaided provider memory.

## Stop, recovery and accessibility

Separate native checks made three invocations per provider: a completed reply, a deliberately stopped active call, and a distinct new message continuing the original completed session. Claude and Codex each passed Stop, safe Resume and reopening in a separate server process. Resume and reopening launched no duplicate call. The uncertain stopped turn stayed saved, observed owned processes exited, and an unrelated controlled process stayed alive. These checks cover clean reopening after Stop; they do not establish abrupt-crash or OS-reboot recovery, remote provider abort or charge reversal.

Across the native checks, 26 actual invocations produced 24 completed replies and two deliberately stopped calls. Usage costs were not measured.

The browser's recovery control resumed a partially stopped fixture Council using its original roster, preserved completed work and the next-message draft, skipped the uncertain launched call, and completed the remaining safe work. An uncertain direct call correctly disabled Resume and left Send available. At 390 pixels, the recovery view had no horizontal overflow.

A keyboard journey covered conversation creation, Send, the studio, two saved versions, comparison, motion controls, resident search/Talk and returning to the previous draft. It exposed lost focus after Save and conversation changes; the repaired paths were rerun. A separate reduced-motion runtime check disabled decorative walking and transitions. Temporary browser emulation was cleared afterward.

## Developer and package checks

- A two-server browser-cookie regression reproduced the original session collision, then passed with cookie names derived from the bound port. Both servers retain authentication in one cookie jar, and sibling cookies or CSRF tokens are rejected.
- 115 tests passed from source and from a clean installed wheel outside the checkout.
- Ruff, mypy for the Windows host and Linux target, compilation, and all five browser-module syntax checks passed.
- Source and wheel builds, isolated installation, CLI help, imports, all 14 web assets and the included MIT/OFL licenses passed verification.
- The exact 63-file initial public tree passed credential/private-information review, binary metadata checks and verification of the actual staged and committed Git blobs. New changes require a fresh outgoing-tree review.

## GitHub checks

The initial public commit passed all four GitHub Checks jobs on 6 October 2026: Ubuntu and Windows, each with Python 3.11 and 3.13. Each job ran 115 tests successfully, compilation, Ruff, mypy, all five browser-module syntax checks and the public-tree scanner. The repository's Actions tab records the actual runs. These hosted checks exercise fixtures and controlled processes; genuine native-provider verification remains Windows-specific.

Remote readback matched all 63 published files to the reviewed commit. The initial history contains only reviewed source, and the commit uses a GitHub noreply address. GitHub secret scanning and push protection were enabled, with no open secret-scanning alerts observed at publication. Local configuration, authentication, histories and private receipts were excluded.

## Still unverified

Actual 64-provider scale, synthesis quality with short excerpts, abrupt server crashes or OS reboot, genuine native-provider integration on Linux/macOS, and user usability acceptance. Native process exit does not prove remote provider cancellation or charge reversal. Usage costs were not measured.

Private receipts, native session IDs, account information and raw transcripts are kept outside this source tree.
