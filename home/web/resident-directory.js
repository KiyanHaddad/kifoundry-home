/** Resident management view. Callbacks own persistence; this module renders inert DOM only. */
let directoryNumber = 0;

const activeStatuses = new Set(['queued', 'running']);
const phaseNames = { reply: 'reply', proposal: 'first thoughts', critique: 'challenge', synthesis: 'synthesis' };

export class ResidentDirectory {
  constructor(panelElement, callbacks) {
    if (!panelElement?.ownerDocument) throw new TypeError('ResidentDirectory needs a panel element.');
    for (const action of ['add', 'archive', 'restore', 'talk', 'select', 'selectAll', 'close']) {
      if (typeof callbacks?.[action] !== 'function') throw new TypeError(`ResidentDirectory needs a ${action} callback.`);
    }
    this.document = panelElement.ownerDocument;
    this.callbacks = callbacks;
    this.rows = new Map();
    this.archivedRows = new Map();
    this.state = { agents: [], archived_agents: [], resident_bindings: [], selected: new Set(), round: null, connected: false };
    this.pending = null;
    this.rosterKey = '';
    this.bindingKey = '';
    this.prefix = `resident-directory-${++directoryNumber}`;

    this.root = this.element('section', '', 'resident-directory');
    const heading = this.element('div', '', 'directory-heading');
    const introduction = this.element('div');
    const title = this.element('h2', 'Residents');
    title.id = `${this.prefix}-title`;
    this.root.setAttribute('aria-labelledby', title.id);
    introduction.append(title, this.element('p', 'Talk one to one, gather Council, or make room for someone new.', 'directory-introduction'));
    this.closeButton = this.button('Close residents', 'text-button directory-close', () => this.perform('close'));
    heading.append(introduction, this.closeButton);

    this.search = this.element('input', '', 'directory-search');
    this.search.type = 'search';
    this.search.maxLength = 120;
    this.search.id = `${this.prefix}-search`;
    this.search.placeholder = 'Find a name or role';
    this.search.addEventListener('input', () => this.filterRows());
    const searchLabel = this.label('Find a resident', this.search, 'directory-search-label');
    this.count = this.element('p', '', 'directory-count');
    this.count.setAttribute('role', 'status');
    this.count.setAttribute('aria-live', 'polite');
    this.inviteAll=this.button('Invite everyone','small-button directory-all',()=>this.perform('selectAll'));
    this.list = this.element('ul', '', 'directory-list');
    this.list.setAttribute('aria-label', 'Current residents');
    this.empty = this.element('p', '', 'directory-empty');

    this.archived = this.element('details', '', 'directory-archived');
    this.archivedSummary = this.element('summary', 'Moved out');
    this.archivedList = this.element('ul', '', 'directory-list directory-archived-list');
    this.archivedList.setAttribute('aria-label', 'Residents who moved out');
    this.archived.append(this.archivedSummary, this.element('p', 'Their conversations stay saved. Bring someone back whenever you want.', 'directory-help'), this.archivedList);

    this.form = this.element('form', '', 'directory-add-form');
    const addTitle = this.element('h3', 'Add a resident');
    this.nameInput = this.element('input', '', 'directory-name-input');
    this.nameInput.id = `${this.prefix}-name`;
    this.nameInput.name = 'name';
    this.nameInput.required = true;
    this.nameInput.maxLength = 60;
    this.nameInput.autocomplete = 'off';
    this.nameInput.placeholder = 'What should we call them?';
    this.nameInput.addEventListener('input', () => this.nameInput.setCustomValidity(''));
    this.roleInput = this.element('textarea', '', 'directory-role-input');
    this.roleInput.id = `${this.prefix}-role`;
    this.roleInput.name = 'role';
    this.roleInput.rows = 3;
    this.roleInput.placeholder = 'What do they help with?';
    this.roleInput.addEventListener('input', () => this.roleInput.setCustomValidity(''));
    this.bindingSelect = this.element('select', '', 'directory-binding-select');
    this.bindingSelect.id = `${this.prefix}-binding`;
    this.bindingSelect.name = 'binding_id';
    this.bindingSelect.required = true;
    this.addHint = this.element('p', '', 'directory-help directory-add-hint');
    this.addHint.id = `${this.prefix}-add-hint`;
    this.bindingSelect.setAttribute('aria-describedby', this.addHint.id);
    this.addButton = this.element('button', 'Add resident', 'primary-button directory-add-button');
    this.addButton.type = 'submit';
    this.form.append(addTitle, this.label('Name', this.nameInput), this.label('Role · optional', this.roleInput),
      this.label('Replies using', this.bindingSelect), this.addHint, this.addButton);
    this.form.addEventListener('submit', (event) => { event.preventDefault(); this.addResident(); });

    this.error = this.element('p', '', 'inline-error directory-error');
    this.error.setAttribute('role', 'alert');
    this.error.hidden = true;
    this.notice = this.element('p', '', 'directory-notice');
    this.notice.setAttribute('role', 'status');
    this.notice.setAttribute('aria-live', 'polite');
    this.notice.hidden = true;
    this.root.append(heading, searchLabel, this.count, this.inviteAll, this.error, this.list, this.empty, this.archived, this.form, this.notice);
    panelElement.replaceChildren(this.root);
    this.render(this.state);
  }

  element(tag, content = '', className = '') {
    const element = this.document.createElement(tag);
    if (content) element.textContent = String(content);
    if (className) element.className = className;
    return element;
  }

  label(text, control, className = 'directory-field') {
    const label = this.element('label', text, className);
    label.htmlFor = control.id;
    label.append(control);
    return label;
  }

  button(text, className, callback) {
    const button = this.element('button', text, className);
    button.type = 'button';
    button.addEventListener('click', callback);
    return button;
  }

  /** Form values and existing row nodes survive ordinary status/selection polling. */
  render({ agents = [], archived_agents = [], resident_bindings = [], selected = [], round = null, connected = false, capabilities = {max_participants:5,max_residents:64} } = {}) {
    this.state = {
      agents: this.uniqueResidents(agents).filter((agent) => !agent.archived),
      archived_agents: this.uniqueResidents(archived_agents),
      resident_bindings: Array.isArray(resident_bindings) ? resident_bindings.filter((binding) => typeof binding?.id === 'string') : [],
      selected: selected instanceof Set ? selected : new Set(Array.isArray(selected) ? selected : []),
      round, capabilities, connected: connected === true,
    };
    const rosterKey = JSON.stringify([this.state.agents, this.state.archived_agents]);
    if (rosterKey !== this.rosterKey) {
      this.reconcile(this.list, this.rows, this.state.agents, false);
      this.reconcile(this.archivedList, this.archivedRows, this.state.archived_agents, true);
      this.rosterKey = rosterKey;
    }
    const bindingKey = JSON.stringify(this.state.resident_bindings);
    if (bindingKey !== this.bindingKey) {
      const selectedBinding = this.bindingSelect.value;
      const options = this.state.resident_bindings.map((binding) => {
        const label = typeof binding.label === 'string' && binding.label ? binding.label : this.providerName(binding.provider);
        const provider = this.providerName(binding.provider);
        const option = this.element('option', label.toLocaleLowerCase().includes(provider.toLocaleLowerCase()) ? label : `${label} · ${provider}`);
        option.value = binding.id;
        return option;
      });
      if (!options.length) {
        const option = this.element('option', 'No provider connection available');
        option.value = '';
        options.push(option);
      } else if (selectedBinding && !this.state.resident_bindings.some((binding) => binding.id === selectedBinding)) {
        const option = this.element('option', 'Previous connection unavailable · choose another');
        option.value = '';
        option.disabled = true;
        options.unshift(option);
      }
      this.bindingSelect.replaceChildren(...options);
      if (this.state.resident_bindings.some((binding) => binding.id === selectedBinding)) this.bindingSelect.value = selectedBinding;
      this.bindingKey = bindingKey;
    }
    this.patchState();
    this.filterRows();
  }

  uniqueResidents(residents) {
    if (!Array.isArray(residents)) return [];
    const unique = new Map();
    for (const resident of residents) if (typeof resident?.id === 'string') unique.set(resident.id, resident);
    return [...unique.values()];
  }

  reconcile(list, rows, residents, archived) {
    const present = new Set(residents.map((resident) => resident.id));
    for (const [id, row] of rows) {
      if (!present.has(id)) { row.element.remove(); rows.delete(id); }
    }
    residents.forEach((resident, index) => {
      let row = rows.get(resident.id);
      if (!row) { row = this.createRow(resident.id, archived); rows.set(resident.id, row); }
      row.resident = resident;
      row.name.textContent = resident.name || 'Unnamed resident';
      row.provider.textContent = this.providerName(resident.provider);
      row.roleContent.textContent = resident.role || 'No specific role yet.';
      row.role.hidden = !resident.role;
      if (list.children[index] !== row.element) list.insertBefore(row.element, list.children[index] || null);
    });
  }

  createRow(id, archived) {
    const element = this.element('li', '', 'directory-resident');
    element.dataset.residentId = id;
    const description = this.element('div', '', 'directory-resident-description');
    const name = this.element('h3', '', 'directory-resident-name');
    const provider = this.element('p', '', 'directory-resident-provider');
    const status = this.element('p', '', 'directory-resident-status');
    const selected = this.element('span', 'Selected', 'directory-selected');
    selected.hidden = true;
    const role = this.element('details', '', 'directory-resident-role');
    const roleContent = this.element('p', '', 'directory-role-content');
    role.append(this.element('summary', 'Role'), roleContent);
    description.append(name, provider, status, selected, role);
    const actions = this.element('div', '', 'directory-resident-actions');
    const talk = archived ? null : this.button('Talk', 'small-button directory-talk', () => this.perform('talk', id));
    const invite = archived ? null : this.button('Invite to Council', 'small-button directory-invite', () => this.perform('select', id));
    const action = this.button(archived ? 'Bring back' : 'Move out', 'text-button directory-resident-action', () => this.perform(archived ? 'restore' : 'archive', id));
    if (talk) actions.append(talk, invite);
    actions.append(action);
    element.append(description, actions);
    return { element, name, provider, status, selected, role, roleContent, talk, invite, action, resident: null };
  }

  providerName(provider) {
    if (provider === 'claude') return 'Claude';
    if (provider === 'codex') return 'Codex';
    if (provider === 'fixture') return 'Fixture demo · simulated replies';
    return typeof provider === 'string' && provider ? provider : 'Provider';
  }

  roundBusy() {
    return activeStatuses.has(this.state.round?.status) ||
      (Array.isArray(this.state.round?.turns) && this.state.round.turns.some((turn) => activeStatuses.has(turn.status)));
  }

  statusFor(resident, archived) {
    if (archived) return resident.available === false ? 'Moved out · needs a connection to return' : 'Moved out · conversations saved';
    if (resident.available === false) return 'Needs a connection';
    if (!this.state.connected) return 'Home disconnected';
    const turns = Array.isArray(this.state.round?.turns) ? this.state.round.turns.filter((turn) => turn.agent_id === resident.id) : [];
    const current = turns.find((turn) => turn.status === 'running') || turns.find((turn) => turn.status === 'queued') || turns.at(-1);
    if (current?.status === 'running') return `Thinking · ${phaseNames[current.phase] || 'reply'}`;
    if (current?.status === 'queued') return 'Waiting to reply';
    if (current?.status === 'completed') return 'Reply saved';
    if (current?.status === 'failed') return 'Could not reply · earlier work is saved';
    if (current?.status === 'cancelled') return 'Stopped · saved replies kept';
    if (current?.status === 'interrupted') return 'Interrupted · saved replies kept';
    return 'Ready to talk';
  }

  patchState() {
    const mutationBlocked = Boolean(this.pending) || !this.state.connected || this.roundBusy();
    const available=this.state.agents.filter(agent=>agent.available!==false).length;
    this.inviteAll.textContent='Invite all '+available+' available residents';
    this.inviteAll.disabled=Boolean(this.pending)||!this.state.connected||!available||available>this.state.capabilities.max_participants;
    for (const [archived, rows] of [[false, this.rows], [true, this.archivedRows]]) {
      for (const [id, row] of rows) {
        const selected = !archived && this.state.selected.has(id);
        row.element.classList.toggle('is-selected', selected);
        row.element.classList.toggle('is-unavailable', row.resident.available === false);
        row.selected.hidden = !selected;
        row.status.textContent = this.statusFor(row.resident, archived);
        if (row.talk) {
          row.talk.disabled = Boolean(this.pending) || !this.state.connected || row.resident.available === false;
          row.talk.setAttribute('aria-pressed', String(selected));
          row.talk.setAttribute('aria-label', `Talk with ${row.resident.name || 'this resident'}`);
        }
        if (row.invite) {
          row.invite.disabled = Boolean(this.pending) || !this.state.connected || row.resident.available === false;
          row.invite.textContent = selected ? 'At the table' : 'Invite to Council';
          row.invite.setAttribute('aria-pressed', String(selected));
          row.invite.setAttribute('aria-label', `${selected ? 'Remove' : 'Invite'} ${row.resident.name || 'this resident'} ${selected ? 'from' : 'to'} Council`);
        }
        row.action.disabled = mutationBlocked || (archived && row.resident.available === false);
        const rowMutation = this.pending?.id === id && ['archive', 'restore'].includes(this.pending.action);
        row.action.textContent = rowMutation ? (archived ? 'Bringing back…' : 'Moving out…') : (archived ? 'Bring back' : 'Move out');
        row.action.setAttribute('aria-label', `${archived ? 'Bring back' : 'Move out'} ${row.resident.name || 'this resident'}${archived ? '' : '; conversations stay saved'}`);
      }
    }
    const bindingsAvailable = this.state.resident_bindings.length > 0;
    const creationBlocked = mutationBlocked || !bindingsAvailable || this.state.agents.length >= 64;
    for (const field of [this.nameInput, this.roleInput, this.bindingSelect, this.addButton]) field.disabled = creationBlocked;
    this.addButton.textContent = this.pending?.action === 'add' ? 'Adding…' : 'Add resident';
    this.addHint.textContent = !this.state.connected ? 'Reconnect Home to change the residents.' :
      !bindingsAvailable ? 'Set up a provider connection locally to add a resident.' :
      this.state.agents.length >= 64 ? 'The town has 64 residents. Move someone out before adding another.' :
      this.roundBusy() ? 'Wait for the conversation to finish before adding or moving residents.' :
      'Each resident gets their own conversations through an existing provider connection.';
    this.archived.hidden = this.state.archived_agents.length === 0;
    this.archivedSummary.textContent = `Moved out (${this.state.archived_agents.length})`;
    this.root.setAttribute('aria-busy', String(Boolean(this.pending)));
  }

  filterRows() {
    const query = this.search.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const rows of [this.rows, this.archivedRows]) {
      for (const row of rows.values()) {
        const searchable = [row.resident.name, row.resident.role, row.resident.provider].filter(Boolean).join(' ').toLocaleLowerCase();
        row.element.hidden = Boolean(query) && !searchable.includes(query);
        if (rows === this.rows && !row.element.hidden) visible += 1;
      }
    }
    const total = this.state.agents.length;
    this.count.textContent = (query ? `${visible} of ${total} current residents` : `${total} current ${total === 1 ? 'resident' : 'residents'}`)+` · ${this.state.selected.size} invited`;
    this.empty.hidden = visible > 0;
    this.empty.textContent = total ? 'No current residents match your search.' : 'There are no residents in town yet. Add someone below, or bring a resident back.';
  }

  async addResident() {
    if (this.addButton.disabled) return;
    const name = this.nameInput.value.trim();
    const role = this.roleInput.value.trim();
    this.nameInput.setCustomValidity(!name ? 'Give the resident a name.' : Array.from(name).length > 60 ? 'Keep the name within 60 characters.' : '');
    this.roleInput.setCustomValidity(new TextEncoder().encode(role).length > 4096 ? 'The role is too long. Keep it within 4 KiB of text.' : '');
    if (!this.form.reportValidity()) return;
    const binding_id = this.bindingSelect.value;
    if (!this.state.resident_bindings.some((binding) => binding.id === binding_id)) return;
    await this.perform('add', null, { name, role, binding_id });
  }

  async perform(action, id = null, payload = undefined) {
    if (action === 'close') {
      try { await this.callbacks.close(); } catch (error) { this.showError(error); }
      return;
    }
    if (this.pending) return;
    const focusWasInside = this.root.contains(this.document.activeElement);
    this.error.hidden = true;
    this.notice.hidden = true;
    this.pending = { action, id };
    this.patchState();
    try {
      await this.callbacks[action](action === 'add' ? payload : id);
      if (action === 'add') { this.nameInput.value = ''; this.roleInput.value = ''; }
      const messages = { add: 'Resident added to the town.', archive: 'Resident moved out. Their conversations stay saved.', restore: 'Resident brought back to the town.' };
      this.notice.textContent = messages[action] || '';
      this.notice.hidden = !messages[action];
    } catch (error) { this.showError(error); }
    finally {
      this.pending = null;
      this.patchState();
      if (action === 'add' && focusWasInside && this.root.getClientRects().length && !this.nameInput.disabled) {
        this.nameInput.focus({ preventScroll: true });
      }
      if (['archive', 'restore'].includes(action) && focusWasInside &&
          !this.root.contains(this.document.activeElement) && this.root.getClientRects().length) {
        this.search.focus({ preventScroll: true });
      }
    }
  }

  showError(error) {
    this.error.textContent = typeof error?.message === 'string' && error.message ? error.message.slice(0, 800) : 'That action could not be completed. Your saved conversations are kept.';
    this.error.hidden = false;
  }
}
