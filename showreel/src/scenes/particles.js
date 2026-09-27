// 03 PARTICLES — the shapes shatter on the downbeat into ~11k particles sampled
// from their exact outlines, ride a curl-noise flow wrapped in a differential
// vortex (every kick blows the galaxy outward), then get pulled onto the 3D
// lattice the pillar scene extrudes from. Fixed-step deterministic sim, so any
// frame can be rendered in isolation.
import { W, H, C, BEAT } from '../config.js';
import { smoothstep, clamp01, lerp } from '../lib/ease.js';
import { rng, TAU } from '../lib/math.js';
import { makeNoise } from '../lib/noise.js';
import { TILES, tileState, shapePathAt } from './shape.js';
import { latticeTargets } from './dimension.js';

const DT = 1 / 240;
const F = 9; // floats per particle: x y vx vy tx ty size seed spin
let P = null;
let count = 0;
let colorOf = null;
let palette = [];
let shards = []; // solid shapes that disintegrate over the first frames
const sim = { t: -1, init: null };
const noise = makeNoise(11);
const ZOOM = 1.05; // matches the shape scene's end zoom

function init() {
  const r = rng(99);
  const probe = document.createElement('canvas').getContext('2d');
  const pts = [];
  palette = [];
  const palIndex = new Map();
  for (const t of TILES) {
    const s = tileState(t, 3.9999);
    if (s.fgScale <= 0) continue;
    const path = shapePathAt(t, s);
    shards.push({ path, col: s.fg, x: s.x, y: s.y });
    if (!palIndex.has(s.fg)) {
      palIndex.set(s.fg, palette.length);
      palette.push(s.fg);
    }
    const ci = palIndex.get(s.fg);
    let n = 0, tries = 0;
    while (n < 250 && tries < 5000) {
      tries++;
      const x = s.x + (r() - 0.5) * 200, y = s.y + (r() - 0.5) * 200;
      if (!probe.isPointInPath(path, x, y)) continue;
      n++;
      const sx = 960 + (x - 960) * ZOOM, sy = 540 + (y - 540) * ZOOM;
      if (sx < -80 || sx > W + 80 || sy < -80 || sy > H + 80) continue;
      pts.push([sx, sy, 960 + (s.x - 960) * ZOOM, 540 + (s.y - 540) * ZOOM, ci]);
    }
  }
  count = pts.length;
  P = new Float32Array(count * F);
  colorOf = new Uint8Array(count);
  const targets = latticeTargets();
  // assign lattice targets in angular order -> the pull reads as one coherent swirl
  const ang = (x, y) => Math.atan2(y - 540, x - 960);
  const order = pts.map((p, i) => i).sort((a, b) => ang(pts[a][0], pts[a][1]) - ang(pts[b][0], pts[b][1]));
  const tOrder = targets.map((t, i) => i).sort((a, b) => ang(targets[a].x, targets[a].y) - ang(targets[b].x, targets[b].y));
  order.forEach((pi, k) => {
    const tg = targets[tOrder[Math.floor((k / count) * tOrder.length)]];
    const a = r() * TAU, rr = Math.sqrt(r()) * 7 * tg.s;
    P[pi * F + 4] = tg.x + Math.cos(a) * rr;
    P[pi * F + 5] = tg.y + Math.sin(a) * rr * 0.55;
  });
  pts.forEach((p, i) => {
    P[i * F + 6] = 1.4 + r() * r() * 3.2;
    P[i * F + 7] = r();
    colorOf[i] = p[4];
  });
  sim.init = pts;
  reset();
}

function reset() {
  const r = rng(5);
  sim.init.forEach((p, i) => {
    const o = i * F;
    P[o] = p[0];
    P[o + 1] = p[1];
    const dx = p[0] - p[2], dy = p[1] - p[3];
    const dl = Math.hypot(dx, dy) + 1e-3;
    const gx = p[0] - 960, gy = p[1] - 540;
    const gl = Math.hypot(gx, gy) + 1e-3;
    const sp = 260 + 700 * r() * r();
    P[o + 2] = (dx / dl) * sp + (gx / gl) * 160 + (r() - 0.5) * 120;
    P[o + 3] = (dy / dl) * sp + (gy / gl) * 160 + (r() - 0.5) * 120;
  });
  sim.t = 0;
}

function step(t) {
  const u = t / BEAT;
  const flowW = smoothstep(0.02, 0.35, t);
  const vortexW = smoothstep(0.08, 0.36, t) * (1 - smoothstep(1.0, 1.45, t));
  const pull = smoothstep(0.98, 1.6, t);
  const relax = 1 - Math.exp(-DT * lerp(2.6, 0, pull));
  const k = 170 * pull, c = 2 * Math.sqrt(k + 1e-6) * 0.9 * pull;
  // beat onsets (after the first) kick the swirl outward
  const u0 = (t - DT) / BEAT;
  const kicked = Math.floor(u) !== Math.floor(u0) && Math.floor(u) >= 1;
  const ts = t * 0.45;
  const e = 0.9;
  for (let i = 0; i < count; i++) {
    const o = i * F;
    const x = P[o], y = P[o + 1];
    let vx = P[o + 2], vy = P[o + 3];
    const gx = x - 960, gy = y - 560;
    const rr = Math.hypot(gx, gy) + 1;
    // target velocity: curl noise (2D curl of a 3D field) + vortex
    const nx = x * 0.0014, ny = y * 0.0014, nz = ts + P[o + 7] * 0.15;
    const dny = (noise.n3(nx, ny + 0.01, nz) - noise.n3(nx, ny - 0.01, nz)) / 0.02;
    const dnx = (noise.n3(nx + 0.01, ny, nz) - noise.n3(nx - 0.01, ny, nz)) / 0.02;
    let tvx = dny * 150 * flowW, tvy = -dnx * 150 * flowW;
    if (vortexW > 0) {
      // flat-ish rotation curve => inner arms outrun outer ones (spiral shear)
      const vt = 640 * Math.pow(rr / 260, -0.25) * vortexW;
      const vr = 2.3 * Math.max(0, rr - 90) * vortexW;
      tvx += (-gy / rr) * vt - (gx / rr) * vr;
      tvy += (gx / rr) * vt - (gy / rr) * vr;
    }
    vx += (tvx - vx) * relax;
    vy += (tvy - vy) * relax;
    if (kicked) {
      const kk = 520 * (1 - pull) * (0.6 + P[o + 7] * 0.8);
      vx += (gx / rr) * kk;
      vy += (gy / rr) * kk;
    }
    if (pull > 0) {
      vx += ((P[o + 4] - x) * k - vx * c) * DT;
      vy += ((P[o + 5] - y) * k - vy * c) * DT;
    }
    P[o] = x + vx * DT;
    P[o + 1] = y + vy * DT;
    P[o + 2] = vx;
    P[o + 3] = vy;
  }
}

function advanceTo(t) {
  if (t < sim.t - 1e-9) reset();
  while (sim.t + DT <= t + 1e-9) {
    step(sim.t);
    sim.t += DT;
  }
}

export default {
  init,
  samples: (lt) => (lt < 0.15 ? 12 : 5),
  hud: () => C.paper,
  vignette: 0.32,
  render(ctx, lt) {
    advanceTo(lt);
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, W, H);
    // solid shapes disintegrate over the first few frames
    const sh = 1 - clamp01(lt / 0.1);
    if (sh > 0) {
      ctx.save();
      ctx.globalAlpha = sh * sh;
      ctx.translate(960, 540);
      ctx.scale(ZOOM * (1 + (1 - sh) * 0.15), ZOOM * (1 + (1 - sh) * 0.15));
      ctx.translate(-960, -540);
      for (const s of shards) {
        ctx.fillStyle = s.col;
        ctx.fill(s.path);
      }
      ctx.restore();
    }
    const snap = smoothstep(1.66, 1.87, lt);
    const trail = 0.028 * (1 - snap);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (let c = 0; c < palette.length; c++) {
      ctx.strokeStyle = palette[c];
      // bucket by size so each colour is a handful of stroke() calls
      for (let b = 0; b < 3; b++) {
        ctx.lineWidth = [1.6, 2.6, 3.8][b];
        ctx.globalAlpha = [0.9, 0.8, 0.7][b];
        ctx.beginPath();
        for (let i = 0; i < count; i++) {
          if (colorOf[i] !== c) continue;
          const o = i * F;
          const sz = P[o + 6];
          const bb = sz < 2.2 ? 0 : sz < 3.2 ? 1 : 2;
          if (bb !== b) continue;
          const x = lerp(P[o], P[o + 4], snap), y = lerp(P[o + 1], P[o + 5], snap);
          const lx = P[o + 2] * trail, ly = P[o + 3] * trail;
          ctx.moveTo(x - lx, y - ly);
          ctx.lineTo(x + 0.01, y + 0.01);
        }
        ctx.stroke();
      }
    }
    ctx.restore();
  },
};
