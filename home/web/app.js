import { TownWorld } from './world.js';
import { normalizeRoom, recoveryInfo } from './room.js';
import { ResidentDirectory } from './resident-directory.js';
/** @typedef {{id:string,name:string,provider:string,role?:string}} Agent */
/** @typedef {{id:string,title:string,version:number,content:string,created_at?:string}} Artifact */
/** @typedef {{id:string,title:string,messages:Array<object>,rounds:Array<object>,artifacts:Artifact[]}} Room */

const $ = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
const state = {
  csrf: "", agents: /** @type {Agent[]} */ ([]), archived_agents: [], resident_bindings: [], rooms: [], room: /** @type {Room|null} */ (null),
  capabilities: {max_participants:5,max_residents:64,max_workers:4},
  fixture: false, selected: new Set(), sending: false, resuming: false, saving: false, loading: false, epoch: 0, connected: false,
  poll: 0, registryEpoch: 0, editKey: "", attachedId: "", editDirty: false, discussionKey: "", activityKey: "", activityRoundId: "",
};
const activeStatuses = new Set(["queued", "running"]);
const statusLabels = { queued: "Waiting their turn", running: "Thinking", completed: "Finished", failed: "Could not reply", cancelled: "Stopped", interrupted: "Interrupted", partial: "Some replies received" };
const phaseLabels = { proposal: "First thoughts", critique: "Challenge", synthesis: "Putting it together", direct: "Reply", reply: "Reply" };
const world = new TownWorld(selectResident);
const directory = new ResidentDirectory($('residentDirectoryPanel'), {
  add: payload => mutateResident('/api/agents', payload),
  archive: id => mutateResident('/api/agents/' + encodeURIComponent(id) + '/archive', {}),
  restore: id => mutateResident('/api/agents/' + encodeURIComponent(id) + '/restore', {}),
  talk: id => { closeDirectory(); selectResident(id); },
  select: toggleCouncilGuest,
  selectAll: inviteEveryone,
  close: closeDirectory,
});
const palette = ["#8d4734", "#34594f", "#63522d", "#5b466f", "#3d6250"];

/** Make inert DOM content. No owner or model content is parsed as HTML. */
function node(tag, content = "", className = "") {
  const el = document.createElement(tag);
  if (content) el.textContent = String(content);
  if (className) el.className = className;
  return el;
}
function button(label, className, action) {
  const el = node("button", label, className);
  el.type = "button";
  el.addEventListener("click", action);
  return el;
}
function toggle(id, shown) { $(id).classList.toggle("hidden", !shown); }
function showError(id, message = "") { $(id).textContent = message; toggle(id, Boolean(message)); }
function agentName(id) { return [...state.agents, ...state.archived_agents].find((agent) => agent.id === id)?.name || "Unknown resident"; }
function activeRound() { return state.room?.rounds?.find((round) => activeStatuses.has(round.status)) || null; }
function pendingRound() { return activeRound() || state.room?.rounds?.find(round => (round.turns || []).some(turn => activeStatuses.has(turn.status))) || null; }
function storageRead(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageWrite(key, value) { try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { /* Saved server state remains authoritative. */ } }
function dateLabel(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date); }

async function api(path, body, headers = {}) {
  const options = { credentials: "same-origin", headers: { "Accept": "application/json", ...headers } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = state.csrf;
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error("The connection was lost. Your draft is still here."); }
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The home returned an unreadable response. Your draft is kept."); }
  if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : "That request could not be completed.");
  return result;
}

async function boot() {
  state.loading = true;
  updateComposer();
  showError("bootErrorText"); toggle("bootError", false);
  try {
    const launch = new URLSearchParams(location.hash.slice(1)).get("launch");
    const session = await api("/api/session", undefined, launch ? { "X-Home-Launch": launch } : {});
    if (typeof session.csrf !== "string" || !session.csrf) throw new Error("Reopen this home using the launcher to start a private session.");
    if (launch) history.replaceState(null, "", location.pathname + location.search);
    state.csrf = session.csrf;
    const data = await api("/api/state");
    if (!Array.isArray(data.agents) || !Array.isArray(data.rooms) || !data.room) throw new Error("The home has no saved conversation to open.");
    applyResidents(data);
    state.rooms = data.rooms;
    state.fixture = data.fixture === true;
    state.connected = true;
    if (!state.selected.size) state.selected = new Set(state.agents.filter(agent => agent.available !== false).slice(0,1).map(agent => agent.id));
    $("modeLabel").textContent = state.fixture ? "Fixture demo · simulated replies" : "Provider conversations";
    $("modeLabel").classList.toggle("fixture", state.fixture);
    $("conversationFootnote").textContent = state.fixture ? "This is a fixture demo. These simulated replies do not verify live providers." : "Each resident speaks for themselves. You decide what happens next.";
    renderHouses(); renderParticipants();
    const lastRoom = storageRead("kifoundry-home:last-room");
    const room = lastRoom && data.rooms.some((item) => item.id === lastRoom) ? await api("/api/rooms/" + encodeURIComponent(lastRoom)) : data.room;
    adoptRoom(room, true);
  } catch (error) {
    state.connected = false; updateHouseStates();
    $("modeLabel").textContent = "Home connection unavailable";
    showError("bootErrorText", error.message + " Reopen using the launcher if your private session has expired."); toggle("bootError", true);
  } finally { state.loading = false; updateComposer(); schedulePoll(); }
}

function renderHouses() {
  world.configure(state.agents);
  updateHouseStates();
}
function applyResidents(data) {
  state.agents = data.agents;
  state.archived_agents = data.archived_agents || [];
  state.resident_bindings = data.resident_bindings || [];
  if(data.capabilities && Number.isInteger(data.capabilities.max_participants) && data.capabilities.max_participants>=1 && data.capabilities.max_participants<=64) {
    state.capabilities={...state.capabilities,...data.capabilities};
  }
  state.selected = new Set([...state.selected].filter(id => state.agents.some(agent => agent.id === id && agent.available !== false)));
}
function renderDirectory() {
  directory.render({agents:state.agents,archived_agents:state.archived_agents,resident_bindings:state.resident_bindings,selected:state.selected,round:pendingRound() || state.room?.rounds.at(-1),connected:state.connected,capabilities:state.capabilities});
}
function openDirectory() {
  state.directoryReturn = document.activeElement;
  toggle('residentDirectoryPanel',true); renderDirectory(); directory.search.focus({preventScroll:true});
  refreshResidents();
}
function closeDirectory() {
  toggle('residentDirectoryPanel',false); state.directoryReturn?.focus({preventScroll:true});
}
async function mutateResident(path,payload) {
  const changed = await api(path,payload);
  const epoch = ++state.registryEpoch;
  try {
    const data = await api('/api/state');
    if(epoch !== state.registryEpoch) return;
    applyResidents(data); state.connected = true;
  }
  catch (error) {
    if(epoch !== state.registryEpoch) return;
    // The mutation is confirmed. Keep it represented locally so retry cannot duplicate an add.
    if(changed && typeof changed.id==='string') {
      const agents=state.agents.filter(agent=>agent.id!==changed.id);
      const archived=state.archived_agents.filter(agent=>agent.id!==changed.id);
      (changed.archived ? archived : agents).push(changed);
      applyResidents({agents,archived_agents:archived,resident_bindings:state.resident_bindings});
    }
    state.connected=false;
    showError('composerError','Resident change saved. Reconnect to load the latest town.');
  }
  renderHouses(); renderParticipants(); updateComposer(); renderDirectory();
  const id = changed.id || changed.agent?.id;
  if (id && state.agents.some(agent => agent.id === id)) world.focusResident(id);
}
async function refreshResidents() {
  if(!state.csrf) return;
  const epoch=++state.registryEpoch;
  try {
    const data=await api('/api/state');
    if(epoch!==state.registryEpoch) return;
    applyResidents(data);state.connected=true;renderHouses();renderParticipants();updateComposer();renderDirectory();
  } catch(error) {
    if(epoch===state.registryEpoch){state.connected=false;updateHouseStates();updateComposer();directory.showError(error);}
  }
}
function toggleCouncilGuest(id) {
  const agent=state.agents.find(agent=>agent.id===id);
  if (!agent || agent.available===false) throw new Error('This resident needs a provider connection before joining Council.');
  if (state.selected.has(id)) state.selected.delete(id);
  else {
    if(state.selected.size>=state.capabilities.max_participants) throw new Error('This Council supports up to '+state.capabilities.max_participants+' residents.');
    state.selected.add(id);
  }
  renderParticipants(); updateHouseStates(); updateComposer(); renderDirectory();
}
function selectResident(id) {
  if (state.agents.find(agent=>agent.id===id)?.available===false) { openDirectory(); return; }
  state.selected = new Set([id]); renderParticipants(); updateHouseStates(); updateComposer();
  world.focusResident(id); renderDirectory();
  $("composerText").focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 800px)").matches) $("conversationKind").scrollIntoView({ block: "start", behavior: motionBehavior() });
}
function gatherEveryone() {
  const available = state.agents.filter(agent=>agent.available!==false);
  if(available.length>state.capabilities.max_participants) { openDirectory(); return; }
  state.selected = new Set(available.map((agent) => agent.id));
  renderParticipants(); updateHouseStates(); updateComposer(); $("composerText").focus({ preventScroll: true });
  renderDirectory();
}
function inviteEveryone() {
  const available=state.agents.filter(agent=>agent.available!==false);
  if(available.length>state.capabilities.max_participants) throw new Error('This server supports '+state.capabilities.max_participants+' Council participants.');
  state.selected=new Set(available.map(agent=>agent.id));
  renderParticipants(); updateHouseStates(); updateComposer(); renderDirectory();
}
function renderParticipants() {
  const selectedAgents=state.agents.filter(agent=>state.selected.has(agent.id));
  const shown=selectedAgents.length>5?selectedAgents.slice(0,4):selectedAgents;
  $("participants").replaceChildren(...shown.map((agent, index) => {
    const el = button("", "participant", () => {
      toggleCouncilGuest(agent.id);
    });
    el.setAttribute("aria-pressed", String(state.selected.has(agent.id)));
    const initial = node("span", agent.name.slice(0, 1), "participant-initial"); initial.style.setProperty("--resident-color", palette[index % palette.length]);
    el.append(initial, node("span", agent.name));
    return el;
  }));
  if(selectedAgents.length>shown.length) $('participants').append(button('+'+(selectedAgents.length-shown.length)+' invited','participant participant-more',openDirectory));
  const names = [...state.selected].map(agentName);
  $("recipientHint").textContent = names.length === 1 ? "A direct conversation with " + names[0] + "." : names.length>5 ? names.length+' residents will receive the same starting context. Everyone replies, challenges once, then one resident synthesizes.' : names.length ? "Council: " + names.join(", ") + ". First thoughts, a challenge, then a synthesis." : "Choose who should hear your message.";
  $("conversationKind").textContent = names.length > 1 ? "Council conversation" : "Conversation";
  $("everyoneButton").textContent = 'Choose guests';
}
function updateHouseStates() {
  world.update(state.selected, pendingRound() || state.room?.rounds.at(-1), state.connected);
  $("commonsButton").setAttribute("aria-pressed", String(state.selected.size > 1));
  renderDirectory();
}

function persistDraft() {
  if (!state.room) return;
  storageWrite("kifoundry-home:draft:" + state.room.id, JSON.stringify({ text: $("composerText").value, editKey: state.editKey, title: $("artifactTitle").value, content: $("artifactContent").value, attachedId: state.attachedId, dirty: state.editDirty }));
}
function restoreDraft() {
  let draft = null;
  try { draft = JSON.parse(storageRead("kifoundry-home:draft:" + state.room.id) || "null"); } catch { /* Ignore a broken local draft; server history is intact. */ }
  $("composerText").value = typeof draft?.text === "string" ? draft.text : "";
  state.editKey = typeof draft?.editKey === "string" ? draft.editKey : "";
  state.attachedId = typeof draft?.attachedId === "string" ? draft.attachedId : "";
  state.editDirty = draft?.dirty === true;
  $("artifactTitle").value = typeof draft?.title === "string" ? draft.title : "";
  $("artifactContent").value = typeof draft?.content === "string" ? draft.content : "";
}
function adoptRoom(room, changed = false) {
  room = normalizeRoom(room);
  state.room = room;
  state.connected = true;
  document.querySelector('.conversation-panel').classList.toggle('has-messages',room.messages.length>0);
  toggle('recoverDraftButton',Boolean(storageRead('kifoundry-home:recovered-work:'+room.id)));
  if (changed) { state.discussionKey = ""; state.activityKey = ""; state.activityRoundId = ""; $('recoverySelect').replaceChildren(); restoreDraft(); }
  storageWrite("kifoundry-home:last-room", room.id);
  $("roomTitle").textContent = room.title;
  $("savedLabel").textContent = "Saved locally";
  renderRooms(); renderDiscussion(); renderActivity(); renderArtifacts(); updateHouseStates(); updateComposer();
}
function renderRooms() {
  $("rooms").replaceChildren(...state.rooms.map((room) => {
    const el = button("", "room-button", () => openRoom(room.id));
    el.append(node("span", room.title), node("small", dateLabel(room.updated_at || room.created_at)));
    if (room.id === state.room?.id) el.setAttribute("aria-current", "page");
    return el;
  }));
}
async function openRoom(id) {
  if (id === state.room?.id || state.sending || state.resuming || state.saving) return;
  persistDraft(); const epoch = ++state.epoch; state.loading = true; updateComposer();
  window.clearTimeout(state.poll); showError("composerError");
  try { const room = await api("/api/rooms/" + encodeURIComponent(id)); if (epoch === state.epoch) adoptRoom(room, true); }
  catch (error) { showError("composerError", error.message); }
  finally { if (epoch === state.epoch) { state.loading = false; updateComposer(); schedulePoll(); if (document.activeElement === document.body) $('composerText').focus({preventScroll:true}); } }
}
function renderDiscussion() {
  const messages = state.room.messages;
  const key = JSON.stringify(messages);
  const roomId = state.room.id;
  if (key === state.discussionKey) return;
  state.discussionKey = key;
  const log = $("discussion");
  const nearBottom = log.dataset.roomId !== state.room.id || log.scrollHeight - log.scrollTop - log.clientHeight < 100;
  if (!messages.length) {
    const welcome = node("div", "", "discussion-welcome");
    const illustration = node('div','','welcome-illustration');
    const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('viewBox','0 0 90 70'); svg.setAttribute('fill','none'); svg.setAttribute('aria-hidden','true');
    const path = document.createElementNS(svg.namespaceURI,'path'); path.setAttribute('d','M12 48h64M21 48v15m46-15v15M27 43V21l18 6 18-6v22l-18 6-18-6Zm18-16v22M8 37V17m70 20V17M33 14V7m24 7V7'); svg.append(path); illustration.append(svg);
    const actions = node('div','','starter-actions');
    actions.append(button('Say hello','',()=>{$('composerText').value='Hey, let’s talk.'; persistDraft(); $('composerText').focus();}),button('Brainstorm together','',()=>{gatherEveryone();$('composerText').value='Let’s brainstorm an idea together. What should we explore?';persistDraft();}));
    welcome.append(illustration, node("h3", "Pull up a chair."), node("p", "Choose a resident to talk with, gather Council for a second perspective, or bring a draft from the studio."), actions);
    log.replaceChildren(welcome); return;
  }
  if (log.dataset.roomId !== state.room.id) { log.replaceChildren(); log.dataset.roomId = state.room.id; }
  const existing = new Map([...log.children].filter(el=>el.dataset.messageId).map(el=>[el.dataset.messageId,el]));
  const desired = messages.map((message) => {
    const prior = existing.get(message.id);
    if (prior) return prior;
    const article = node("article", "", "message message-" + (message.role === "owner" ? "owner" : message.role === "agent" ? "agent" : "system"));
    article.dataset.messageId = message.id;
    if (message.phase === 'synthesis') article.classList.add('message-synthesis');
    const heading = node("div", "", "message-heading");
    heading.append(node("strong", message.role === "owner" ? "You" : message.role === "agent" ? message.agent_name || agentName(message.agent_id) : "Home"));
    if (message.phase) heading.append(node("span", phaseLabels[message.phase] || message.phase, "message-phase"));
    if (message.role === "agent") {
      const configured = [...state.agents,...state.archived_agents].find((agent) => agent.id === message.agent_id);
      heading.append(node("span", message.agent_provider || message.provider || (state.fixture ? "Fixture" : configured?.provider || "Provider"), "provider-label"));
    }
    const content = node("div", message.content, "message-content");
    let body = article;
    if (['proposal','critique'].includes(message.phase)) {
      const details = node('details','','message-details'); const summary = node('summary'); summary.append(heading); details.append(summary); article.append(details); body = details;
    } else article.append(heading);
    body.append(content);
    if (message.role === "agent" && message.content) body.append(button("Use as draft", "text-button use-draft", () => useMessageAsDraft(message.content)));
    return article;
  });
  for (let index=0; index<desired.length; index++) if(log.children[index]!==desired[index]) log.insertBefore(desired[index],log.children[index]||null);
  for(const child of [...log.children]) if(!desired.includes(child)) child.remove();
  if (nearBottom) requestAnimationFrame(() => {
    const latest = desired.at(-1);
    if (log.dataset.roomId !== roomId || state.discussionKey !== key || !latest || latest !== log.lastElementChild) return;
    // A long final reply opens at its speaker and beginning, rather than only its last line.
    log.scrollTop = latest.offsetHeight > log.clientHeight ?
      log.scrollTop + latest.getBoundingClientRect().top - log.getBoundingClientRect().top : log.scrollHeight;
  });
}
function renderActivity() {
  const round = pendingRound() || state.room.rounds.find(item => item.id === state.activityRoundId) || state.room.rounds.at(-1);
  toggle("roundActivity", Boolean(round));
  if (!round) return;
  const key = JSON.stringify(round);
  if (key === state.activityKey) return;
  state.activityKey = key;
  const heading = node("div", "", "activity-heading");
  heading.append(node("strong", round.mode === "direct" ? "Resident reply" : "Council round"), node("span", statusLabels[round.status] || round.status, "round-status"));
  const list = node("div", "", "turn-list");
  for (const turn of round.turns || []) {
    const el = node("div", "", "turn-status"); el.dataset.status = turn.status;
    el.append(node("span", "", "status-dot"), node("span", (round.participant_snapshots?.[turn.agent_id]?.name || agentName(turn.agent_id)) + " · " + (phaseLabels[turn.phase] || turn.phase)), node("small", statusLabels[turn.status] || turn.status));
    if (turn.error) el.append(node("p", turn.error, "turn-error"));
    list.append(el);
  }
  const expanded = $("roundActivity").querySelector('details')?.open || false;
  const details = node('details'); details.open = expanded;
  details.append(node('summary','See replies and execution status'),list);
  $("roundActivity").replaceChildren(heading, ...(round.note ? [node('p', round.note, 'round-note')] : []), details);
}
function renderRecovery() {
  const rounds = [...(state.room?.rounds || [])].reverse().filter(round => recoveryInfo(round));
  toggle('recoveryPanel', Boolean(rounds.length) && !pendingRound());
  if (!rounds.length) return;
  const select = $('recoverySelect');
  const selected = rounds.find(round => round.id === select.value) || rounds[0];
  const options = rounds.map(round => {
    const names = round.participants.map(id => round.participant_snapshots?.[id]?.name || agentName(id));
    const option = node('option', (round.mode === 'direct' ? 'Reply' : 'Council') + ' · ' + names.join(', ') + ' · ' + dateLabel(round.created_at));
    option.value = round.id; return option;
  });
  select.replaceChildren(...options); select.value = selected.id;
  const info = recoveryInfo(selected);
  const missing = selected.participants.some(id => !state.agents.some(agent => agent.id === id && agent.available !== false));
  const explanation = info.waiting ? 'Waiting for the stopped calls to finish.' : missing ?
    'Bring back the original residents and reconnect their providers before resuming.' : !info.canResume ?
    'No safe work remains in this round. Send a new message to continue.' :
    (info.maxNewCalls ? 'Up to ' + info.maxNewCalls + ' new provider calls. ' : 'No new provider calls. ') +
    'Completed replies stay saved. Only work that never started can run.';
  $('recoveryHint').textContent = explanation + (info.unknownCalls ?
    ' ' + info.unknownCalls + ' started ' + (info.unknownCalls === 1 ? 'call has' : 'calls have') + ' an uncertain outcome and will not be repeated.' : '');
  $('resumeButton').disabled = !state.connected || state.loading || state.sending || state.resuming || state.saving || Boolean(pendingRound()) || missing || !info.canResume;
  $('resumeButton').textContent = state.resuming ? 'Resuming…' : 'Resume saved round';
  select.disabled = state.resuming;
}
function updateComposer() {
  const active = Boolean(pendingRound());
  $("composerText").disabled = !state.room || state.loading;
  $("sendButton").disabled = !state.room || !state.connected || state.loading || state.sending || state.resuming || active || !state.selected.size || state.selected.size > state.capabilities.max_participants;
  $("sendButton").textContent = state.resuming ? 'Resuming…' : state.sending ? "Sending…" : active ? "Round in progress" : state.selected.size > 1 ? "Ask the Council" : "Send";
  toggle("cancelButton", Boolean(activeRound())); $("cancelButton").disabled = state.sending;
  $("composerLabel").textContent = active ? "Keep your next thought here while they reply." : "What’s on your mind?";
  $("callCount").textContent = state.selected.size > state.capabilities.max_participants ? 'This Council supports up to '+state.capabilities.max_participants+' residents.' : state.selected.size > 1 ? 'Up to '+(2*state.selected.size+1)+' provider calls, with up to '+state.capabilities.max_workers+' at once. Everyone proposes and challenges once, then one resident synthesizes. Long replies may be shared as labelled excerpts; full replies stay saved.' : state.selected.size ? "One provider call for a direct reply." : "Choose a resident to begin.";
  for (const id of ["newRoomButton", "commonsButton", "everyoneButton", "bringWorkButton", "studioButton"]) $(id).disabled = !state.room || state.loading;
  $("newRoomButton").disabled = !state.room || state.loading || state.saving || state.sending || state.resuming;
  for (const roomButton of $("rooms").querySelectorAll("button")) roomButton.disabled = state.saving || state.sending || state.resuming;
  const artifact = latestArtifact(state.attachedId);
  $("attachedWork").textContent = artifact ? artifact.title + " · v" + artifact.version : "";
  renderRecovery();
}
async function sendMessage(event) {
  event.preventDefault(); if (!state.room || state.sending || state.resuming || pendingRound()) return;
  const text = $("composerText").value.trim();
  if (!text || !state.selected.size || state.selected.size > state.capabilities.max_participants) return;
  if (new TextEncoder().encode(text).length > 16384) { showError("composerError", "This message is too long. Keep it under 16 KiB, or save the draft in the studio."); return; }
  const roomId = state.room.id;
  const payload = { text, participants: [...state.selected], mode: state.selected.size === 1 ? "direct" : "council", artifact_ids: state.attachedId ? [state.attachedId] : [] };
  const fingerprint = JSON.stringify(payload);
  let previous;
  try { previous = JSON.parse(storageRead("kifoundry-home:request:" + roomId) || "null"); } catch { previous = null; }
  const requestId = previous?.fingerprint === fingerprint ? previous.id : crypto.randomUUID();
  storageWrite("kifoundry-home:request:" + roomId, JSON.stringify({ id: requestId, fingerprint }));
  state.sending = true; state.activityRoundId = ''; let submitted = false; showError("composerError"); persistDraft(); updateComposer();
  try {
    await api("/api/rooms/" + encodeURIComponent(roomId) + "/rounds", { ...payload, request_id: requestId });
    submitted = true;
    storageWrite("kifoundry-home:request:" + roomId, null);
    $("composerText").value = ""; persistDraft();
    const room = await api("/api/rooms/" + encodeURIComponent(roomId));
    if (state.room.id === roomId) adoptRoom(room);
  } catch (error) { showError("composerError", submitted ? "Your message was saved, but its progress could not be loaded. Reconnect to check the discussion." : error.message + " Check the saved discussion before changing and resending your draft."); await refreshRoom(); }
  finally { state.sending = false; updateComposer(); schedulePoll(); if (document.activeElement === document.body) $('composerText').focus({preventScroll:true}); }
}
async function cancelRound() {
  const round = activeRound(); if (!round || state.sending) return;
  $("cancelButton").disabled = true;
  try { await api("/api/rounds/" + encodeURIComponent(round.id) + "/cancel", {}); await refreshRoom(); }
  catch (error) { showError("composerError", error.message); }
  finally { updateComposer(); schedulePoll(); if (document.activeElement === document.body) $('composerText').focus({preventScroll:true}); }
}
async function resumeRound() {
  if (!state.room || $('resumeButton').disabled || state.resuming || pendingRound()) return;
  const roomId = state.room.id, epoch = state.epoch, roundId = $('recoverySelect').value;
  if (!state.room.rounds.some(round => round.id === roundId && recoveryInfo(round)?.canResume)) return;
  state.resuming = true; state.activityRoundId = roundId; showError('composerError'); persistDraft(); updateComposer();
  let submitted = false;
  try {
    // The server's safe default never repeats a previously launched uncertain call.
    const resumed = await api('/api/rounds/' + encodeURIComponent(roundId) + '/resume', {});
    submitted = true;
    if (epoch === state.epoch && state.room.id === roomId) {
      adoptRoom({...state.room, rounds: state.room.rounds.map(round => round.id === roundId ? resumed : round)});
      $('composerText').focus({preventScroll:true});
      const room = await api('/api/rooms/' + encodeURIComponent(roomId));
      if (epoch === state.epoch && state.room.id === roomId) adoptRoom(room);
    }
  } catch (error) {
    showError('composerError', submitted ? 'Resume was requested, but its progress could not be loaded. Reconnect to check the saved round.' : error.message);
    await refreshRoom();
  } finally { state.resuming = false; updateComposer(); schedulePoll(); }
}
async function refreshRoom() {
  if (!state.room) return;
  const roomId = state.room.id, epoch = state.epoch;
  try { const room = await api("/api/rooms/" + encodeURIComponent(roomId)); if (epoch === state.epoch && state.room.id === roomId) adoptRoom(room); }
  catch (error) { if (epoch === state.epoch) { state.connected=false; updateHouseStates(); showError("composerError", error.message); } }
}
function schedulePoll() {
  window.clearTimeout(state.poll);
  if (document.hidden || !state.room || !pendingRound()) return;
  state.poll = window.setTimeout(async () => { await refreshRoom(); schedulePoll(); }, 1500);
}

function artifactKey(artifact) { return artifact.id + ":" + artifact.version; }
function selectedArtifact() { return state.room?.artifacts.find((artifact) => artifactKey(artifact) === state.editKey) || null; }
function latestArtifact(id) { return state.room?.artifacts.filter((artifact) => artifact.id === id).sort((a, b) => b.version - a.version)[0] || null; }
function openStudio() { state.studioReturn=document.activeElement; toggle("studioPanel", true); $("artifactTitle").focus({ preventScroll: true }); }
function motionBehavior() { return matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"; }
function renderArtifacts() {
  const artifacts = state.room.artifacts;
  const options = [node("option", "New draft")]; options[0].value = "";
  for (const artifact of [...artifacts].sort((a, b) => a.title.localeCompare(b.title) || b.version - a.version)) {
    const option = node("option", artifact.title + " · v" + artifact.version); option.value = artifactKey(artifact); options.push(option);
  }
  $("artifactSelect").replaceChildren(...options);
  if (!artifacts.some((artifact) => artifactKey(artifact) === state.editKey)) state.editKey = "";
  $("artifactSelect").value = state.editKey;
  const selected = selectedArtifact();
  if (selected && !state.editDirty) { $("artifactTitle").value = selected.title; $("artifactContent").value = selected.content; }
  const latest = selected && latestArtifact(selected.id);
  const isLatest = selected && selected.version === latest.version;
  $("attachArtifact").disabled = !isLatest;
  $("attachArtifact").checked = Boolean(isLatest && state.attachedId === selected.id);
  $("saveArtifactButton").textContent = selected ? "Save new revision" : "Save draft";
  if (state.attachedId && !latestArtifact(state.attachedId)) state.attachedId = "";
  renderComparison(); updateComposer();
}
function selectArtifact(key) {
  preserveEditedWork();
  state.editKey = key; state.editDirty = false; showError("artifactError"); $("artifactNotice").textContent = "";
  const selected = selectedArtifact();
  $("artifactTitle").value = selected?.title || ""; $("artifactContent").value = selected?.content || "";
  renderArtifacts(); persistDraft();
}
function recoveryKey() { return 'kifoundry-home:recovered-work:'+state.room.id; }
function preserveEditedWork() {
  if(!state.room || !state.editDirty || !$("artifactContent").value.trim()) return;
  storageWrite(recoveryKey(),JSON.stringify({editKey:state.editKey,title:$("artifactTitle").value,content:$("artifactContent").value}));
  toggle('recoverDraftButton',true);
}
function recoverEditedWork() {
  let draft;try{draft=JSON.parse(storageRead(recoveryKey())||'null');}catch{return;}
  if(!draft || typeof draft.content!=='string')return;
  const current={editKey:state.editKey,title:$("artifactTitle").value,content:$("artifactContent").value};
  state.editKey=typeof draft.editKey==='string'?draft.editKey:'';state.editDirty=true;
  $("artifactTitle").value=typeof draft.title==='string'?draft.title:'';$("artifactContent").value=draft.content;
  if(current.content.trim()) storageWrite(recoveryKey(),JSON.stringify(current));
  else {storageWrite(recoveryKey(),null);toggle('recoverDraftButton',false);}
  renderArtifacts();persistDraft();$("artifactNotice").textContent='Unsaved edits recovered. Review before saving.';
}
function useMessageAsDraft(content) {
  openStudio(); $("artifactContent").value = content;
  if (!$("artifactTitle").value) $("artifactTitle").value = "Conversation draft";
  state.editDirty = true; $("artifactNotice").textContent = "Reply placed on the desk. Review it, then save a draft or revision.";
  persistDraft(); $("artifactContent").focus({ preventScroll: true });
}
function renderComparison() {
  const selected = selectedArtifact();
  const versions = selected ? state.room.artifacts.filter((artifact) => artifact.id === selected.id && artifact.version !== selected.version).sort((a, b) => a.version - b.version) : [];
  toggle("comparison", Boolean(selected && versions.length));
  if (!selected || !versions.length) return;
  const oldKey = $("compareSelect").value;
  $("compareSelect").replaceChildren(...versions.map((artifact) => { const option = node("option", "Version " + artifact.version); option.value = artifactKey(artifact); return option; }));
  if (versions.some((artifact) => artifactKey(artifact) === oldKey)) $("compareSelect").value = oldKey;
  const original = versions.find((artifact) => artifactKey(artifact) === $("compareSelect").value) || versions[0];
  $("originalLabel").textContent = original.title + " · v" + original.version;
  $("revisionLabel").textContent = selected.title + " · v" + selected.version;
  $("originalContent").textContent = original.content; $("revisionContent").textContent = selected.content;
}
async function saveArtifact(event) {
  event.preventDefault(); if (!state.room || state.saving) return;
  const title = $("artifactTitle").value.trim(), content = $("artifactContent").value;
  if (!title || !content.trim()) return;
  if (new TextEncoder().encode(content).length > 65536) { showError("artifactError", "This draft exceeds 64 KiB. Save a smaller section."); return; }
  const selected = selectedArtifact();
  const payload = { title, content };
  if (selected) { payload.artifact_id = selected.id; payload.expected_version = selected.version; }
  state.saving = true; $("saveArtifactButton").disabled = true; showError("artifactError"); updateComposer();
  try {
    const artifact = await api("/api/rooms/" + encodeURIComponent(state.room.id) + "/artifacts", payload);
    const room = await api("/api/rooms/" + encodeURIComponent(state.room.id));
    state.editKey = artifactKey(artifact); state.editDirty = false; state.attachedId = artifact.id;
    adoptRoom(room); persistDraft();
    $("artifactNotice").textContent = "Version " + artifact.version + " saved. It will be included in your next message.";
  } catch (error) { showError("artifactError", error.message + " Your edited draft is kept; existing versions have not been overwritten."); }
  finally { state.saving = false; $("saveArtifactButton").disabled = false; updateComposer(); if (document.activeElement === document.body) $('saveArtifactButton').focus({preventScroll:true}); }
}
async function createRoom(event) {
  event.preventDefault(); const title = $("newRoomTitle").value.trim(); if (!title) return;
  $("createRoomButton").disabled = true; showError("newRoomError");
  try {
    // Creation returns a summary. Load the complete conversation before adopting it.
    // If readback fails, the same Start action retries opening the confirmed saved room.
    const summary = state.newRoomPending?.title===title ? state.newRoomPending : await api("/api/rooms", { title });
    state.newRoomPending=summary;
    if(!state.rooms.some(room=>room.id===summary.id)) state.rooms=[summary,...state.rooms];
    renderRooms();
    const room=await api('/api/rooms/'+encodeURIComponent(summary.id));
    persistDraft(); ++state.epoch;
    adoptRoom(room, true); state.newRoomPending=null; $("newRoomDialog").close(); $("composerText").focus();
  } catch (error) { showError("newRoomError", state.newRoomPending ? 'Conversation saved. Press Start to try opening it again.' : error.message); }
  finally { $("createRoomButton").disabled = false; schedulePoll(); }
}

$("commonsButton").addEventListener("click", gatherEveryone);
$("everyoneButton").addEventListener("click", openDirectory);
$("residentsButton").addEventListener("click", openDirectory);
$("studioButton").addEventListener("click", openStudio);
$("bringWorkButton").addEventListener("click", openStudio);
$("closeStudioButton").addEventListener("click", () => { toggle("studioPanel", false); state.studioReturn?.focus({preventScroll:true}); });
$("composer").addEventListener("submit", sendMessage);
$("composerText").addEventListener("input", persistDraft);
$("composerText").addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !$("sendButton").disabled) { event.preventDefault(); $("composer").requestSubmit(); } });
$("cancelButton").addEventListener("click", cancelRound);
$('resumeButton').addEventListener('click', resumeRound);
$('recoverySelect').addEventListener('change', () => { state.activityRoundId = $('recoverySelect').value; state.activityKey = ''; renderActivity(); renderRecovery(); });
$("retryButton").addEventListener("click", boot);
$("artifactSelect").addEventListener("change", () => selectArtifact($("artifactSelect").value));
$("newDraftButton").addEventListener("click", () => selectArtifact(""));
$("recoverDraftButton").addEventListener("click", recoverEditedWork);
$("artifactForm").addEventListener("submit", saveArtifact);
for (const id of ["artifactTitle", "artifactContent"]) $(id).addEventListener("input", () => { state.editDirty = true; persistDraft(); });
$("attachArtifact").addEventListener("change", () => { state.attachedId = $("attachArtifact").checked ? selectedArtifact()?.id || "" : ""; persistDraft(); updateComposer(); });
$("compareSelect").addEventListener("change", renderComparison);
$("newRoomButton").addEventListener("click", () => { state.newRoomPending=null; $("newRoomTitle").value = ""; showError("newRoomError"); $("newRoomDialog").showModal(); });
$("dismissRoomButton").addEventListener("click", () => $("newRoomDialog").close());
$("newRoomForm").addEventListener("submit", createRoom);
document.addEventListener("visibilitychange", () => { if (document.hidden) window.clearTimeout(state.poll); else { refreshResidents(); refreshRoom().then(schedulePoll); } });
document.addEventListener('keydown', event => { if(event.key==='Escape' && !$('residentDirectoryPanel').classList.contains('hidden')) closeDirectory(); });
window.addEventListener("pagehide", persistDraft);
boot();
