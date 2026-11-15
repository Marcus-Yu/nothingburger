/* The drafting-sheet world both 3D views share: the paper ground and its ink grid, a soft
   contact shadow, easing, and a small tween runner. */
import * as THREE from 'three';
import { COLORS } from './parts.js';

export const PAPER = 0xF4EFE7;
export const easeOut = (t) => 1 - Math.pow(1 - t, 3);
export const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function lines(points, color = COLORS.line, opacity = 1) {
  const g = new THREE.BufferGeometry().setFromPoints(points);
  return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
}

/** A square grid on the ground (y = 0) around (cx, cz). */
export function grid(size, step, opacity, cx = 0, cz = 0) {
  const p = [];
  for (let v = -size; v <= size + 1e-6; v += step) {
    p.push(new THREE.Vector3(cx + v, 0, cz - size), new THREE.Vector3(cx + v, 0, cz + size),
      new THREE.Vector3(cx - size, 0, cz + v), new THREE.Vector3(cx + size, 0, cz + v));
  }
  return lines(p, COLORS.line, opacity);
}

export function contactShadow(size = 1.7, strength = 0.28) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const x = c.getContext('2d');
  const r = x.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, `rgba(45,32,12,${strength})`);
  r.addColorStop(1, 'rgba(45,32,12,0)');
  x.fillStyle = r;
  x.fillRect(0, 0, 128, 128);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = 0.006;
  return m;
}

/** Renderer, scene, warm lights and fog on the paper colour. */
export function paperWorld(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(PAPER, 1);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(PAPER, 9, 19);
  scene.add(new THREE.HemisphereLight(0xFFF8EC, 0xC9BBA4, 1.6));
  const key = new THREE.DirectionalLight(0xFFFFFF, 1.5);
  key.position.set(-3, 6, 5);
  scene.add(key);
  return { renderer, scene };
}

/** tween(ms, fn(t), ease) -> Promise; call tick(now) once per frame. Reduced motion jumps to the end. */
export function tweens(reducedMotion) {
  const list = [];
  return {
    tween(ms, fn, ease = easeOut) {
      if (reducedMotion) ms = 1;
      return new Promise((done) => list.push({ t0: performance.now(), ms, fn, ease, done }));
    },
    tick(now) {
      for (let i = list.length - 1; i >= 0; i--) {
        const tw = list[i];
        const t = Math.min((now - tw.t0) / tw.ms, 1);
        tw.fn(tw.ease(t));
        if (t >= 1) { list.splice(i, 1); tw.done(); }
      }
    },
    finishAll() { list.splice(0).forEach((tw) => { tw.fn(1); tw.done(); }); },
  };
}

export function disposeScene(scene, renderer) {
  scene.traverse((o) => {
    o.geometry?.dispose();
    [].concat(o.material || []).forEach((m) => { m.map?.dispose(); m.dispose(); });
  });
  renderer.dispose();
}
