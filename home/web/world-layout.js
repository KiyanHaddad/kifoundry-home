/** Saved slots locate homes. Visual placement has no dependency on model execution. */
export const HOMES_PER_DISTRICT = 5;
const plots = [
  {x:24,y:31,feet:[29,35]}, {x:74,y:36,feet:[65,40]},
  {x:15,y:50,feet:[23,53]}, {x:85,y:54,feet:[76,56]},
  {x:46,y:32,feet:[49,36]},
];
function appearance(id) { let hash=2166136261; for(const char of id) {hash^=char.charCodeAt(0);hash=Math.imul(hash,16777619);}return (hash>>>0)%5; }
export function layoutResidents(agents) {
  const ordered=[...agents].sort((a,b)=>a.id.localeCompare(b.id));
  const reserved=new Set(ordered.filter(a=>Number.isInteger(a.home_slot)&&a.home_slot>=0&&a.home_slot<64).map(a=>a.home_slot));
  return ordered.map(agent=>{
    let slot=agent.home_slot;
    if(!Number.isInteger(slot)||slot<0||slot>=64) {slot=0;while(reserved.has(slot))slot++;reserved.add(slot);}
    const plot=plots[slot%HOMES_PER_DISTRICT];
    return {agent,slot,district:Math.floor(slot/HOMES_PER_DISTRICT),plot,appearance:appearance(agent.id)};
  });
}
