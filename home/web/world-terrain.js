/** Reusable scenery in world coordinates; resident identities stay in the UI. */
const NS = 'http://www.w3.org/2000/svg';
const PREFIX = 'home-terrain-';

function shape(tag, attributes = {}, parent = null) {
  const item = document.createElementNS(NS, tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, String(value));
  if (parent) parent.append(item);
  return item;
}

function group(parent, x = 0, y = 0) {
  return shape('g', { transform: `translate(${x} ${y})` }, parent);
}

function use(parent, name, x, y, scale = 1) {
  return shape('use', {
    href: `#${PREFIX}${name}`, transform: `translate(${x} ${y}) scale(${scale})`,
  }, parent);
}

function random(seed) {
  let value = (seed + 1) * 2654435761;
  return () => {
    value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
    return value / 4294967296;
  };
}

function gradient(defs, name, stops, radial = false) {
  const result = shape(radial ? 'radialGradient' : 'linearGradient', {
    id: PREFIX + name, ...(radial ? {} : { x1: '0%', y1: '0%', x2: '0%', y2: '100%' }),
  }, defs);
  for (const [offset, color, opacity = 1] of stops) {
    shape('stop', { offset, 'stop-color': color, 'stop-opacity': opacity }, result);
  }
  return result;
}

function definitions(svg) {
  const defs = shape('defs', {}, svg);
  gradient(defs, 'clearing', [['0%', '#537344'], ['62%', '#425f3b'], ['100%', '#2c4934']], true);

  const grass = shape('pattern', { id: PREFIX + 'grass', width: 96, height: 88, patternUnits: 'userSpaceOnUse' }, defs);
  for (const [x, y, radius] of [[8, 18, 1.1], [35, 8, .8], [76, 31, 1.5], [50, 60, 1], [17, 73, 1.4], [87, 82, .7]]) {
    shape('circle', { cx: x, cy: y, r: radius, fill: '#c4cf9b', opacity: .16 }, grass);
  }
  shape('path', { d: 'M22 39l-2-5m2 5 3-4M68 73l-2-6m2 6 3-4M87 13l-1-4', fill: 'none', stroke: '#aec08b', 'stroke-width': 1.1, opacity: .19 }, grass);
  const stone = shape('pattern', { id: PREFIX + 'stone', width: 37, height: 24, patternUnits: 'userSpaceOnUse' }, defs);
  shape('path', { d: 'M1 1h17v10H1zM20 1h16v10H20zM-7 13h17v10H-7zM12 13h17v10H12zM31 13h17v10H31z', fill: 'none', stroke: '#ded4b9', 'stroke-width': 1, opacity: .24 }, stone);

  // Display viewports use measured alpha bounds; atlas pixels stay unchanged.
  // [column, row, left, top, right, bottom, visible world width]
  const frames = {
    pine: [0,0,111,155,274,401,100],
    tree: [1,0,108,163,301,400,130],
    shrub: [2,0,95,242,291,388,64],
    lantern: [3,0,139,177,260,401,36],
    council: [0,1,76,214,325,412,210],
    studio: [1,1,110,171,322,407,150],
    pond: [2,1,64,195,322,411,155],
    garden: [3,1,83,197,298,403,115],
  };
  for (const [name, [column,row,left,top,right,bottom,width]] of Object.entries(frames)) {
    const height = width * (bottom-top) / (right-left);
    const prop = shape('g', {id: PREFIX+name}, defs);
    const viewport = shape('svg', {
      x: -width/2, y: -height, width, height,
      viewBox: `${column*362+left} ${row*543+top} ${right-left} ${bottom-top}`,
      overflow: 'hidden',
    }, prop);
    shape('image', {href:'town-props.webp', x:0, y:0, width:1448, height:1086}, viewport);
  }
}

function path(parent, d, width = 30) {
  const common = { d, fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' };
  shape('path', { ...common, stroke: '#1a3525', 'stroke-width': width + 12, opacity: .28 }, parent);
  shape('path', { ...common, stroke: '#758065', 'stroke-width': width + 4 }, parent);
  shape('path', { ...common, stroke: '#aca78b', 'stroke-width': width }, parent);
  shape('path', { ...common, stroke: `url(#${PREFIX}stone)`, 'stroke-width': width }, parent);
}

function clearing(parent, district) {
  const g = group(parent, district.x, district.y);
  const d = 'M-470-415C-290-473-80-452 98-455S463-440 489-306 486-84 503 88 494 377 359 430 91 450-97 450-440 440-484 293-492 42-503-113-522-336-470-415Z';
  shape('path', { d, fill: `url(#${PREFIX}clearing)`, stroke: '#233f2e', 'stroke-width': 19 }, g);
  shape('path', { d, fill: `url(#${PREFIX}grass)` }, g);
  shape('ellipse', { cx: -210, cy: -15, rx: 164, ry: 113, fill: '#658050', opacity: .14 }, g);
  shape('ellipse', { cx: 273, cy: 245, rx: 165, ry: 106, fill: '#96a064', opacity: .1 }, g);
}

function neighborhoodPaths(parent, district) {
  const [hx, hy] = district.hub;
  for (const plot of district.plots) {
    const [px, py] = plot.feet;
    const bend = px < hx ? -25 : 25;
    path(parent, `M${px} ${py}C${px + bend} ${py + 35} ${hx + (px - hx) * .34} ${hy + (py - hy) * .56} ${hx} ${hy}`, 25);
  }
  shape('ellipse', { cx: hx, cy: hy, rx: 115, ry: 70, fill: '#9c9e7d', stroke: '#707e59', 'stroke-width': 4 }, parent);
  shape('ellipse', { cx: hx, cy: hy, rx: 111, ry: 66, fill: `url(#${PREFIX}stone)` }, parent);
}

function streets(parent, districts) {
  for (let first = 0; first < districts.length; first++) {
    for (let second = first + 1; second < districts.length; second++) {
      const a = districts[first], b = districts[second];
      const dx = b.x - a.x, dy = b.y - a.y;
      if (dy === 0 && Math.abs(dx) === 1150) {
        const left = dx > 0 ? a : b, right = dx > 0 ? b : a;
        path(parent, `M${left.x} ${left.y + 100}C${left.x + 180} ${left.y + 220} ${left.x + 360} ${left.y + 220} ${left.x + 520} ${left.y + 220}L${right.x - 520} ${right.y + 220}C${right.x - 360} ${right.y + 220} ${right.x - 180} ${right.y + 220} ${right.x} ${right.y + 100}`, 40);
      } else if (dx === 0 && Math.abs(dy) === 1080) {
        const top = dy > 0 ? a : b, bottom = dy > 0 ? b : a;
        path(parent, `M${top.x} ${top.y + 100}C${top.x - 150} ${top.y + 230} ${top.x - 150} ${top.y + 360} ${top.x - 150} ${top.y + 480}L${bottom.x - 150} ${bottom.y - 480}C${bottom.x - 150} ${bottom.y - 300} ${bottom.x - 130} ${bottom.y - 20} ${bottom.x} ${bottom.y + 100}`, 40);
      }
    }
  }
}

function plotGarden(parent, plot, occupied) {
  const g = group(parent, plot.x, plot.y);
  shape('ellipse', { cx: 0, cy: -3, rx: 82, ry: 27, fill: '#243e2b', opacity: occupied ? .48 : .2 }, g);
  shape('ellipse', { cx: 0, cy: -6, rx: 76, ry: 24, fill: occupied ? '#6e7950' : '#66824c', opacity: .65 }, g);
  if (occupied) return;
  use(g, 'garden', 0, 0);
}

function pond(parent, x, y) { use(parent,'pond',x,y+25); }

function decorations(parent, district) {
  const g = group(parent, district.x, district.y);
  const rng = random(district.id);
  const localPlots = district.plots.map(plot => ({ x: plot.x - district.x, y: plot.y - district.y }));
  const hasPond = district.id % 3 === 0;
  if (hasPond) pond(g, -435, 403);
  for (let index = 0; index < 100; index++) {
    const x = Math.round((rng() - .5) * 1060), y = Math.round((rng() - .5) * 930);
    if (Math.abs(x) < 407 && Math.abs(y) < 365) continue;
    if (Math.abs(y - 220) < 65 || Math.abs(x + 150) < 60) continue;
    if (hasPond && Math.abs(x + 435) < 95 && y > 325) continue;
    if (localPlots.some(plot => Math.abs(x - plot.x) < 142 && y > plot.y - 245 && y - 150 < plot.y + 65)) continue;
    use(g, rng() > .35 ? 'pine' : 'tree', x, y, .63 + rng() * .44);
  }
  for (const [x, y] of [[-107, 24], [117, 32], [-228, 220], [233, 398], [-430, 226], [432, 222]]) {
    use(g, 'lantern', x, y, .85);
  }
  for (const [x, y] of [[-450, -294], [453, -292], [-88, 439], [93, 441], [-492, 11], [489, 16]]) {
    use(g, 'shrub', x, y, .8 + rng() * .5);
    for (let flower = 0; flower < 5; flower++) {
      shape('circle', { cx: x + Math.round(rng() * 45 - 22), cy: y + Math.round(rng() * 14 - 5), r: 1.7, fill: flower % 2 ? '#c6b57e' : '#a6a98e', opacity: .8 }, g);
    }
  }
  if (district.id !== 0) {
    const bench = group(g, 0, 100);
    shape('ellipse', { cx: 1, cy: 4, rx: 41, ry: 14, fill: '#273d2a', opacity: .4 }, bench);
    shape('path', { d: 'M-36-5 0-18 37-5 0 9Z', fill: '#ad8a56', stroke: '#5d593c', 'stroke-width': 3 }, bench);
    shape('path', { d: 'M-29-2v15M29-2v15M0 8v12', stroke: '#65543a', 'stroke-width': 4 }, bench);
    shape('path', { d: 'M-23-6 12 5m-13-17 25 8', stroke: '#dbb980', 'stroke-width': 1.5, opacity: .55 }, bench);
  }
}

function councilTable(parent, center) {
  const g = group(parent, center.x, center.y);
  shape('ellipse', {cx:0,cy:3,rx:146,ry:86,fill:'#778267',stroke:'#a3a487','stroke-width':3},g);
  shape('ellipse', {cx:0,cy:3,rx:135,ry:77,fill:'#aaa58a',stroke:'#69785b','stroke-width':2},g);
  shape('ellipse', {cx:0,cy:3,rx:133,ry:75,fill:`url(#${PREFIX}stone)`},g);
  use(g,'council',0,63);
  use(g,'lantern',-133,27,.9);
  use(g,'lantern',133,27,.9);
}

function studio(parent, center) {
  use(parent,'studio',center.x,center.y);
}

/** Build one inert scenery layer; houses, people and controls are separate. */
export function createTerrain(town) {
  const { minX, minY, width, height } = town.bounds;
  const svg = shape('svg', {
    xmlns: NS, class: 'world-terrain', viewBox: `${minX} ${minY} ${width} ${height}`,
    width, height, 'aria-hidden': 'true', focusable: 'false',
  });
  definitions(svg);
  shape('rect', { x: minX, y: minY, width, height, fill: '#203d30' }, svg);
  shape('rect', { x: minX, y: minY, width, height, fill: `url(#${PREFIX}grass)` }, svg);
  for (const district of town.districts) clearing(svg, district);
  streets(svg, town.districts);
  for (const district of town.districts) neighborhoodPaths(svg, district);
  const occupied = new Set(town.entries.map(entry => entry.slot));
  for (const district of town.districts) {
    for (const plot of district.plots) plotGarden(svg, plot, occupied.has(plot.slot));
    decorations(svg, district);
  }
  councilTable(svg, town.commons);
  studio(svg, town.studio);
  return svg;
}
