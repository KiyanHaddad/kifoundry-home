/** Saved slots locate homes. Visual placement has no dependency on model execution. */
export const HOMES_PER_DISTRICT = 8;
const MAX_RESIDENTS = 64;
const DISTRICT_WIDTH = 1150;
const DISTRICT_HEIGHT = 1080;
const WORLD_PADDING = 40;
const localPlots = [
  [-320, -180], [0, -250], [320, -180], [-380, 100],
  [380, 100], [-290, 340], [0, 380], [290, 340],
];
const firstNames = [
  'Commons Quarter', 'North Grove', 'Northeast Grove', 'East Grove',
  'Southeast Grove', 'South Grove', 'Southwest Grove', 'West Grove', 'Northwest Grove',
];

function appearance(id) {
  let hash = 2166136261;
  for (const char of id) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619); }
  return (hash >>> 0) % 5;
}

/** Square spiral: center, north, northeast, east, southeast, south, southwest, west. */
function districtCell(index) {
  if (!Number.isSafeInteger(index) || index < 0) throw new RangeError('Invalid neighborhood index.');
  if (index === 0) return [0, 0];
  const ring = Math.ceil((Math.sqrt(index + 1) - 1) / 2);
  const offset = index - (2 * ring - 1) ** 2;
  if (offset < 2 * ring) return [1 - ring + offset, -ring];
  if (offset < 4 * ring) return [ring, 1 - ring + offset - 2 * ring];
  if (offset < 6 * ring) return [ring - 1 - (offset - 4 * ring), ring];
  return [-ring, ring - 1 - (offset - 6 * ring)];
}

export function districtGeometry(index) {
  const [column, row] = districtCell(index);
  const x = column * DISTRICT_WIDTH, y = row * DISTRICT_HEIGHT;
  const vertical = row < 0 ? 'North' : row > 0 ? 'South' : '';
  const horizontal = column < 0 ? 'west' : column > 0 ? 'east' : '';
  const direction = vertical + (vertical ? horizontal : horizontal.replace(/^./, char => char.toUpperCase()));
  const name = firstNames[index] || `${direction || 'Outer'} Grove ${index + 1}`;
  return {
    id: index, name, x, y, hub: [x, y + 100],
    plots: localPlots.map(([localX, localY], position) => ({
      slot: index * HOMES_PER_DISTRICT + position,
      x: x + localX, y: y + localY, feet: [x + localX, y + localY + 38],
    })),
    bounds: {minX: x - 520, minY: y - 480, maxX: x + 520, maxY: y + 480},
  };
}

export function layoutResidents(agents) {
  if (agents.length > MAX_RESIDENTS) throw new RangeError('The town supports at most 64 active residents.');
  const ordered = [...agents].sort((a, b) => a.id.localeCompare(b.id));
  const validSlot = slot => Number.isInteger(slot) && slot >= 0 && slot < MAX_RESIDENTS;
  const reserved = new Set(ordered.filter(agent => validSlot(agent.home_slot)).map(agent => agent.home_slot));
  return ordered.map(agent => {
    let slot = agent.home_slot;
    if (!validSlot(slot)) {
      slot = 0;
      while (reserved.has(slot)) slot++;
      reserved.add(slot);
    }
    const district = Math.floor(slot / HOMES_PER_DISTRICT);
    const {x, y, feet} = districtGeometry(district).plots[slot % HOMES_PER_DISTRICT];
    return {agent, slot, district, plot: {x, y, feet}, appearance: appearance(agent.id)};
  });
}

export function layoutTown(agents, extraDistricts = []) {
  const entries = layoutResidents(agents);
  const ids = [...new Set([0, ...extraDistricts, ...entries.map(entry => entry.district)])].sort((a, b) => a - b);
  const districts = ids.map(id => ({
    ...districtGeometry(id), count: entries.filter(entry => entry.district === id).length,
  }));
  const minX = Math.min(...districts.map(district => district.bounds.minX)) - WORLD_PADDING;
  const minY = Math.min(...districts.map(district => district.bounds.minY)) - WORLD_PADDING;
  const maxX = Math.max(...districts.map(district => district.bounds.maxX)) + WORLD_PADDING;
  const maxY = Math.max(...districts.map(district => district.bounds.maxY)) + WORLD_PADDING;
  return {
    entries, districts, bounds: {minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY},
    commons: {x: 0, y: 100}, studio: {x: 210, y: -20},
  };
}
