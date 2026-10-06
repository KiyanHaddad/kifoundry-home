import { layoutResidents } from './world-layout.js';
/** World presentation consumes registry entries, selection and saved execution states. */
const seats=[[34,47],[62,47],[37,59],[61,59],[49,51]];
const phases={proposal:'First thoughts',critique:'Challenge',synthesis:'Synthesis',reply:'Reply'};
const statuses={queued:'Waiting',running:'Thinking',failed:'Could not reply',cancelled:'Stopped',interrupted:'Interrupted',completed:'Finished'};
function el(tag,text='',className=''){const node=document.createElement(tag);node.textContent=text;node.className=className;return node;}
function shortName(name){return name.replace(/\s*\(fixture\)\s*$/,'');}
export class TownWorld {
  constructor(onChoose){
    this.onChoose=onChoose;this.entries=[];this.actors=new Map();this.homes=new Map();this.pictures=new Map();this.timers=new Map();
    this.selected=new Set();this.connected=true;this.active=false;this.round=null;this.district=0;this.districtButtons=new Map();
    this.reduced=matchMedia('(prefers-reduced-motion: reduce)');
    try{this.paused=localStorage.getItem('kifoundry-home:pause-wandering')==='true';}catch{this.paused=false;}
    document.getElementById('motionButton').addEventListener('click',()=>{
      this.paused=!this.paused;
      try{localStorage.setItem('kifoundry-home:pause-wandering',String(this.paused));}catch{/* Optional preference. */}
      this.applyMotionPreference();
    });
    this.reduced.addEventListener('change',()=>this.applyMotionPreference());
    document.addEventListener('visibilitychange',()=>{if(document.hidden)this.stopWalks();});
    this.ambient=setInterval(()=>this.wander(),7000);
    window.addEventListener('pagehide',()=>{clearInterval(this.ambient);this.stopWalks();});
    this.applyMotionPreference();
  }
  configure(agents){
    this.entries=layoutResidents(agents);
    const districts=this.districts();
    if(districts.length&&!districts.includes(this.district))this.district=districts[0];
    this.render();
  }
  districts(){return [...new Set(this.entries.map(entry=>entry.district))].sort((a,b)=>a-b);}
  focusResident(id){
    const entry=this.entries.find(entry=>entry.agent.id===id);
    if(entry){this.district=entry.district;this.render();}
  }
  showDistrict(district){this.district=district;this.render();}
  visibleEntries(){
    const local=this.entries.filter(entry=>entry.district===this.district);
    const localGuests=local.filter(entry=>this.selected.has(entry.agent.id)).length;
    const visitors=this.entries.filter(entry=>entry.district!==this.district&&this.selected.has(entry.agent.id)).slice(0,Math.max(0,seats.length-localGuests));
    return [...local,...visitors];
  }
  render(){
    const houses=document.getElementById('houses'),residents=document.getElementById('residents');
    const local=this.entries.filter(entry=>entry.district===this.district);
    const localIds=new Set(local.map(entry=>entry.agent.id));
    for(const [id,home]of this.homes)if(!localIds.has(id)){home.remove();this.homes.delete(id);this.pictures.get(id)?.remove();this.pictures.delete(id);}
    for(const entry of local){
      const {agent,plot}=entry;let home=this.homes.get(agent.id);
      if(!home){
        home=el('button','','resident-home');home.type='button';home.dataset.agentId=agent.id;
        const picture=el('span','','house-picture');picture.setAttribute('aria-hidden','true');
        this.pictures.set(agent.id,picture);houses.append(picture);
        const label=el('span','','house-label');label.append(el('span','','home-name'),el('small','','home-status'));
        home.append(label);home.addEventListener('click',()=>this.onChoose(agent.id));this.homes.set(agent.id,home);houses.append(home);
      }
      home.style.left=plot.x+'%';home.style.top=plot.y+'%';
      const picture=this.pictures.get(agent.id);picture.style.left=plot.x+'%';picture.style.top=plot.y+'%';picture.style.backgroundPosition=((entry.slot%5)*25)+'% 0';
      home.querySelector('.home-name').textContent=shortName(agent.name);
      home.title=agent.name+(agent.role?' · '+agent.role:'');
    }
    const visible=this.visibleEntries();
    const visibleIds=new Set(visible.map(entry=>entry.agent.id));
    for(const [id,item]of this.actors)if(!visibleIds.has(id)){this.clearTimers(id);item.actor.remove();this.actors.delete(id);}
    for(const entry of visible){
      const {agent,appearance,plot}=entry;let item=this.actors.get(agent.id);
      const home=entry.district===this.district?plot.feet:[49,87];
      if(!item){
        const actor=el('button','','resident-actor');actor.type='button';actor.dataset.agentId=agent.id;
        const sprite=el('span','','actor-sprite');sprite.setAttribute('aria-hidden','true');sprite.style.backgroundPosition=(appearance*25)+'% 0';
        actor.append(sprite,el('span','','actor-label'));actor.addEventListener('click',()=>this.onChoose(agent.id));
        actor.style.left=home[0]+'%';actor.style.top=home[1]+'%';residents.append(actor);
        item={actor,agent,home,position:home,target:home.join(',')};this.actors.set(agent.id,item);
      }
      item.agent=agent;item.home=home;
    }
    const nav=document.getElementById('districts');const districts=this.districts();
    for(const [district,button]of this.districtButtons)if(!districts.includes(district)){button.remove();this.districtButtons.delete(district);}
    for(const district of districts){
      let button=this.districtButtons.get(district);
      if(!button){button=el('button','Neighborhood '+(district+1),'district-button');button.type='button';button.addEventListener('click',()=>this.showDistrict(district));this.districtButtons.set(district,button);nav.append(button);}
      button.setAttribute('aria-pressed',String(district===this.district));
    }
    districts.forEach((district,index)=>{const button=this.districtButtons.get(district);if(nav.children[index]!==button)nav.insertBefore(button,nav.children[index]||null);});
    nav.classList.toggle('hidden',districts.length<2);
    document.getElementById('residentCount').textContent=this.entries.length+' residents';
    this.update(this.selected,this.round,this.connected);
  }
  update(selected,round,connected=true){
    this.selected=new Set(selected);this.round=round;this.connected=connected;
    this.active=Boolean(round&&(['queued','running'].includes(round.status)||(round.turns||[]).some(turn=>['queued','running'].includes(turn.status))));
    const needed=this.visibleEntries();
    if(needed.some(entry=>!this.actors.has(entry.agent.id))||[...this.actors.keys()].some(id=>!needed.some(entry=>entry.agent.id===id))){this.render();return;}
    const selectedIds=[...this.actors.keys()].filter(id=>selected.has(id));
    for(const entry of this.entries){
      const id=entry.agent.id,chosen=selected.has(id);
      const turns=(round?.turns||[]).filter(turn=>turn.agent_id===id);
      const turn=turns.find(turn=>turn.status==='running')||turns.at(-1);
      const status=!connected?'unknown':entry.agent.available===false?'unavailable':this.active&&turn?turn.status:'idle';
      const text=status==='unknown'?'Status unknown':status==='unavailable'?'Needs connection':status==='idle'?(chosen?'At the table':'At home'):(statuses[status]||status);
      const house=this.homes.get(id);
      if(house){
        house.setAttribute('aria-pressed',String(chosen));house.dataset.working=String(status==='running');
        house.setAttribute('aria-label','Talk with '+entry.agent.name+'. '+text);
        house.querySelector('.home-status').textContent=text;
      }
      const item=this.actors.get(id);if(!item)continue;
      item.actor.setAttribute('aria-pressed',String(chosen));item.actor.dataset.status=status;
      item.actor.querySelector('.actor-label').textContent=shortName(entry.agent.name);
      item.actor.setAttribute('aria-label','Talk with '+entry.agent.name+'. '+text+(this.active&&turn?' · '+(phases[turn.phase]||turn.phase):''));
      const destination=chosen?seats[selectedIds.indexOf(id)]||seats[0]:item.home;
      if(item.target!==destination.join(','))this.walk(id,destination);
    }
    const names=this.entries.filter(entry=>selected.has(entry.agent.id)).map(entry=>shortName(entry.agent.name));
    const density=names.length>selectedIds.length?' · '+selectedIds.length+' shown here':'';
    const text=!connected?'Status unknown · reconnect to check.':this.active?'Replies in progress'+density+'.':names.length>1?'Council selected · '+names.length+' guests'+density+'.':names.length?'Talking with '+names[0]+'.':'Choose a home to talk.';
    document.getElementById('worldStatus').textContent=text;
  }
  walk(id,destination,ambient=false){
    const item=this.actors.get(id);if(!item)return;
    this.clearTimers(id);item.target=destination.join(',');
    const place=point=>{item.actor.style.left=point[0]+'%';item.actor.style.top=point[1]+'%';item.position=point;};
    if(this.paused||this.reduced.matches||document.hidden){place(destination);item.actor.classList.remove('walking');return;}
    item.actor.classList.add('walking');
    const middle=ambient?destination:[(item.position[0]+destination[0])/2,Math.max(38,(item.position[1]+destination[1])/2)];
    place(middle);
    this.timers.set(id,[setTimeout(()=>place(destination),1000),setTimeout(()=>{
      item.actor.classList.remove('walking');this.timers.delete(id);
      if(ambient&&!this.selected.has(id))this.walk(id,item.home);
    },2150)]);
  }
  wander(){
    if(this.paused||this.reduced.matches||this.active||!this.connected||document.hidden)return;
    const item=[...this.actors.values()].find(item=>!this.selected.has(item.agent.id)&&!this.timers.has(item.agent.id)&&document.activeElement!==item.actor&&!item.actor.matches(':hover')&&this.entries.find(entry=>entry.agent.id===item.agent.id)?.district===this.district);
    if(item)this.walk(item.agent.id,[item.home[0]+3,item.home[1]+3],true);
  }
  clearTimers(id){for(const timer of this.timers.get(id)||[])clearTimeout(timer);this.timers.delete(id);}
  stopWalks(){for(const [id,item]of this.actors){this.clearTimers(id);item.actor.classList.remove('walking');const point=item.target.split(',').map(Number);item.actor.style.left=point[0]+'%';item.actor.style.top=point[1]+'%';item.position=point;}}
  applyMotionPreference(){
    const button=document.getElementById('motionButton');button.textContent=this.reduced.matches?'Reduced motion':this.paused?'Resume motion':'Pause motion';
    button.disabled=this.reduced.matches;button.setAttribute('aria-pressed',String(this.paused||this.reduced.matches));
    document.getElementById('town').classList.toggle('motion-paused',this.paused||this.reduced.matches);
    if(this.paused||this.reduced.matches)this.stopWalks();
  }
}

