/* =====================================================================
   The ground around JRR Hall: Vexcel's aerial photo printed lightly onto
   the paper, trees where the photo shows canopy, and Scudder Plaza's sunken
   reflecting pool with the Fountain of Freedom (Yamasaki's plaza, south of
   the hall). All positions are the site's: metres, x east, y north.
   ===================================================================== */

/* Pool corners, read off the Vexcel ortho (site coordinates) */
const POOL = [[26.7, -44.8], [55.0, -39.6], [59.2, -61.9], [32.7, -68.8]];

export function buildGround(THREE, site, loader) {
  const o = site.ortho;
  const mat = new THREE.MeshBasicMaterial({ color: '#F4EFE7', toneMapped: false, depthWrite: false });
  loader.load(`assets/${o.file}`, (t) => { t.colorSpace = THREE.SRGBColorSpace; mat.map = t; mat.color.set('#FFFFFF'); mat.needsUpdate = true; });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(o.size, o.size), mat);
  m.rotation.x = -Math.PI / 2; m.position.set(o.centre[0], 0.004, -o.centre[1]); m.renderOrder = -3;
  return m;
}

/* Trees from the canopy detection: low-poly crowns in muted greens, instanced.
   `keepClear(x, y, r)` drops any that would stand in the camera's way. */
export function buildTrees(THREE, site, keepClear) {
  const trees = (site.trees || []).filter(([x, y, r]) => !keepClear(x, y, r));
  const g = new THREE.Group();
  const crowns = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), new THREE.MeshStandardMaterial({ roughness: 0.9, flatShading: true }), trees.length);
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.16, 0.24, 1, 6), new THREE.MeshStandardMaterial({ color: '#6B5A48', roughness: 1 }), trees.length);
  const greens = ['#7C986A', '#6A8758', '#8FAA78', '#728F62'].map((c) => new THREE.Color(c));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3(), c = new THREE.Color();
  trees.forEach(([x, y, r], i) => {
    const trunkH = 2.4 + r * 0.45, crownH = r * 0.82;
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), (x * 13.1 + y * 7.7) % 6.28);
    crowns.setMatrixAt(i, m4.compose(v.set(x, trunkH + crownH * 0.8, -y), q, s.set(r, crownH, r)));
    crowns.setColorAt(i, c.copy(greens[i % greens.length]).offsetHSL(0, 0, ((i * 37) % 9 - 4) * 0.008));
    trunks.setMatrixAt(i, m4.compose(v.set(x, trunkH / 2, -y), q.identity(), s.set(1, trunkH, 1)));
  });
  crowns.castShadow = true; trunks.castShadow = true;
  g.add(trunks, crowns);
  return g;
}

/* Scudder Plaza: a sunken reflecting pool with a limestone rim and the bronze in its centre */
export function buildPool(THREE) {
  const g = new THREE.Group();
  const shape = new THREE.Shape(POOL.map(([x, y]) => new THREE.Vector2(x, y)));
  const water = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshStandardMaterial({ color: '#5A6A72', roughness: 0.18, metalness: 0.15 }));
  water.rotation.x = -Math.PI / 2; water.position.y = 0.05; water.receiveShadow = true; g.add(water);
  const rim = new THREE.MeshStandardMaterial({ color: '#DCD3C1', roughness: 0.8 });
  POOL.forEach(([x1, y1], i) => {
    const [x2, y2] = POOL[(i + 1) % POOL.length], len = Math.hypot(x2 - x1, y2 - y1);
    const b = new THREE.Mesh(new THREE.BoxGeometry(len + 1, 0.5, 1), rim);
    b.position.set((x1 + x2) / 2, 0.25, -(y1 + y2) / 2); b.rotation.y = Math.atan2(y2 - y1, x2 - x1);
    b.castShadow = true; b.receiveShadow = true; g.add(b);
  });
  // the Fountain of Freedom: an abstract bronze, read here as three leaning forms
  const cx = POOL.reduce((a, p) => a + p[0], 0) / 4, cy = POOL.reduce((a, p) => a + p[1], 0) / 4;
  const bronze = new THREE.MeshStandardMaterial({ color: '#4E3E2C', roughness: 0.45, metalness: 0.6 });
  [[0, 0.35, 6.2], [2.1, -0.5, 4.6], [-1.6, 0.8, 5.1]].forEach(([dx, lean, h], i) => {
    const f = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.9, h, 7), bronze);
    f.position.set(cx + dx * 0.6, h / 2, -(cy + (i - 1) * 0.9)); f.rotation.set(lean * 0.5, i * 1.9, lean);
    f.castShadow = true; g.add(f);
  });
  return g;
}
