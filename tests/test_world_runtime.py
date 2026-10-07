"""Exercise the town's registry, navigation and motion behavior without a browser renderer."""

import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
WORLD_MODULE = Path(__file__).resolve().parents[1] / "home" / "web" / "world.js"

RUNTIME_SCENARIOS = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const {HOMES_PER_DISTRICT, layoutTown} = await import(process.argv[2]);
const {WorldCamera} = await import(process.argv[3]);
const source = readFileSync(process.argv[1], 'utf8')
  .replace(/^import .*;\r?$/gm, '').replace('export class TownWorld', 'class TownWorld');
const scenario = process.argv[4];
const plain = value => JSON.parse(JSON.stringify(value));
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-7,
  `Expected ${actual} to be near ${expected}`);
const nodes = new Map(), timeouts = new Map(), intervals = new Map();
let timerId = 0, terrainBuilds = 0, observer;

class Element {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase(); this.id = id; this.parentElement = null;
    this.children = []; this.dataset = {}; this.attributes = {}; this.listeners = new Map();
    this.className = ''; this.style = {setProperty(name,value){this[name] = value;}};
    this.value = ''; this.clientWidth = 800; this.clientHeight = 520;
    this.scrollLeft = 0; this.scrollTop = 0; this._text = '';
    const classes = () => new Set(this.className.split(/\s+/).filter(Boolean));
    this.classList = {
      add:(...names) => {const set = classes(); names.forEach(name=>set.add(name)); this.className = [...set].join(' ');},
      remove:(...names) => {const set = classes(); names.forEach(name=>set.delete(name)); this.className = [...set].join(' ');},
      contains:name => classes().has(name),
      toggle:(name,force) => {
        const set = classes(), enabled = force === undefined ? !set.has(name) : force;
        enabled ? set.add(name) : set.delete(name); this.className = [...set].join(' '); return enabled;
      },
    };
  }
  get textContent(){return this._text + this.children.map(child=>child.textContent).join('');}
  set textContent(value){this._text = String(value); this.replaceChildren();}
  get firstElementChild(){return this.children[0] || null;}
  append(...children){for(const child of children){child.remove(); child.parentElement = this; this.children.push(child);}}
  prepend(child){child.remove(); child.parentElement = this; this.children.unshift(child);}
  replaceChildren(...children){for(const child of this.children)child.parentElement = null; this.children = []; this.append(...children);}
  remove(){if(this.parentElement){const parent = this.parentElement; parent.children = parent.children.filter(item=>item !== this); this.parentElement = null;}}
  setAttribute(name,value){this.attributes[name] = String(value);}
  getAttribute(name){return this.attributes[name] ?? null;}
  addEventListener(name,listener){if(!this.listeners.has(name))this.listeners.set(name,[]); this.listeners.get(name).push(listener);}
  dispatch(name,options = {}){
    const event = {target:this, defaultPrevented:false, preventDefault(){this.defaultPrevented = true;}, ...options};
    for(const listener of this.listeners.get(name) || [])listener(event);
    return event;
  }
  matches(selector){
    if(selector === ':hover')return false;
    if(selector.startsWith('.'))return this.classList.contains(selector.slice(1));
    if(selector === '[data-agent-id]')return this.dataset.agentId !== undefined;
    return this.tagName === selector.toUpperCase();
  }
  closest(selectors){
    for(let item = this; item; item = item.parentElement){
      if(selectors.split(',').some(selector=>item.matches(selector.trim())))return item;
    }
    return null;
  }
  querySelector(selector){
    for(const child of this.children){if(child.matches(selector))return child; const found = child.querySelector(selector); if(found)return found;}
    return null;
  }
  setPointerCapture(id){this.capturedPointer = id;}
  focus(){document.activeElement = this;}
  getBoundingClientRect(){
    const viewport = nodes.get('mapViewport');
    if(this === viewport)return {left:0, top:0, right:this.clientWidth, bottom:this.clientHeight};
    const surface = nodes.get('mapSurface'), scale = Number(surface.style.transform?.match(/scale\(([^)]+)\)/)?.[1] || 1);
    const actor = this.classList.contains('resident-actor'), width = actor ? 58 : 190, height = actor ? 96 : 150;
    const anchorX = Number.parseFloat(this.style.left || 0), anchorY = Number.parseFloat(this.style.top || 0);
    const left = Number.parseFloat(surface.style.left || 0) + (anchorX - width / 2) * scale - viewport.scrollLeft;
    const top = Number.parseFloat(surface.style.top || 0) + (anchorY - height) * scale - viewport.scrollTop;
    return {left, top, right:left + width * scale, bottom:top + height * scale};
  }
}

const body = new Element('body');
for(const id of ['town','mapViewport','mapSurface','mapExtent','houses','residents','mapMarkers',
  'motionButton','zoomInButton','zoomOutButton','commonsViewButton','fitTownButton',
  'neighborhoodSelect','zoomLevel','mapHint','commonsButton','studioButton','residentCount','worldStatus']) {
  const node = new Element(id.endsWith('Button') ? 'button' : id === 'neighborhoodSelect' ? 'select' : 'div', id);
  nodes.set(id,node); body.append(node);
}
const get = id => nodes.get(id), viewport = get('mapViewport');
get('town').append(viewport); viewport.append(get('mapExtent')); get('mapExtent').append(get('mapSurface'));
get('mapSurface').append(get('houses'),get('residents'),get('mapMarkers'),get('commonsButton'),get('studioButton'));
const document = new Element('document');
document.hidden = false; document.activeElement = body;
document.createElement = tag => new Element(tag);
document.getElementById = get;
const window = new Element('window'), media = new Element('media'); media.matches = false;
const context = {
  document, window, HOMES_PER_DISTRICT, layoutTown, WorldCamera,
  matchMedia:() => media, localStorage:{getItem:() => null, setItem(){}},
  ResizeObserver:class {
    constructor(callback){this.callback = callback; this.observations = 0; observer = this;}
    observe(target){this.target = target; this.disconnected = false; this.observations++;}
    disconnect(){this.disconnected = true;}
  },
  setTimeout:(callback,delay) => {const id = ++timerId; timeouts.set(id,{callback,delay}); return id;},
  clearTimeout:id => timeouts.delete(id),
  setInterval:(callback,delay) => {const id = ++timerId; intervals.set(id,{callback,delay}); return id;},
  clearInterval:id => intervals.delete(id),
  createTerrain:() => {terrainBuilds++; const terrain = new Element('svg'); terrain.className = 'world-terrain'; return terrain;},
};
runInNewContext(source + '\nglobalThis.TownWorld=TownWorld;',context);
const chosen = [], world = new context.TownWorld(id=>chosen.push(id));
const resident = slot => ({id:'synthetic-resident-' + slot, name:'Resident ' + slot,
  provider:'fixture', home_slot:slot, available:true, role:'Synthetic workshop resident'});
const residents = count => Array.from({length:count},(_,index)=>resident(index));
const location = node => [Number.parseFloat(node.style.left) + world.town.bounds.minX,
  Number.parseFloat(node.style.top) + world.town.bounds.minY];
const cameraPlace = () => [world.camera.x,world.camera.y,world.camera.zoom];
const residentNodes = () => new Map([...world.homes].map(([id,home]) => [id,
  {home, actor:world.actors.get(id).actor, homePlace:location(home), actorPlace:location(world.actors.get(id).actor)}]));
const checkRetained = original => {
  for(const [id,saved] of original){
    assert.equal(world.homes.get(id),saved.home, 'An existing home DOM node was replaced');
    assert.equal(world.actors.get(id).actor,saved.actor, 'An existing actor DOM node was replaced');
    assert.deepEqual(location(saved.home),saved.homePlace, 'An existing home moved in world coordinates');
    assert.deepEqual(location(saved.actor),saved.actorPlace, 'An existing actor moved in world coordinates');
  }
};

if(scenario === 'capacity') {
  world.configure(residents(64));
  assert.equal(world.entries.length,64); assert.equal(world.homes.size,64); assert.equal(world.actors.size,64);
  assert.equal(get('houses').children.length,64); assert.equal(get('residents').children.length,64);
  assert.equal(world.town.districts.length,8); assert.equal(get('neighborhoodSelect').children.length,9);
  for(const entry of world.entries){
    const home = world.homes.get(entry.agent.id), actor = world.actors.get(entry.agent.id).actor;
    assert.deepEqual(location(home),[entry.plot.x,entry.plot.y]);
    assert.deepEqual(location(actor),plain(entry.plot.feet));
    assert.equal(home.parentElement,get('houses')); assert.equal(actor.parentElement,get('residents'));
    assert.ok(Number.isFinite(Number(actor.style.zIndex)), 'A new actor has no depth ordering');
    assert.ok(Number(actor.style.zIndex) > Number(home.style.zIndex), 'An actor at the door is layered behind its home');
  }
  world.homes.get(resident(63).id).dispatch('click'); world.actors.get(resident(63).id).actor.dispatch('click');
  assert.deepEqual(chosen,[resident(63).id,resident(63).id]);
} else if(scenario === 'growth') {
  const initial = residents(8); world.configure(initial);
  world.camera.moveTo(0,40,.72); world.paintCamera();
  const original = residentNodes(), camera = cameraPlace();
  world.configure([...initial,resident(8)]); checkRetained(original);
  assert.deepEqual(cameraPlace(),camera); assert.equal(world.homes.size,9);
  const grownBounds = plain(world.town.bounds);
  world.configure(initial); checkRetained(original);
  assert.deepEqual(cameraPlace(),camera); assert.deepEqual(plain(world.town.bounds),grownBounds);
  assert.equal(world.homes.size,8); assert.equal(world.actors.has(resident(8).id),false);
  assert.equal(get('mapSurface').children.filter(node=>node.classList.contains('world-terrain')).length,1,
    'Registry changes accumulated old terrain layers');
} else if(scenario === 'removal-cleanup') {
  const initial = residents(16); world.configure(initial); world.focusResident(resident(0).id);
  const item = world.actors.get(resident(0).id);
  world.walk(item.agent.id,[item.home[0]+20,item.home[1]+20]);
  assert.equal(world.timers.has(item.agent.id),true);
  const pending = [...world.timers.get(item.agent.id)], home = world.homes.get(item.agent.id);
  world.configure(initial.slice(1),[resident(0)]);
  assert.equal(world.timers.has(item.agent.id),false); assert.equal(world.actors.has(item.agent.id),false);
  assert.equal(world.homes.has(item.agent.id),false); assert.equal(item.actor.parentElement,null);
  assert.equal(home.parentElement,null);
  for(const id of pending)assert.equal(timeouts.has(id),false, 'Removed actor still owns an animation callback');
} else if(scenario === 'archived-neighborhood') {
  world.configure([resident(0)],[resident(63)]);
  assert.deepEqual(plain(world.town.districts.map(item=>item.id)),[0,1,2,3,4,5,6,7]);
  const bounds = plain(world.town.bounds), marker = world.markers.get(7);
  world.configure([]);
  assert.deepEqual(plain(world.town.bounds),bounds); assert.equal(world.markers.get(7),marker);
  assert.equal(world.town.districts.find(item=>item.id === 7).count,0);
  assert.equal(get('neighborhoodSelect').children.length,9);
  assert.equal(marker.getAttribute('aria-label').includes('0 residents'),true);
} else if(scenario === 'sparse-initial') {
  world.configure([resident(63)]);
  assert.deepEqual(plain(world.town.districts.map(item=>item.id)),[0,1,2,3,4,5,6,7]);
  assert.equal(world.markers.size,8); assert.equal(get('neighborhoodSelect').children.length,9);
  const entry = world.entries[0], home = world.homes.get(entry.agent.id), box = home.getBoundingClientRect();
  close(world.camera.x,entry.plot.x); close(world.camera.y,entry.plot.y-40);
  assert.ok(box.left >= 24 && box.right <= viewport.clientWidth-24);
  assert.ok(box.top >= 24 && box.bottom <= viewport.clientHeight-24);
} else if(scenario === 'animation-budget') {
  viewport.clientWidth = 10000; viewport.clientHeight = 10000; world.configure(residents(64));
  const initialDepths = new Map([...world.actors].map(([id,item])=>[id,Number(item.actor.style.zIndex)]));
  for(const entry of world.entries){
    const item = world.actors.get(entry.agent.id);
    world.walk(entry.agent.id,[item.home[0]+10,item.home[1]+10]);
    assert.ok(world.timers.size <= 8, 'More than eight actors are animating');
  }
  assert.equal(world.timers.size,8); assert.equal(timeouts.size,24);
  for(const [id,item] of world.actors){
    if(!world.timers.has(id)){
      assert.deepEqual(plain(item.position),[item.home[0]+10,item.home[1]+10]);
      assert.equal(item.actor.classList.contains('walking'),false);
    }
  }
  document.hidden = true; document.dispatch('visibilitychange');
  assert.equal(world.timers.size,0); assert.equal(timeouts.size,0);
  for(const [id,item] of world.actors){
    assert.equal(item.actor.classList.contains('walking'),false);
    assert.equal(Number(item.actor.style.zIndex),initialDepths.get(id)+10,
      'Stopping movement left the actor depth at its previous position');
  }
  window.dispatch('pagehide'); assert.equal(intervals.size,0); assert.equal(observer.disconnected,true);
} else if(scenario === 'bfcache') {
  world.configure(residents(64)); world.update(new Set(),null,true);
  world.camera.moveTo(400,200,.85); world.paintCamera();
  const original = cameraPlace(), originalInterval = world.ambient, originalObservations = observer.observations;
  const item = world.actors.get(resident(0).id), oldDepth = Number(item.actor.style.zIndex);
  world.walk(item.agent.id,[item.home[0]+60,item.home[1]+120]);
  assert.equal(world.timers.has(item.agent.id),true);
  window.dispatch('pagehide');
  assert.equal(intervals.size,0); assert.equal(timeouts.size,0); assert.equal(observer.disconnected,true);
  assert.equal(Number(item.actor.style.zIndex),oldDepth+120);
  viewport.clientWidth = 600; viewport.clientHeight = 420;
  window.dispatch('pageshow',{persisted:true});
  assert.equal(observer.disconnected,false); assert.equal(observer.target,viewport);
  assert.equal(observer.observations,originalObservations+1);
  assert.equal(intervals.size,1); assert.notEqual(world.ambient,originalInterval);
  assert.deepEqual(cameraPlace(),original);
  assert.equal(world.camera.viewportWidth,600); assert.equal(world.camera.viewportHeight,420);
  close(viewport.scrollLeft,world.camera.frame().scrollLeft);
  close(viewport.scrollTop,world.camera.frame().scrollTop);
  const restoredInterval = world.ambient, restoredObservations = observer.observations;
  window.dispatch('pageshow',{persisted:false});
  assert.equal(world.ambient,restoredInterval); assert.equal(observer.observations,restoredObservations);
  window.dispatch('pageshow',{persisted:true});
  assert.equal(intervals.size,1, 'Restoring a page created duplicate ambient intervals');
  assert.equal(intervals.has(restoredInterval),false);
  intervals.get(world.ambient).callback();
  assert.ok(world.timers.size > 0, 'Ambient wandering did not resume after restoring the page');
  window.dispatch('pagehide');
  assert.equal(intervals.size,0); assert.equal(timeouts.size,0); assert.equal(world.timers.size,0);
} else if(scenario === 'refresh-scroll') {
  const initial = residents(64); world.configure(initial);
  const frame = world.camera.frame(), left = (frame.width-viewport.clientWidth)*.6,
    top = (frame.height-viewport.clientHeight)*.4;
  viewport.scrollLeft = left; viewport.scrollTop = top; viewport.dispatch('scroll');
  close(world.camera.frame().scrollLeft,left); close(world.camera.frame().scrollTop,top);
  const camera = cameraPlace(), original = residentNodes(), builds = terrainBuilds;
  world.configure(initial.map(agent=>({...agent,name:agent.name+' renamed'})));
  assert.deepEqual(cameraPlace(),camera); checkRetained(original); assert.equal(terrainBuilds,builds);
  assert.equal(world.homes.get(resident(63).id).querySelector('.home-name').textContent,'Resident 63 renamed');
} else if(scenario === 'district-desktop' || scenario === 'district-phone') {
  const compact = scenario === 'district-phone';
  if(compact){viewport.clientWidth = 390; viewport.clientHeight = 420;}
  world.configure(residents(64));
  const select = get('neighborhoodSelect');
  for(const district of world.town.districts){
    get('fitTownButton').dispatch('click'); assert.ok(world.camera.zoom < .48);
    select.value = String(district.id); select.dispatch('change');
    assert.ok(world.camera.zoom >= .48 && world.camera.zoom <= .8);
    const entries = world.entries.filter(entry=>entry.district === district.id);
    for(const entry of entries){
      const home = world.homes.get(entry.agent.id);
      if(compact){home.focus(); viewport.dispatch('focusin',{target:home});}
      const box = home.getBoundingClientRect();
      assert.ok(box.left >= 0 && box.right <= viewport.clientWidth,
        `Home ${entry.slot} is horizontally unreachable in district ${district.id}`);
      assert.ok(box.top >= 0 && box.bottom <= viewport.clientHeight,
        `Home ${entry.slot} is vertically unreachable in district ${district.id}`);
    }
    get('fitTownButton').dispatch('click');
    const marker = world.markers.get(district.id);
    assert.equal(marker.type,'button');
    assert.ok(marker.getAttribute('aria-label').includes(district.name));
    marker.dispatch('click');
    assert.ok(world.camera.zoom >= .48 && world.camera.zoom <= .8);
    assert.ok(entries.some(entry=>{
      const box = world.homes.get(entry.agent.id).getBoundingClientRect();
      return box.left < viewport.clientWidth && box.right > 0 && box.top < viewport.clientHeight && box.bottom > 0;
    }), 'Overview marker opened a view with no reachable homes');
  }
} else if(scenario === 'keyboard') {
  world.configure(residents(64)); const original = cameraPlace();
  for(const modifier of ['ctrlKey','metaKey','altKey']){
    for(const key of ['+','-','ArrowRight','Home','End']){
      const event = viewport.dispatch('keydown',{key,[modifier]:true});
      assert.equal(event.defaultPrevented,false); assert.deepEqual(cameraPlace(),original);
    }
  }
  const nested = viewport.dispatch('keydown',{target:world.homes.get(resident(0).id),key:'+'});
  assert.equal(nested.defaultPrevented,false); assert.deepEqual(cameraPlace(),original);
  assert.equal(viewport.dispatch('keydown',{key:'+'}).defaultPrevented,true);
  close(world.camera.zoom,original[2]*1.25);
  const x = world.camera.x;
  assert.equal(viewport.dispatch('keydown',{key:'ArrowRight'}).defaultPrevented,true);
  close(world.camera.x,x+120/world.camera.zoom);
} else if(scenario === 'pointer') {
  world.configure(residents(64)); world.camera.moveTo(0,0,.8); world.paintCamera();
  const original = cameraPlace(), sprite = world.actors.get(resident(0).id).actor.firstElementChild;
  const options = {pointerType:'mouse',button:0,pointerId:7,clientX:20,clientY:20};
  for(const target of [sprite,get('neighborhoodSelect'),world.homes.get(resident(0).id)]){
    assert.equal(viewport.dispatch('pointerdown',{...options,target}).defaultPrevented,false);
    assert.equal(Boolean(world.drag),false);
  }
  assert.equal(viewport.dispatch('pointerdown',{...options,pointerType:'touch'}).defaultPrevented,false);
  assert.equal(viewport.dispatch('pointerdown',{...options,button:2}).defaultPrevented,false);
  assert.equal(viewport.dispatch('pointerdown',options).defaultPrevented,true);
  assert.equal(viewport.capturedPointer,7);
  viewport.dispatch('pointermove',{pointerId:8,clientX:60,clientY:0}); assert.deepEqual(cameraPlace(),original);
  viewport.dispatch('pointermove',{pointerId:7,clientX:60,clientY:0});
  close(world.camera.x,-50); close(world.camera.y,25);
  viewport.dispatch('pointerup'); assert.equal(Boolean(world.drag),false);
  assert.equal(viewport.classList.contains('dragging'),false);
} else if(scenario === 'focus') {
  world.configure(residents(64)); world.camera.moveTo(0,100,.72); world.paintCamera();
  const home = world.homes.get(resident(63).id), entry = world.entries.find(item=>item.agent.id === resident(63).id);
  assert.ok(home.getBoundingClientRect().left < 0);
  home.focus(); viewport.dispatch('focusin',{target:home});
  close(world.camera.x,entry.plot.x); close(world.camera.y,entry.plot.y-25);
  const box = home.getBoundingClientRect();
  assert.ok(box.left >= 24 && box.right <= viewport.clientWidth-24);
  assert.ok(box.top >= 24 && box.bottom <= viewport.clientHeight-24);
} else if(scenario === 'focus-moved-actor') {
  world.configure(residents(64)); world.paused = true;
  const id = resident(63).id;
  world.update(new Set([id]),null,true);
  const entry = world.entries.find(item=>item.agent.id === id);
  world.camera.moveTo(entry.plot.x,entry.plot.y-25,.72); world.paintCamera();
  const item = world.actors.get(id), point = [...item.position];
  assert.notDeepEqual(point,plain(item.home), 'The test actor did not move away from home');
  assert.ok(item.actor.getBoundingClientRect().right > viewport.clientWidth);
  item.actor.focus(); viewport.dispatch('focusin',{target:item.actor.firstElementChild});
  close(world.camera.x,point[0]); close(world.camera.y,point[1]-25);
  const box = item.actor.getBoundingClientRect();
  assert.ok(box.left >= 24 && box.right <= viewport.clientWidth-24);
  assert.ok(box.top >= 24 && box.bottom <= viewport.clientHeight-24);
} else if(scenario === 'selected-destination') {
  world.configure(residents(64));
  const id = resident(63).id, entry = world.entries.find(item=>item.agent.id === id);
  world.camera.moveTo(entry.plot.x,entry.plot.y-25,.72); world.paintCamera();
  world.update(new Set([id]),null,true);
  const item = world.actors.get(id), destination = item.target.split(',').map(Number);
  assert.notDeepEqual(destination,plain(item.home), 'Selected resident has no commons destination');
  assert.deepEqual(plain(item.position),plain(item.home), 'The actor did not remain in transit for this test');
  world.focusResident(id);
  close(world.camera.x,destination[0]); close(world.camera.y,destination[1]-25);
  world.update(new Set(),null,true); world.focusResident(id);
  close(world.camera.x,entry.plot.x); close(world.camera.y,entry.plot.y-25);
} else {
  throw Error('Unknown runtime scenario: '+scenario);
}
process.stdout.write('ok');
"""


@unittest.skipUnless(NODE, "Node.js is required for the town runtime regression")
class WorldRuntimeTests(unittest.TestCase):
    def run_scenario(self, scenario):
        process = subprocess.run(
            [NODE, "--input-type=module", "--eval", RUNTIME_SCENARIOS,
             str(WORLD_MODULE), WORLD_MODULE.with_name("world-layout.js").as_uri(),
             WORLD_MODULE.with_name("world-camera.js").as_uri(), scenario],
            capture_output=True, encoding="utf-8", timeout=10, check=False, shell=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual("ok", process.stdout)

    def test_every_registered_resident_has_an_interactive_home_and_actor(self):
        self.run_scenario("capacity")

    def test_growth_and_removal_preserve_other_homes_actors_and_camera(self):
        self.run_scenario("growth")

    def test_removed_actors_leave_no_dom_or_animation_callbacks(self):
        self.run_scenario("removal-cleanup")

    def test_archived_residents_keep_their_empty_neighborhood_on_reload(self):
        self.run_scenario("archived-neighborhood")

    def test_sparse_initial_population_keeps_connecting_districts_and_a_visible_home(self):
        self.run_scenario("sparse-initial")

    def test_motion_has_eight_actor_limit_and_cleans_up_when_hidden(self):
        self.run_scenario("animation-budget")

    def test_bfcache_restore_resumes_one_motion_interval_and_observes_the_new_viewport(self):
        self.run_scenario("bfcache")

    def test_native_scroll_and_registry_refresh_keep_the_current_view(self):
        self.run_scenario("refresh-scroll")

    def test_desktop_neighborhood_controls_and_overview_markers_reach_all_homes(self):
        self.run_scenario("district-desktop")

    def test_phone_neighborhood_controls_and_keyboard_focus_reach_all_homes(self):
        self.run_scenario("district-phone")

    def test_map_keyboard_controls_preserve_browser_modifier_shortcuts(self):
        self.run_scenario("keyboard")

    def test_pointer_pan_ignores_controls_and_follows_background_drag(self):
        self.run_scenario("pointer")

    def test_keyboard_focus_brings_an_offscreen_residents_home_into_view(self):
        self.run_scenario("focus")

    def test_actor_focus_follows_its_actual_position_away_from_home(self):
        self.run_scenario("focus-moved-actor")

    def test_selecting_an_outer_resident_focuses_the_commons_destination_then_returns_home(self):
        self.run_scenario("selected-destination")


if __name__ == "__main__":
    unittest.main()
