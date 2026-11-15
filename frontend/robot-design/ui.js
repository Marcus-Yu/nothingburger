/* Small DOM helpers the Robot Design page and the route view share. */
import { tripsFor } from './route-plan.js';

const CSS_ID = 'robot-design-css';

export const ICON = {
  back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  check: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cross: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  dash: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 8h8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  go: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  turn: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12a8 4 0 0 0 16 0M20 12a8 4 0 0 0-13-3.1" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M7 5.5L6.6 9l3.4.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

export function loadCss() {
  if (document.getElementById(CSS_ID)) return;
  const link = document.createElement('link');
  link.id = CSS_ID;
  link.rel = 'stylesheet';
  link.href = new URL('./robot-design.css', import.meta.url).href;
  document.head.append(link);
}

export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
export const fmt = (n) => Number(n).toLocaleString('en-US');

export const loadSnapshot = (scenario) => fetch(new URL(`./data/${scenario}.json`, import.meta.url)).then((r) => {
  if (!r.ok) throw new Error(`no snapshot for "${scenario}" (data/${scenario}.json)`);
  return r.json();
});

/** The job as one line: the run's tasks, in order. */
export function jobLine(snap) {
  return tripsFor(snap).filter((t) => t.kind === 'work')
    .map((t, i) => (i ? t.title.charAt(0).toLowerCase() + t.title.slice(1) : t.title)).join(', then ');
}

/** Fade a scrolling list's edges while more sits above or below. Returns a disconnect function. */
export function scrollFade(list) {
  const mark = () => {
    list.classList.toggle('more', list.scrollHeight - list.scrollTop - list.clientHeight > 4);
    list.classList.toggle('less', list.scrollTop > 4);
  };
  list.addEventListener('scroll', mark, { passive: true });
  const ro = new ResizeObserver(mark);
  ro.observe(list);
  const mo = new MutationObserver(mark);
  mo.observe(list, { childList: true, subtree: true });
  mark();
  return () => { ro.disconnect(); mo.disconnect(); list.removeEventListener('scroll', mark); };
}

/** Scroll a list so its newest row shows. */
export function showRow(list, row) {
  if (!row) return;
  const a = list.getBoundingClientRect(), b = row.getBoundingClientRect();
  if (b.bottom > a.bottom) list.scrollTop += b.bottom - a.bottom;
  else if (b.top < a.top) list.scrollTop -= a.top - b.top;
}

/** Keep Tab inside root. */
export function trapTab(e, root) {
  if (e.key !== 'Tab') return;
  const f = [...root.querySelectorAll('button:not([hidden])')].filter((b) => b.offsetParent);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
