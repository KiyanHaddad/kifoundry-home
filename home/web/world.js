import { HOMES_PER_DISTRICT, layoutTown } from './world-layout.js';
import { WorldCamera } from './world-camera.js';
import { createTerrain } from './world-terrain.js';

const phases = {proposal:'First thoughts', critique:'Challenge', synthesis:'Synthesis', reply:'Reply'};
const statuses = {queued:'Waiting', running:'Thinking', failed:'Could not reply', cancelled:'Stopped', interrupted:'Interrupted', completed:'Finished'};
const $ = id => document.getElementById(id);
function el(tag, text = '', className = '') {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}
function shortName(name) { return name.replace(/\s*\(fixture\)\s*$/, ''); }
function councilSeat(slot) {
  let index = slot;
  for (const [count, radius] of [[8,76], [16,145], [24,215], [16,285]]) {
    if (index < count) {
      const angle = -Math.PI / 2 + index * 2 * Math.PI / count;
      return [Math.cos(angle) * radius, 100 + Math.sin(angle) * radius * .72];
    }
    index -= count;
  }
  return [0,100];
}

/** A registry-driven world. Place and movement never establish provider success. */
export class TownWorld {
  constructor(onChoose) {
    this.onChoose = onChoose; this.entries = []; this.actors = new Map(); this.homes = new Map();
    this.timers = new Map(); this.markers = new Map(); this.knownDistricts = new Set([0]);
    this.selected = new Set(); this.connected = false; this.active = false; this.round = null;
    this.town = layoutTown([]); this.camera = new WorldCamera(this.town.bounds);
    this.initialized = false; this.terrainKey = ''; this.navigationKey = '';
    this.viewport = $('mapViewport'); this.surface = $('mapSurface'); this.extent = $('mapExtent');
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)');
    try { this.paused = localStorage.getItem('kifoundry-home:pause-wandering') === 'true'; }
    catch { this.paused = false; }
    $('motionButton').addEventListener('click', () => {
      this.paused = !this.paused;
      try { localStorage.setItem('kifoundry-home:pause-wandering', String(this.paused)); } catch { /* Optional preference. */ }
      this.applyMotionPreference();
    });
    this.reduced.addEventListener('change', () => this.applyMotionPreference());
    this.bindCamera();
    this.resize = new ResizeObserver(() => {
      this.camera.setViewport(this.viewport.clientWidth, this.viewport.clientHeight); this.paintCamera();
    });
    this.resize.observe(this.viewport);
    document.addEventListener('visibilitychange', () => { if (document.hidden) this.stopWalks(); });
    this.ambient = setInterval(() => this.wander(), 7000);
    window.addEventListener('pagehide', () => { clearInterval(this.ambient); this.stopWalks(); this.resize.disconnect(); });
    window.addEventListener('pageshow', event => {
      if (!event.persisted) return;
      this.resize.observe(this.viewport); clearInterval(this.ambient);
      this.ambient = setInterval(() => this.wander(),7000);
      this.camera.setViewport(this.viewport.clientWidth,this.viewport.clientHeight); this.paintCamera();
    });
    this.applyMotionPreference();
  }
  bindCamera() {
    $('zoomInButton').addEventListener('click', () => this.zoomBy(1.25));
    $('zoomOutButton').addEventListener('click', () => this.zoomBy(.8));
    $('commonsViewButton').addEventListener('click', () => this.goTo(0,100));
    $('fitTownButton').addEventListener('click', () => { this.camera.fit(); this.paintCamera(); });
    $('neighborhoodSelect').addEventListener('change', event => {
      const district = this.town.districts.find(item => String(item.id) === event.target.value);
      if (district) this.visitDistrict(district);
    });
    this.viewport.addEventListener('scroll', () => {
      this.camera.readScroll(this.viewport.scrollLeft, this.viewport.scrollTop);
    }, {passive:true});
    this.viewport.addEventListener('keydown', event => {
      if (event.target !== this.viewport || event.ctrlKey || event.metaKey || event.altKey) return;
      const steps = {ArrowLeft:[120,0], ArrowRight:[-120,0], ArrowUp:[0,120], ArrowDown:[0,-120]};
      if (steps[event.key]) this.camera.pan(...steps[event.key]);
      else if (event.key === '+' || event.key === '=') this.camera.setZoom(this.camera.zoom * 1.25);
      else if (event.key === '-') this.camera.setZoom(this.camera.zoom * .8);
      else if (event.key === 'Home') this.camera.moveTo(0,100,Math.max(.72,this.camera.zoom));
      else if (event.key === 'End') this.camera.fit();
      else return;
      event.preventDefault(); this.paintCamera();
    });
    this.viewport.addEventListener('pointerdown', event => {
      if (event.pointerType !== 'mouse' || event.button !== 0 || event.target.closest('button,select,a')) return;
      this.drag = {id:event.pointerId, x:event.clientX, y:event.clientY};
      this.viewport.setPointerCapture(event.pointerId); this.viewport.classList.add('dragging'); event.preventDefault();
    });
    this.viewport.addEventListener('pointermove', event => {
      if (!this.drag || this.drag.id !== event.pointerId) return;
      this.camera.pan(event.clientX - this.drag.x, event.clientY - this.drag.y);
      this.drag.x = event.clientX; this.drag.y = event.clientY; this.paintCamera();
    });
    const release = () => { this.drag = null; this.viewport.classList.remove('dragging'); };
    this.viewport.addEventListener('pointerup', release); this.viewport.addEventListener('pointercancel', release);
    this.viewport.addEventListener('lostpointercapture', release);
    this.viewport.addEventListener('focusin', event => {
      const target = event.target.closest('[data-agent-id]');
      if (!target) return;
      const box = target.getBoundingClientRect(), view = this.viewport.getBoundingClientRect();
      if (box.left < view.left + 24 || box.right > view.right - 24 || box.top < view.top + 24 || box.bottom > view.bottom - 24) {
        const entry = this.entries.find(item => item.agent.id === target.dataset.agentId);
        const point = target.classList.contains('resident-actor') ? this.actors.get(target.dataset.agentId)?.position : entry && [entry.plot.x,entry.plot.y];
        if (point) this.goTo(point[0],point[1]-25);
      }
    });
  }
  configure(agents, archived = []) {
    for (const resident of [...agents,...archived]) {
      if (Number.isInteger(resident.home_slot) && resident.home_slot >= 0 && resident.home_slot < 64) {
        // Keep the connecting neighborhoods, including vacant ones, on the map.
        for (let id=0; id<=Math.floor(resident.home_slot / HOMES_PER_DISTRICT); id++) this.knownDistricts.add(id);
      }
    }
    this.town = layoutTown(agents, this.knownDistricts); this.entries = this.town.entries;
    for (const district of this.town.districts) this.knownDistricts.add(district.id);
    this.camera.setViewport(this.viewport.clientWidth, this.viewport.clientHeight); this.camera.setBounds(this.town.bounds);
    if (!this.initialized) {
      const first = [...this.entries].sort((a,b) => a.slot - b.slot)[0], compact = this.viewport.clientWidth < 600;
      const close = compact || (first && first.district !== 0);
      if (close) this.camera.moveTo(first ? first.plot.x : 0,first ? first.plot.y-40 : 100,.8);
      else this.visitDistrict(this.town.districts[0]);
      this.initialized = true;
    }
    this.render();
  }
  focusResident(id) {
    const entry = this.entries.find(item => item.agent.id === id);
    if (entry) {
      const point = this.selected.has(id) ? councilSeat(entry.slot) : [entry.plot.x,entry.plot.y];
      this.goTo(point[0],point[1]-25);
    }
  }
  goTo(x,y) { this.camera.moveTo(x,y,Math.max(.72,this.camera.zoom)); this.paintCamera(); }
  visitDistrict(district) {
    const zoom = Math.max(.48,Math.min(.8,(this.viewport.clientWidth-24)/1040,(this.viewport.clientHeight-32)/900));
    this.camera.moveTo(district.x,district.y+5,zoom); this.paintCamera();
  }
  zoomBy(amount) { this.camera.setZoom(this.camera.zoom * amount); this.paintCamera(); }
  place(node,x,y) {
    node.style.left = (x - this.town.bounds.minX) + 'px'; node.style.top = (y - this.town.bounds.minY) + 'px';
  }
  paintCamera() {
    const frame = this.camera.frame();
    this.extent.style.width = frame.width + 'px'; this.extent.style.height = frame.height + 'px';
    this.surface.style.width = this.town.bounds.width + 'px'; this.surface.style.height = this.town.bounds.height + 'px';
    this.surface.style.left = frame.offsetX + 'px'; this.surface.style.top = frame.offsetY + 'px';
    this.surface.style.transform = 'scale(' + frame.scale + ')';
    this.surface.style.setProperty('--label-scale', String(1 / frame.scale));
    this.surface.style.setProperty('--marker-width', Math.min(154,Math.max(64,1150*frame.scale-14))+'px');
    this.surface.style.setProperty('--marker-font', frame.scale < .11 ? '11px' : '17px');
    $('town').classList.toggle('overview', frame.scale < .48);
    $('zoomLevel').textContent = Math.round(frame.scale * 100) + '%';
    $('zoomInButton').disabled = frame.scale >= 1.35; $('zoomOutButton').disabled = frame.scale <= .08;
    this.viewport.scrollLeft = frame.scrollLeft; this.viewport.scrollTop = frame.scrollTop;
    $('mapHint').textContent = frame.scale < .48 ? 'Overview · choose a neighborhood to visit' : 'Drag or swipe to explore · arrow keys move the map';
  }
  render() {
    const key = this.town.districts.map(item => item.id).join(',') + ':' + this.entries.map(entry => entry.slot).sort((a,b)=>a-b).join(',');
    if (key !== this.terrainKey) {
      this.surface.querySelector('.world-terrain')?.remove(); this.surface.prepend(createTerrain(this.town)); this.terrainKey = key;
    }
    const ids = new Set(this.entries.map(entry => entry.agent.id));
    for (const [id, home] of this.homes) if (!ids.has(id)) { home.remove(); this.homes.delete(id); }
    for (const [id, item] of this.actors) if (!ids.has(id)) { this.clearTimers(id); item.actor.remove(); this.actors.delete(id); }
    for (const entry of this.entries) {
      const {agent, plot, appearance} = entry; let home = this.homes.get(agent.id);
      if (!home) {
        home = el('button','','resident-home'); home.type = 'button'; home.dataset.agentId = agent.id;
        const picture = el('span','','house-picture'); picture.setAttribute('aria-hidden','true');
        const shadow = el('span','','house-shadow'); shadow.setAttribute('aria-hidden','true');
        const label = el('span','','house-label'); label.append(el('span','','home-name'),el('small','','home-status'));
        home.append(shadow,picture,label); home.addEventListener('click',()=>this.onChoose(agent.id)); this.homes.set(agent.id,home); $('houses').append(home);
      }
      this.place(home,plot.x,plot.y); home.style.zIndex = String(Math.round(plot.y - this.town.bounds.minY));
      home.querySelector('.house-picture').style.backgroundPosition = (-appearance * 217.2) + 'px -112px';
      home.querySelector('.home-name').textContent = shortName(agent.name); home.title = agent.name + (agent.role ? ' · ' + agent.role : '');
      let item = this.actors.get(agent.id);
      if (!item) {
        const actor = el('button','','resident-actor'); actor.type = 'button'; actor.dataset.agentId = agent.id;
        const sprite = el('span','','actor-sprite'); sprite.setAttribute('aria-hidden','true'); sprite.style.backgroundPosition = appearance * 25 + '% 0';
        actor.append(sprite,el('span','','actor-label')); actor.addEventListener('click',()=>this.onChoose(agent.id)); $('residents').append(actor);
        item = {actor,agent,home:plot.feet,position:plot.feet,target:plot.feet.join(',')}; this.actors.set(agent.id,item);
      }
      item.agent = agent; item.home = plot.feet; item.entry = entry; this.place(item.actor,...item.position);
      item.actor.style.zIndex = String(Math.round(item.position[1]-this.town.bounds.minY)+2);
    }
    this.renderNavigation(); this.renderMarkers();
    this.place($('commonsButton'),this.town.commons.x,this.town.commons.y);
    this.place($('studioButton'),this.town.studio.x,this.town.studio.y);
    $('residentCount').textContent = this.entries.length + ' residents · ' + this.town.districts.length + (this.town.districts.length === 1 ? ' neighborhood' : ' neighborhoods');
    this.paintCamera(); this.update(this.selected,this.round,this.connected);
  }
  renderNavigation() {
    const key = this.town.districts.map(item => item.id + ':' + item.count).join(',');
    if (key === this.navigationKey) return;
    const select = $('neighborhoodSelect'), previous = select.value;
    select.replaceChildren(el('option','Choose a neighborhood')); select.firstElementChild.value = '';
    for (const district of this.town.districts) {
      const option = el('option',district.name + ' · ' + district.count + '/8 homes'); option.value = String(district.id); select.append(option);
    }
    select.value = this.town.districts.some(item => String(item.id) === previous) ? previous : ''; this.navigationKey = key;
  }
  renderMarkers() {
    for (const district of this.town.districts) {
      let marker = this.markers.get(district.id);
      if (!marker) {
        marker = el('button','','map-neighborhood-marker'); marker.type = 'button';
        marker.addEventListener('click',()=>this.visitDistrict(district));
        marker.append(el('strong',district.name),el('span','','marker-count')); this.markers.set(district.id,marker); $('mapMarkers').append(marker);
      }
      marker.querySelector('.marker-count').textContent = district.count + (district.count === 1 ? ' resident' : ' residents');
      marker.setAttribute('aria-label','Visit '+district.name+', '+district.count+' residents'); this.place(marker,...district.hub);
    }
  }
  update(selected,round,connected = true) {
    this.selected = new Set(selected); this.round = round; this.connected = connected;
    this.active = Boolean(round && (['queued','running'].includes(round.status) || (round.turns || []).some(turn=>['queued','running'].includes(turn.status))));
    for (const entry of this.entries) {
      const id = entry.agent.id, chosen = selected.has(id), turns = (round?.turns || []).filter(turn=>turn.agent_id === id);
      const turn = turns.find(item=>item.status === 'running') || turns.at(-1);
      const status = !connected ? 'unknown' : entry.agent.available === false ? 'unavailable' : this.active && turn ? turn.status : 'idle';
      const text = status === 'unknown' ? 'Status unknown' : status === 'unavailable' ? 'Needs connection' : status === 'idle' ? (chosen ? 'At the commons' : 'At home') : (statuses[status] || status);
      const home = this.homes.get(id), item = this.actors.get(id);
      home.setAttribute('aria-pressed',String(chosen)); home.dataset.working = String(status === 'running');
      home.setAttribute('aria-label','Talk with '+entry.agent.name+'. '+text); home.querySelector('.home-status').textContent = text;
      item.actor.setAttribute('aria-pressed',String(chosen)); item.actor.dataset.status = status; item.actor.querySelector('.actor-label').textContent = shortName(entry.agent.name);
      item.actor.setAttribute('aria-label','Talk with '+entry.agent.name+'. '+text+(this.active && turn ? ' · '+(phases[turn.phase] || turn.phase) : ''));
      const destination = chosen ? councilSeat(entry.slot) : item.home;
      if (item.target !== destination.join(',')) this.walk(id,destination);
    }
    const names = this.entries.filter(entry=>selected.has(entry.agent.id)).map(entry=>shortName(entry.agent.name));
    $('worldStatus').textContent = !connected ? 'Status unknown · reconnect to check.' : this.active ? 'Replies in progress.' : names.length > 1 ? 'Council selected · '+names.length+' guests.' : names.length ? 'Talking with '+names[0]+'.' : 'Choose a home to talk.';
  }
  walk(id,destination,ambient = false) {
    const item = this.actors.get(id); if (!item) return;
    this.clearTimers(id); item.target = destination.join(',');
    const place = point => { this.place(item.actor,...point); item.position = point; item.actor.style.zIndex = String(Math.round(point[1] - this.town.bounds.minY) + 2); };
    const offscreen = Math.abs(item.position[0] - this.camera.x) > this.viewport.clientWidth / this.camera.zoom || Math.abs(item.position[1] - this.camera.y) > this.viewport.clientHeight / this.camera.zoom;
    if (this.paused || this.reduced.matches || document.hidden || this.timers.size >= 8 || offscreen) { place(destination); item.actor.classList.remove('walking'); return; }
    item.actor.classList.add('walking');
    const hub = this.town.districts.find(district=>district.id === item.entry.district)?.hub || [0,100], route = ambient ? [destination] : [hub,destination];
    const timers = route.map((point,index)=>setTimeout(()=>place(point),index * 1100));
    timers.push(setTimeout(()=> {
      item.actor.classList.remove('walking'); this.timers.delete(id);
      if (ambient && !this.selected.has(id)) this.walk(id,item.home);
    },route.length * 1100));
    this.timers.set(id,timers);
  }
  wander() {
    if (this.paused || this.reduced.matches || this.active || !this.connected || document.hidden || this.camera.zoom < .48) return;
    const item = [...this.actors.values()].find(item=>!this.selected.has(item.agent.id) && !this.timers.has(item.agent.id) && document.activeElement !== item.actor && !item.actor.matches(':hover') && Math.abs(item.home[0]-this.camera.x) < this.viewport.clientWidth/(2*this.camera.zoom) && Math.abs(item.home[1]-this.camera.y) < this.viewport.clientHeight/(2*this.camera.zoom));
    if (item) this.walk(item.agent.id,[item.home[0]+28,item.home[1]+22],true);
  }
  clearTimers(id) { for (const timer of this.timers.get(id) || []) clearTimeout(timer); this.timers.delete(id); }
  stopWalks() {
    for (const [id,item] of this.actors) {
      this.clearTimers(id); item.actor.classList.remove('walking'); const point = item.target.split(',').map(Number); this.place(item.actor,...point); item.position = point;
      item.actor.style.zIndex = String(Math.round(point[1]-this.town.bounds.minY)+2);
    }
  }
  applyMotionPreference() {
    const button = $('motionButton'); button.textContent = this.reduced.matches ? 'Reduced motion' : this.paused ? 'Resume motion' : 'Pause motion';
    button.disabled = this.reduced.matches; button.setAttribute('aria-pressed',String(this.paused || this.reduced.matches));
    $('town').classList.toggle('motion-paused',this.paused || this.reduced.matches);
    if (this.paused || this.reduced.matches) this.stopWalks();
  }
}

