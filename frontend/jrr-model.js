/* =====================================================================
   JRR Hall as a recognisable model: Vexcel's footprint and measured height,
   the Collegiate Gothic facade (facade.js) on every wall, Vexcel's aerial
   photo on the roof (skylights and rooftop pavilions as they are), limestone
   quoins and coping, and a limestone Gothic portal on the Washington Road
   side for the camera to walk through.
   ===================================================================== */
import { BAY, facadeTexture } from './facade.js';

const LIMESTONE = '#DCD3C1', GOLD = '#C99A2E', INK = '#2A231B';

export function buildJRR(THREE, site, { plaza, maxAniso = 8, loader }) {
  const group = new THREE.Group();
  const ring = site.jrr.ring, H = site.jrr.h;

  // walls: direction and outward normal per edge (outward from the footprint's winding)
  const area2 = ring.reduce((a, [x1, y1], i) => { const [x2, y2] = ring[(i + 1) % ring.length]; return a + x1 * y2 - x2 * y1; }, 0);
  const walls = ring.map(([x1, y1], i) => {
    const [x2, y2] = ring[(i + 1) % ring.length], len = Math.hypot(x2 - x1, y2 - y1);
    const dx = (x2 - x1) / len, dy = (y2 - y1) / len, s = area2 > 0 ? 1 : -1;
    return { x1, y1, x2, y2, len, dx, dy, nx: dy * s, ny: -dx * s };
  });

  /* the facade on every wall: u counts bays so windows line up wall by wall */
  const pos = [], uv = [];
  for (const w of walls) {
    if (w.len < 0.05) continue;
    const bays = w.len >= BAY * 0.75 ? Math.max(1, Math.round(w.len / BAY)) : w.len / BAY;
    const A = [w.x1, 0, -w.y1], B = [w.x2, 0, -w.y2], C = [w.x2, H, -w.y2], D = [w.x1, H, -w.y1];
    // wind each quad so its front face points outward
    const ab = [B[0] - A[0], 0, B[2] - A[2]], n = [-ab[2] * H, 0, ab[0] * H];   // (B-A) x (D-A)
    const out = n[0] * w.nx + n[2] * -w.ny > 0;
    const tri = out ? [[A, 0, 0], [B, bays, 0], [C, bays, 1], [A, 0, 0], [C, bays, 1], [D, 0, 1]]
                    : [[A, 0, 0], [C, bays, 1], [B, bays, 0], [A, 0, 0], [D, 0, 1], [C, bays, 1]];
    for (const [p, u, v] of tri) { pos.push(...p); uv.push(u, v); }
  }
  const wallGeo = new THREE.BufferGeometry();
  wallGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  wallGeo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  wallGeo.computeVertexNormals();
  const wallMesh = new THREE.Mesh(wallGeo, new THREE.MeshStandardMaterial({ map: facadeTexture(THREE, H, { maxAniso }), roughness: 0.92 }));
  wallMesh.castShadow = true; wallMesh.receiveShadow = true;
  group.add(wallMesh);

  /* roof: Vexcel's aerial photo of this roof */
  const roofGeo = new THREE.ShapeGeometry(new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y))));
  const [mx0, my0] = site.roof.min, [mx1, my1] = site.roof.max, p = roofGeo.attributes.position, ruv = [];
  for (let i = 0; i < p.count; i++) ruv.push((p.getX(i) - mx0) / (mx1 - mx0), (p.getY(i) - my0) / (my1 - my0));
  roofGeo.setAttribute('uv', new THREE.Float32BufferAttribute(ruv, 2));
  roofGeo.rotateX(-Math.PI / 2);
  const roofMat = new THREE.MeshStandardMaterial({ color: '#F2EEE6', roughness: 0.95 });
  loader.load(`assets/${site.roof.file}`, (t) => { t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = maxAniso; roofMat.map = t; roofMat.color.set('#FFFFFF'); roofMat.needsUpdate = true; });
  const roof = new THREE.Mesh(roofGeo, roofMat); roof.position.y = H; roof.receiveShadow = true;
  group.add(roof);

  /* limestone coping on the parapet, with a gold line on top (the brand's one roof note) */
  const lime = new THREE.MeshStandardMaterial({ color: LIMESTONE, roughness: 0.8 });
  for (const w of walls) {
    if (w.len < 0.4) continue;
    const c = new THREE.Mesh(new THREE.BoxGeometry(w.len + 0.5, 0.42, 0.62), lime);
    c.position.set(w.x1 + w.dx * w.len / 2 - w.nx * 0.18, H + 0.21, -(w.y1 + w.dy * w.len / 2 - w.ny * 0.18));
    c.rotation.y = Math.atan2(w.dy, w.dx); c.castShadow = true;
    group.add(c);
  }
  group.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, H + 0.44, -y))), new THREE.LineBasicMaterial({ color: GOLD })));

  /* limestone quoins at every real corner: long and short blocks, alternating */
  const qPts = [];
  walls.forEach((w, i) => {
    const prev = walls[(i - 1 + walls.length) % walls.length];
    const turn = Math.abs(Math.asin(Math.max(-1, Math.min(1, prev.dx * w.dy - prev.dy * w.dx))));
    if (turn < 0.5 || w.len < 1.2 || prev.len < 1.2) return;
    for (let y = 0.9, k = 0; y < H - 0.6; y += 0.42, k++) {
      const long = k % 2 === 0;
      qPts.push([w.x1, w.y1, w.dx, w.dy, w.nx, w.ny, y, long ? 0.95 : 0.55]);       // along this wall
      qPts.push([w.x1, w.y1, -prev.dx, -prev.dy, prev.nx, prev.ny, y, long ? 0.55 : 0.95]);   // along the previous one
    }
  });
  const quoins = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.38, 1), lime, qPts.length);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), v = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  qPts.forEach(([x, y, dx, dy, nx, ny, h, len], i) => {
    v.set(x + dx * len / 2 + nx * 0.06, h + 0.19, -(y + dy * len / 2 + ny * 0.06));
    q.setFromAxisAngle(up, Math.atan2(dy, dx)); sc.set(len, 1, 0.16);
    quoins.setMatrixAt(i, m4.compose(v, q, sc));
  });
  quoins.castShadow = true;
  group.add(quoins);

  /* outline: a faint ink edge keeps the drafting character */
  group.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, H + 0.02, -y))), new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.35 })));

  /* the entrance: middle of the facade facing the Washington Road plaza */
  let door = null, best = Infinity;
  for (const w of walls) {
    if (w.len < 12) continue;
    const mx = w.x1 + w.dx * w.len / 2, my = w.y1 + w.dy * w.len / 2;
    const d = Math.hypot(mx - plaza[0], my - plaza[1]);
    if (d < best && w.nx * (plaza[0] - mx) + w.ny * (plaza[1] - my) > 0) { best = d; door = { w, x: mx, y: my }; }
  }
  const outward = new THREE.Vector3(door.w.nx, 0, -door.w.ny);
  const doorPos = new THREE.Vector3(door.x, 0, -door.y);
  group.add(gothicPortal(THREE, doorPos, outward, lime));

  return { group, door: doorPos, outward, H };
}

/* A limestone portal with a pointed Gothic arch, 1.2 m proud of the wall, lit from within */
function gothicPortal(THREE, at, outward, lime) {
  const DW = 5.6, DH = 7.2, SPRING = 4.4, JAMB = 1.3, DEPTH = 1.2, OW = DW + 2 * JAMB, OH = DH + 1.5;
  const arch = (path) => {   // left jamb up, pointed arch over, right jamb down
    path.lineTo(-DW / 2, SPRING);
    path.quadraticCurveTo(-DW / 2, SPRING + (DH - SPRING) * 0.9, 0, DH);
    path.quadraticCurveTo(DW / 2, SPRING + (DH - SPRING) * 0.9, DW / 2, SPRING);
    path.lineTo(DW / 2, 0);
  };
  const frame = new THREE.Shape(); frame.moveTo(-OW / 2, 0); frame.lineTo(-DW / 2, 0); arch(frame);
  frame.lineTo(OW / 2, 0); frame.lineTo(OW / 2, OH - 0.9); frame.lineTo(0, OH); frame.lineTo(-OW / 2, OH - 0.9); frame.closePath();
  const g = new THREE.Group(); g.position.copy(at); g.rotation.y = Math.atan2(outward.x, outward.z);
  const surround = new THREE.Mesh(new THREE.ExtrudeGeometry(frame, { depth: DEPTH, bevelEnabled: false }), new THREE.MeshStandardMaterial({ color: '#CFC5B0', roughness: 0.85 }));
  surround.castShadow = true; surround.receiveShadow = true; g.add(surround);

  // the lit doorway: warm light, shadowed under the arch so it reads deep
  const hole = new THREE.Shape(); hole.moveTo(-DW / 2, 0); arch(hole); hole.closePath();
  const holeGeo = new THREE.ShapeGeometry(hole, 24), hp = holeGeo.attributes.position, huv = [];
  for (let i = 0; i < hp.count; i++) huv.push(0.5, hp.getY(i) / DH);
  holeGeo.setAttribute('uv', new THREE.Float32BufferAttribute(huv, 2));
  const c = document.createElement('canvas'); c.width = 4; c.height = 128; const cg = c.getContext('2d');
  const gr = cg.createLinearGradient(0, 0, 0, 128); gr.addColorStop(0, '#9C8762'); gr.addColorStop(0.3, '#E2CB98'); gr.addColorStop(1, '#F8EAC6');
  cg.fillStyle = gr; cg.fillRect(0, 0, 4, 128);
  const lt = new THREE.CanvasTexture(c); lt.colorSpace = THREE.SRGBColorSpace;
  const opening = new THREE.Mesh(holeGeo, new THREE.MeshBasicMaterial({ map: lt, toneMapped: false }));
  opening.position.z = 0.05; g.add(opening);

  // a gold line traces the arch on the portal's face
  const archPts = new THREE.Path(); archPts.moveTo(-DW / 2, 0); arch(archPts);
  g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(archPts.getPoints(24).map((p) => new THREE.Vector3(p.x, p.y, DEPTH + 0.02))), new THREE.LineBasicMaterial({ color: GOLD })));

  // light spilling onto the plaza
  const sc = document.createElement('canvas'); sc.width = sc.height = 256; const sg = sc.getContext('2d');
  const rg = sg.createRadialGradient(128, 0, 0, 128, 0, 256); rg.addColorStop(0, 'rgba(232,192,104,.55)'); rg.addColorStop(0.5, 'rgba(232,192,104,.16)'); rg.addColorStop(1, 'rgba(232,192,104,0)');
  sg.fillStyle = rg; sg.fillRect(0, 0, 256, 256);
  const st = new THREE.CanvasTexture(sc); st.colorSpace = THREE.SRGBColorSpace;
  const spill = new THREE.Mesh(new THREE.PlaneGeometry(DW * 3, 14), new THREE.MeshBasicMaterial({ map: st, transparent: true, depthWrite: false, toneMapped: false }));
  spill.rotation.x = -Math.PI / 2; spill.position.set(0, 0.06, DEPTH + 7); g.add(spill);
  return g;
}
