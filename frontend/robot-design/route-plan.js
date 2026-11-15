/* The route view's reading of a run snapshot: places named from the world's ids, and the route's
   legs grouped into trips (drive somewhere, work there). Pure: the page and the tests use it. */
import { SKILL } from './plan.js';

/** "table_c6_top" -> "table C6", "bottle_on_table_e2" -> "the bottle on table E2". */
export function anchorName(id) {
  const words = String(id).replace(/_(top|surface|point)$/, '').split('_')
    .map((w) => (/^[a-z]\d+$/.test(w) ? w.toUpperCase() : w));
  const s = words.join(' ');
  return words.includes('on') ? `the ${s}` : s;
}

/** A route stop's name: the dock, the way-out door, or a task's anchor. */
export function placeName(snap, stop) {
  if (stop === 'dock') return 'the dock';
  if (stop === 'way_out') {
    const door = snap.world.way_out?.doorway || '';
    return `the ${door.replace(/^d_/, '').replace(/_/g, ' ')} door`;
  }
  const task = snap.tasks.find((t) => t.id === stop);
  return task ? anchorName(task.anchor) : stop;
}

const taskOf = (snap, id) => snap.tasks.find((t) => t.id === id);

/** Trips in order: { kind: 'move'|'work', title, legs: [index], length_m, expanded, dropped, task? }. */
export function tripsFor(snap) {
  const legs = snap.route.legs;
  const trips = [];
  const add = (t) => { trips.push(t); return t; };
  let work = null;
  legs.forEach((leg, i) => {
    const search = leg.search || { expanded: 0, dropped: [] };
    if (leg.from === leg.to && work && work.task === leg.to) {          // a short move between working spots
      work.legs.push(i);
      work.length_m += leg.length_m;
      work.expanded += search.expanded;
      return;
    }
    const to = leg.to;
    const title = to === 'dock' ? 'Back to the dock'
      : leg.carrying ? `Carry it to ${placeName(snap, to)}`
        : `To ${placeName(snap, to)}`;
    add({ kind: 'move', title, from: leg.from, to, legs: [i], carrying: Boolean(leg.carrying),
      length_m: leg.length_m, expanded: search.expanded, dropped: search.dropped.length });
    const task = taskOf(snap, to);
    work = task ? add({ kind: 'work', task: to, title: `${(SKILL[task.skill] || task.skill).toLowerCase()} ${placeName(snap, to)}`,
      legs: [], length_m: 0, expanded: 0, dropped: 0 }) : null;
  });
  return trips.map((t) => (t.kind === 'work' ? { ...t, title: t.title.replace(/^./, (c) => c.toUpperCase()) } : t));
}

export function totals(snap) {
  const legs = snap.route.legs;
  return {
    length_m: legs.reduce((s, l) => s + l.length_m, 0),
    expanded: legs.reduce((s, l) => s + (l.search?.expanded || 0), 0),
    dropped: legs.reduce((s, l) => s + (l.search?.dropped.length || 0), 0),
  };
}

/** Door clearances in words. The robot's width is measured across it at the angle it crosses that door,
    so it differs from door to door. */
export function doorLines(snap) {
  return (snap.route.door_clearances || []).map((d) => ({
    door: `${d.doorway.replace(/^d_/, '').replace(/_/g, ' ')} door`.replace(/^./, (c) => c.toUpperCase()),
    text: `${d.clear_width_m.toFixed(2)} m wide; the robot is ${d.robot_width_m.toFixed(2)} m across at the angle it crosses: ${d.margin_m.toFixed(2)} m spare each side`,
  }));
}
