# Using the home

The town gives you three entrances: a resident's house for a conversation, the commons for Council, and the studio for written work. **Residents** also provides a searchable list when the town grows.

## Pick up your work

**Your working desk**, above the town, shows the current conversation, most recently saved draft and activity in that conversation.

- **Continue conversation** takes you to the message box. An unsent message stays on this browser until you send or clear it.
- **Open saved draft** opens the exact most recently saved revision. If you have unsaved edits, **Continue editing** reopens those edits instead. The desk labels unsaved text separately from saved work.
- **View replies** opens saved execution details. **Reconnect** retries loading Home after a connection failure.

These actions do not send a message, resume a round or attach a draft. Activity reflects the conversation's last loaded execution state; walking remains decorative. Demo replies stay labelled as simulated.

## Talk to one resident

1. Choose their house, or open **Residents → Talk**.
2. Check **Who receives your message**. One selected resident means one direct reply.
3. Type your message and send it.

Saying hello needs no project setup. Replies show the actual provider; demo residents are visibly labelled fixtures. A resident's walking animation is decorative. Saved execution status tells you whether a call is running or finished.

Use **New conversation** to start a separate discussion. Existing conversations remain in the list. Direct provider sessions belong to a resident in a particular conversation; returning to that conversation resumes its saved direct session.

## Ask the Council

1. Open **Choose guests** or invite residents through the directory.
2. Review the selected names and the provider-call bound above Send.
3. Give the group one concrete question, then choose **Ask the Council**.

The commons currently gathers all available residents. Check the roster before sending, especially in a large town. Inviting someone does not launch a provider call.

For a group of `N` residents, a complete round uses up to `2N+1` calls: independent first thoughts, one round of challenges based on the actual replies, and one attributed synthesis. Two residents means up to five calls; three means up to seven. Failures can reduce that count. Four calls can run at once by default.

Earlier contributions can be expanded in the discussion. Council is bounded; it does not continue debating automatically. Its fresh phase sessions remain separate from each resident's direct conversation. Long contributions may be shared with peers as labelled excerpts while the full replies remain saved.

## Bring a draft and keep revisions

1. Choose **Bring work** or the studio.
2. Give the draft a title, paste its text, and choose **Save draft**.
3. The saved version is attached to your next message. Ask for a specific improvement.
4. On a useful reply, choose **Use as draft**. Review and edit the result in the studio.
5. Choose **Save new revision**. Use **Compare with** to read it beside an earlier version.

Saving appends a version; it does not replace earlier saved text. Moving a reply onto the desk does not save it automatically. The interface supports pasted text, not general video/audio inspection or arbitrary file upload.

The studio initially lists 100 recent version records. Use **Older saved versions** to load another page; selecting a version or comparison loads that exact body. An older revision cannot be attached as the current draft. Conversation lists likewise offer **Older conversations**. All records remain saved.

Try `examples/script.txt` for a first exercise: save it, ask a small Council to improve its opening, then compare the revision with the original.

## Stop and recover

**Stop** asks the application to stop its owned work and prevents later phases. Completed replies remain saved. A stopped process does not establish whether a remote provider stopped processing or reversed usage.

For a stopped or interrupted round, **Continue saved work** shows its original participants and remaining bound. **Resume saved round** reuses completed work and starts only calls that never launched. It does not repeat calls with uncertain outcomes. If nothing can safely resume, review the saved discussion and send a distinct new message.

## Add, move out and bring back residents

Open **Residents → Add resident**, enter a name and role, and choose an existing provider connection. That connection must already be configured locally. A Claude-backed specialist remains labelled Claude; adding a name does not create a new provider account.

- **Move out** archives a resident and keeps their history.
- **Bring back** restores the same identity when a connection and home slot are available.
- Other active homes keep their locations. The directory and neighborhoods support up to 64 active residents.

Resident changes wait for active work to finish, including processes still exiting after Stop.

## Return later

Start with the same `--data-dir`, open your saved conversation, and continue. Saved messages and draft versions live in SQLite. Unsaved editor recovery also uses the browser's local storage, so save important revisions before changing browser profiles or clearing site data.

For moving computers or publishing your own changes, read [privacy and data](PRIVACY.md). For failures, see [troubleshooting](TROUBLESHOOTING.md).
