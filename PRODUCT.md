# KiFoundry Home

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People who want a persistent place to spend time with AI residents, discuss creative work and ideas, and continue those conversations later. The application is independently installable and usable with configured provider connections.

## Product Purpose

A welcoming RPG home where people approach individual residents, gather a real Council, bring work into the discussion, save revisions, and return later. Casual conversation is a first-class use. The town remains visible while talking.

## Operating Context

A local browser application with SQLite persistence and trusted server-side provider connections. Houses choose an individual resident; the commons gathers the Council; the studio stores drafts and versions. One composer serves direct and group conversation. A searchable resident directory provides Talk, Invite to Council, Add resident, Move out and Bring back.

## Capabilities and Constraints

Current implementation supports saved rooms, direct conversation, bounded independent Council proposals/challenges/synthesis, attributed replies, stop/resume, and versioned drafts. The town supports 64 active residents, shown in neighborhoods of five homes. Council can include every available resident, with at most `2N+1` calls and four concurrent calls by default. The composer shows that budget before Send; inviting residents does not start calls.

The scene shows at most five selected guests at a time and states when more are participating. All guests remain in the directory and saved discussion. Provider prompts stay within 128 KiB: long peer replies receive fair, explicitly marked excerpts while their full text stays saved in the room.

The browser adds residents through an existing trusted provider binding. Native TOML configuration currently supplies one to five bindings and initial residents; each binding can support additional residents with separate adapter instances. Browser controls do not accept executable paths, workspaces, model settings or native session IDs.

Schema 2 stores resident IDs, home slots and archive state. Moving out preserves conversations and sessions while releasing the home; bringing back prefers the old slot and uses another free slot if occupied. New rounds freeze participant names, providers and roles, and saved replies retain speaker attribution. Existing active residents keep their locations when others change.

Fixture residents are scripted and explicitly labelled. Desktop and phone fixture views were reviewed. Native Claude/Codex conversations, a three-resident Council, saved revision comparison and continued conversation after a separate server restart passed; see docs/VERIFICATION.md. User usability acceptance and actual 64-provider scale remain open. Decorative walking does not establish provider execution or autonomous learning.

## Brand Commitments

KiFoundry Home presents agents and specialists as visible residents with persistent houses. Design changes should improve conversation, shared work or navigation while preserving the town's identity. Use functional controls, clear language, actual provider attribution and explicit privacy boundaries.

## Product Principles

- Enter and talk without a task form.
- Every resident speaks for itself; disagreements survive synthesis.
- Conversations and saved work persist beyond a browser session.
- The world makes actions easier to find.
- Evidence labels match what was actually tested.

## Accessibility & Inclusion

Keyboard controls, visible focus, labelled standard inputs, reduced motion, and compact-screen layouts are required by the existing implementation contract.
