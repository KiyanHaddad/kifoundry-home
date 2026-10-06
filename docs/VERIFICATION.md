# Verification — 6 October 2026

This is a local development alpha. These checks establish specific behavior. User acceptance, repository publication and remote CI have separate evidence.

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
