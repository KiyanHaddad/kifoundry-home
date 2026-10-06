# KiFoundry Home visual system

A welcoming RPG settlement makes conversations, Council and shared work visible as functional interactions in the town.

## World and composition

A detailed original forest settlement at dusk carries the first viewport. Pine green framing and warm illuminated buildings belong to the same evening scene. The commons sits in the center; the studio is beside it. Review resident-management changes at actual browser dimensions.

Generated terrain provides empty residential clearings. A transparent five-house atlas supplies separate homes according to application state; removing a resident removes the corresponding house and avatar. Assets and conversion evidence are recorded in ASSETS.md.

Saved home slots 0–63 organize up to 64 active residents into neighborhoods of five plots. Neighborhood buttons page the scenery; the directory searches the whole town. Existing homes keep their positions when other residents join or leave. Restoring an archived resident prefers their old plot, then another free slot. The five house variants follow the plot, while avatar appearance follows a stable resident-ID hash. Legacy payloads without slots use ID ordering around reserved slots. Empty plots remain clearings.

Selected guests from other neighborhoods remain visible at the Council table. A direct Talk action opens the resident's neighborhood. The resident count describes active registry entries; windows and walking do not assert provider presence.

The browser UI is an operating surface. Standard legible controls sit on opaque pine plates. The desktop conversation bench stays beside the town, with less space in its empty state. On a phone, the town and bench form a single column; the empty welcome illustration/text yields to the composer. The studio opens as an attached editor over the lower part of the town, keeping the environment visible. Closing it restores focus to its entry control.

## Type and color

Self-hosted Fraunces 500 supplies headings and the wordmark. Self-hosted Manrope 400/600 supplies interaction and reading text. Font origins and OFL notices are in ASSETS.md. Body/UI scale must be checked at actual browser dimensions; mini scene annotations do not replace accessible control names.

- Ground: #172926
- Panel: #203632
- Raised control: #29443e
- Text: #f2eedc
- Secondary text: #bccbbe
- Action and focus: #ebc47f / #ffde9f
- Pale selected plate: #f1ead7, dark text #26352c

Use authored SVG icons with consistent thin rounded strokes. No decorative eyebrow headings, emoji icon substitutes, or gradient text.

## Motion and evidence

Resident sprites are separate semantic buttons. Position reflects selection: chosen residents walk toward seats near the table. Ambient wandering stays near the home, stops during an active round, pauses when hidden, and can be turned off. Reduced motion removes both transitions and wandering.

Sprites are static atlas illustrations moving through the scene, with a small walking bob. They do not have directional skeletal animation. Walking is explicitly decorative. Thinking, failure, stop and interruption labels are derived from saved turns. A failed progress fetch switches the world to Status unknown.

## Discussion and work

Council proposals and challenges are individually expandable; the synthesis remains expanded and attributed. Execution details are available in one disclosure. Saved message nodes retain identity during polling. Unsent message and editor drafts remain local until sent/saved; saved versions remain authoritative in SQLite. Selecting another version preserves dirty work in an explicitly recoverable local buffer.

The directory separates Talk from Invite to Council. Its Add resident form asks for a name, role and configured provider connection. Move out archives a resident; Bring back restores them while keeping saved work. Provider labels and connection availability remain explicit. Registry changes wait until all running conversations and owned calls finish. Council can include the whole available town. The commons and Invite all select everyone without starting provider calls. Choose guests opens individual selection. The composer states the call budget and possible reply excerpts before Send.

Five visible seats keep each neighborhood readable. Selected local residents occupy them first, with selected visitors filling free seats. The scene explicitly reports the total guest count and how many are shown. Compact participant chips open the full directory; no hidden guest loses their actual turn or saved reply.

Desktop conversations with messages use natural page height and a discussion area between 240 and 420 pixels. Page scrolling reaches the composer while the town remains alongside it. Following a new reply opens its beginning if it is taller than the discussion area; reading earlier messages keeps its existing position. Empty conversations and phone layouts retain their separate sizing.

## Boundaries

This is a development build with fixture and boundary tests. Desktop and phone fixture captures were independently reviewed; house and commons label overlaps were corrected and confirmed. A two-person native Council, actual saved revision comparison and continuation after server restart passed, as did clean packaging and developer checks. Broader recovery usability, long-output accessibility, native scale and owner acceptance remain open. No formal Impeccable composition approval or detector pass is claimed here. A screenshot establishes only the view it captures; see docs/VERIFICATION.md for the distinct checks.
