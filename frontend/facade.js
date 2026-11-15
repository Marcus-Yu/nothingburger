/* =====================================================================
   JRR Hall's facade, painted once onto a canvas: one 6 m bay of the 1929
   Collegiate Gothic elevation (Charles Klauder's Frick Chemistry
   Laboratory), tiled along every wall.

   Purple-grey argillite in random coursed ashlar, Indiana limestone for
   the base, string courses, window surrounds and coping, and steel
   casement windows with stone mullions; the ground floor has Tudor-arched
   heads. Proportions are drawn in metres.
   ===================================================================== */

export const BAY = 6;   // metres of wall per texture repeat

const ARGILLITE = ['#6E6670', '#776E79', '#7F7582', '#685F69', '#857B87', '#73697A', '#7A7276'];
const MORTAR = '#9E968F', LIMESTONE = '#DDD4C2', LIME_SHADE = '#C7BDA9', STEEL = '#2A2E31';

export function facadeTexture(THREE, height, { maxAniso = 8 } = {}) {
  const k = 512 / BAY;                     // px per metre
  const Wpx = 512, Hpx = Math.round(height * k);
  const c = document.createElement('canvas'); c.width = Wpx; c.height = Hpx;
  const g = c.getContext('2d');
  const Y = (m) => Hpx - m * k;            // metres above grade -> canvas y
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

  // storeys, scaled to the measured height (16.57 m: three storeys over a base, with a parapet)
  const s = height / 16.57;
  const base = 0.9 * s, bands = [5.0 * s, 9.2 * s, 13.4 * s], top = height - 0.45 * s;

  // argillite: random coursed ashlar
  g.fillStyle = MORTAR; g.fillRect(0, 0, Wpx, Hpx);
  for (let y = 0; y < height; ) {
    const ch = (0.3 + rnd() * 0.16) * s;
    for (let x = -rnd() * 0.6; x < BAY; ) {
      const cw = 0.45 + rnd() * 0.75;
      g.fillStyle = ARGILLITE[(rnd() * ARGILLITE.length) | 0];
      g.fillRect(x * k + 1.5, Y(y + ch) + 1.5, cw * k - 3, ch * k - 3);
      g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(x * k + 1.5, Y(y + ch) + 1.5, cw * k - 3, 2);
      x += cw;
    }
    y += ch;
  }

  const lime = (x0, y0, x1, y1) => {   // a limestone member with a light top and shaded underside
    g.fillStyle = LIMESTONE; g.fillRect(x0 * k, Y(y1), (x1 - x0) * k, (y1 - y0) * k);
    g.fillStyle = LIME_SHADE; g.fillRect(x0 * k, Y(y0) - 3, (x1 - x0) * k, 3);
  };
  lime(0, 0, BAY, base);                                  // plinth
  bands.forEach((b) => lime(0, b, BAY, b + 0.28 * s));    // string courses
  lime(0, top, BAY, height);                              // parapet coping

  // windows: one per bay per storey, two lights with a stone mullion and transom
  const storeys = [[base, bands[0]], [bands[0] + 0.28 * s, bands[1]], [bands[1] + 0.28 * s, bands[2]]];
  const ww = 2.9, wx0 = (BAY - ww) / 2;
  storeys.forEach(([y0, y1], i) => {
    const sill = y0 + 0.75 * s, head = y1 - 0.65 * s, sur = 0.22;
    const arched = i === 0;
    // limestone surround
    g.fillStyle = LIMESTONE;
    g.fillRect((wx0 - sur) * k, Y(head + sur + (arched ? 0.35 : 0)), (ww + 2 * sur) * k, (head - sill + 2 * sur + (arched ? 0.35 : 0)) * k);
    lime(wx0 - sur - 0.1, sill - sur, wx0 + ww + sur + 0.1, sill);   // projecting sill
    // glazing: dark steel ground, sky catching the upper panes
    const glass = g.createLinearGradient(0, Y(head), 0, Y(sill));
    glass.addColorStop(0, '#7C8C96'); glass.addColorStop(0.45, '#4B5A64'); glass.addColorStop(1, '#2F3A42');
    g.save();
    g.beginPath();
    if (arched) {   // Tudor arch: shallow four-centred head
      g.moveTo(wx0 * k, Y(sill)); g.lineTo(wx0 * k, Y(head - 0.15));
      g.quadraticCurveTo(wx0 * k, Y(head + 0.25), (wx0 + ww / 2) * k, Y(head + 0.32));
      g.quadraticCurveTo((wx0 + ww) * k, Y(head + 0.25), (wx0 + ww) * k, Y(head - 0.15));
      g.lineTo((wx0 + ww) * k, Y(sill)); g.closePath();
    } else g.rect(wx0 * k, Y(head), ww * k, (head - sill) * k);
    g.clip();
    g.fillStyle = glass; g.fillRect(wx0 * k, Y(head + 0.4), ww * k, (head - sill + 0.4) * k);
    // steel casement grid: small panes
    g.strokeStyle = STEEL; g.lineWidth = 2;
    for (let x = wx0; x <= wx0 + ww + 1e-3; x += ww / 6) { g.beginPath(); g.moveTo(x * k, Y(head + 0.4)); g.lineTo(x * k, Y(sill)); g.stroke(); }
    for (let y = sill; y <= head + 0.4; y += 0.42 * s) { g.beginPath(); g.moveTo(wx0 * k, Y(y)); g.lineTo((wx0 + ww) * k, Y(y)); g.stroke(); }
    g.restore();
    // stone mullion and transom
    g.fillStyle = LIMESTONE;
    g.fillRect((BAY / 2 - 0.11) * k, Y(head + (arched ? 0.3 : 0)), 0.22 * k, (head - sill + (arched ? 0.3 : 0)) * k);
    const tr = sill + (head - sill) * 0.72;
    g.fillRect(wx0 * k, Y(tr + 0.09), ww * k, 0.18 * k);
  });

  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace; t.wrapS = THREE.RepeatWrapping; t.anisotropy = maxAniso;
  return t;
}
