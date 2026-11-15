/* =====================================================================
   The landing's site: JRR Hall (jrr-model.js) among its neighbours, trees
   and Scudder Plaza (site-dressing.js) on the drafting grid, and the
   scroll-driven camera that circles the hall and walks in at its door.

   Geometry comes from assets/jrr-site.json: Vexcel building footprints,
   roof heights, aerial photo and detected tree canopy (x east, y north,
   metres, origin at JRR Hall's footprint centre).
   ===================================================================== */
import { buildJRR } from './jrr-model.js';
import { buildGround, buildTrees, buildPool } from './site-dressing.js';

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const sstep = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
const easeInOut = (t) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);

const PAPER = '#F4EFE7', INK = '#2A231B', GOLD = '#C99A2E';

/* The main entrance faces Washington Road, across the paved plaza west-south-west of the
   building (read off the Vexcel ortho, not a surveyed point). */
const PLAZA = [-25.3, -24.1];

export function createCampus(THREE, renderer, site, { reduce = false } = {}) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAPER);
  scene.fog = new THREE.Fog(PAPER, 420, 820);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 900);
  const loader = new THREE.TextureLoader();
  const maxAniso = renderer.capabilities.getMaxAnisotropy();

  /* light: warm sun from the south-west, soft sky */
  scene.add(new THREE.HemisphereLight(0xfff8ee, 0xd9cbb6, 1.2));
  const sun = new THREE.DirectionalLight(0xfff1dc, 2.0);
  sun.position.set(-120, 160, 90);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -120, right: 120, top: 120, bottom: -120, near: 10, far: 520 });
  sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.6;
  scene.add(sun);

  /* the site printed on the paper, shadows on it, and the drafting grid on top */
  scene.add(buildGround(THREE, site, loader));
  const shadowCatcher = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.ShadowMaterial({ color: 0x3a2a14, opacity: 0.2 }));
  shadowCatcher.rotation.x = -Math.PI / 2; shadowCatcher.position.y = 0.01; shadowCatcher.receiveShadow = true; shadowCatcher.renderOrder = -2;
  scene.add(shadowCatcher);
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(900, 900), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, toneMapped: false,
    uniforms: { uColor: { value: new THREE.Color(INK) } },
    vertexShader: 'varying vec3 vW;void main(){vec4 w=modelMatrix*vec4(position,1.);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}',
    fragmentShader: `uniform vec3 uColor;varying vec3 vW;
      float line(vec2 p,float s,float w){vec2 q=p/s;vec2 g=abs(fract(q-.5)-.5)/(fwidth(q)*w);return 1.-min(min(g.x,g.y),1.);}
      void main(){float mi=line(vW.xz,2.,1.);float ma=line(vW.xz,10.,1.4);float d=length(vW.xz);
      float fade=1.-smoothstep(120.,300.,d);gl_FragColor=vec4(uColor,(mi*.045+ma*.12)*fade);}`,
  }));
  grid.rotation.x = -Math.PI / 2; grid.position.y = 0.02; grid.renderOrder = -1;
  scene.add(grid);

  /* neighbours: faint paper volumes drawn in ink line-work, so JRR Hall leads */
  const extrude = (ring, h) => {
    const g = new THREE.ExtrudeGeometry(new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y))), { depth: h, bevelEnabled: false });
    g.rotateX(-Math.PI / 2);  // shape xy -> world x,-z; depth -> +y
    return g;
  };
  const nbFill = new THREE.MeshStandardMaterial({ color: PAPER, roughness: 1, transparent: true, opacity: 0.32, depthWrite: false });
  const nbEdge = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.18 });
  for (const b of site.neighbors) {
    const g = extrude(b.ring, b.h);
    scene.add(new THREE.Mesh(g, nbFill));
    scene.add(new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), nbEdge));
  }

  /* JRR Hall */
  const { group: jrr, door, outward, H } = buildJRR(THREE, site, { plaza: PLAZA, maxAniso, loader });
  scene.add(jrr);

  /* trees, keeping the walk from the plaza to the door clear; and Scudder Plaza's pool */
  const dx = outward.x, dy = -outward.z, ox = door.x, oy = -door.z;
  const onPath = (x, y, r) => {   // distance from the 34 m approach line in front of the door
    const t = clamp(((x - ox) * dx + (y - oy) * dy) / 34);
    return Math.hypot(x - (ox + dx * 34 * t), y - (oy + dy * 34 * t)) < r + 3;
  };
  scene.add(buildTrees(THREE, site, onPath));
  scene.add(buildPool(THREE));

  const doorMark = new THREE.Mesh(new THREE.RingGeometry(1.6, 2.1, 48), new THREE.MeshBasicMaterial({ color: GOLD, transparent: true, opacity: 0.9, toneMapped: false, depthWrite: false }));
  doorMark.rotation.x = -Math.PI / 2; doorMark.position.copy(door).addScaledVector(outward, 10).setY(0.07);
  scene.add(doorMark);

  /* drafting furniture: north arrow and a real-scale bar, in ink */
  const ink = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0.55 });
  const seg = (pts) => new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts.map(([x, z]) => new THREE.Vector3(x, 0.05, z))), ink);
  const NX = 78, NZ = -58;  // north-east of the building, clear of the hero caption
  scene.add(seg([[NX, NZ + 7], [NX, NZ - 7], [NX, NZ - 7], [NX - 2.4, NZ - 2.5], [NX, NZ - 7], [NX + 2.4, NZ - 2.5]]));
  const N = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 4.2), new THREE.MeshBasicMaterial({ map: letter('N'), transparent: true, depthWrite: false, toneMapped: false }));
  N.rotation.x = -Math.PI / 2; N.position.set(NX, 0.05, NZ - 11); scene.add(N);
  const SX = 40, SZ = -72;  // 0-10-20-30 m scale bar
  const ticks = [];
  for (let m = 0; m <= 30; m += 10) ticks.push([SX + m, SZ - 1.2], [SX + m, SZ + 1.2]);
  scene.add(seg([[SX, SZ], [SX + 30, SZ], ...ticks]));
  const scaleLabel = new THREE.Mesh(new THREE.PlaneGeometry(14, 3.5), new THREE.MeshBasicMaterial({ map: letter('0   10   20   30 m', 512, 128, 44), transparent: true, depthWrite: false, toneMapped: false }));
  scaleLabel.rotation.x = -Math.PI / 2; scaleLabel.position.set(SX + 15, 0.05, SZ + 4); scene.add(scaleLabel);

  function letter(text, w = 128, h = 128, px = 96) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const g = c.getContext('2d'); g.fillStyle = INK; g.globalAlpha = 0.7;
    g.font = `500 ${px}px "Geist Mono", ui-monospace, monospace`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, w / 2, h / 2);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }

  /* ---------- camera choreography ----------
     p in [0,1] is the landing's scroll progress.
       0    .. 0.10  hero: three-quarter aerial, building to the right of the title
       0.10 .. 0.74  orbit: most of a full turn, lowering, ending square on the entrance
       0.74 .. 1     approach: down to eye height at the plaza, then into the doorway  */
  const ring = site.jrr.ring;
  const azDoor = Math.atan2(outward.x, outward.z);   // camera azimuth that faces the entrance
  const AZ0 = azDoor - Math.PI * 1.55;
  // aim at the footprint's bounding-box centre, not the average of its vertices
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  const centre = new THREE.Vector3((Math.min(...xs) + Math.max(...xs)) / 2, H * 0.4, -(Math.min(...ys) + Math.max(...ys)) / 2);
  const pos = new THREE.Vector3(), look = new THREE.Vector3(), tmp = new THREE.Vector3();
  let W = 1, Hh = 1, mob = false, shadowsDone = false;
  let smoothP = 0, offX = 0;

  function orbitAt(az, el, dist, target) {
    return tmp.set(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)).multiplyScalar(dist).add(target);
  }

  function update(dt, p, mx = 0, my = 0) {
    smoothP += (p - smoothP) * (reduce ? 1 : 1 - Math.exp(-dt * 6));
    const t = smoothP;
    const orbit = easeInOut(sstep(0.1, 0.74, t));
    const approach = sstep(0.74, 0.97, t);
    const dist = lerp(mob ? 520 : 262, mob ? 330 : 255, orbit);
    const el = lerp(0.66, 0.34, orbit) + (reduce ? 0 : my * -0.025);
    const az = reduce ? AZ0 : lerp(AZ0, azDoor, orbit) + mx * 0.05 * (1 - approach);
    const aerial = orbitAt(az, el, dist, centre).clone();

    // descent to eye height, then an unhurried walk into the doorway (overlapping, one ease each)
    const a1 = easeInOut(sstep(0, 0.45, approach)), a2 = sstep(0.4, 1, approach);
    const plaza = tmp.copy(door).addScaledVector(outward, 26).setY(1.7);
    const atDoor = door.clone().addScaledVector(outward, 0.7).setY(2.6);   // inside the portal, facing the lit arch
    const ground = plaza.clone().lerp(atDoor, a2);
    pos.copy(aerial).lerp(ground, a1);
    look.copy(centre).lerp(door.clone().addScaledVector(outward, -4).setY(lerp(3.2, 2.8, a2)), a1);
    camera.position.copy(pos); camera.lookAt(look);

    const fov = lerp(32, 58, a1) + a2 * 12;
    if (Math.abs(camera.fov - fov) > 1e-3) { camera.fov = fov; camera.updateProjectionMatrix(); }
    // desktop: the building sits right of the title and of the steps panel (a negative offset
    // moves the scene right), then centres for the walk-in
    const wantOff = mob ? 0 : -W * lerp(0.2, 0.25, sstep(0.12, 0.3, t)) * (1 - sstep(0.62, 0.76, t));
    offX += (wantOff - offX) * (1 - Math.exp(-dt * 6));
    // phones: lift the building into the upper half, clear of the title
    const offY = mob ? 0.2 * Hh * (1 - orbit) : 0;
    camera.setViewOffset(W, Hh, offX, offY, W, Hh);

    doorMark.material.opacity = 0.35 + 0.55 * sstep(0.6, 0.8, t) * (1 - a2);
    if (!shadowsDone) { renderer.shadowMap.needsUpdate = true; shadowsDone = true; }
    return { fade: sstep(0.82, 1, a2) };   // keyed to the camera reaching the door, not to raw scroll
  }

  function resize(w, h, isMob) { W = w; Hh = h; mob = isMob; camera.aspect = w / h; camera.updateProjectionMatrix(); }

  return { scene, camera, update, resize };
}
