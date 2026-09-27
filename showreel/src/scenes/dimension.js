// 04 DIMENSION — a 13x13 field of extruded pillars under an orbiting camera.
// Every kick sends a ring pulse out from the centre that lifts the pillars and
// lights their tops orange. Then the camera cranes to top-down, the field
// flattens into a grid, and we dive into the centre tile.
import { W, H, C, BEAT, RGB } from '../config.js';
import { seg, outBack, inOutCubic, inOutQuart, clamp01, lerp } from '../lib/ease.js';
import { hash, rgbStr, mixRgb } from '../lib/math.js';
import { makeCam } from '../lib/cam3d.js';

export const N = 13;
const SP = 120;
const PW = 84;
const HALF = (N - 1) / 2;

export function camAt(u) {
  const orbit = inOutCubic(seg(u, 0, 3.1));
  const crane = inOutQuart(seg(u, 2.85, 3.6));
  const dive = seg(u, 3.35, 4.0);
  let yaw = lerp(0.32, 1.02, orbit);
  yaw = lerp(yaw, Math.PI / 2, crane);
  const pitch = lerp(0.98, Math.PI / 2, crane);
  let dist = lerp(2750, 2450, orbit);
  // log-space zoom into the centre tile
  const zd = Math.pow(dive, 2.6);
  dist = Math.exp(lerp(Math.log(dist), Math.log(58), zd));
  return makeCam({ yaw, pitch, dist, focal: 1450, cy: lerp(560, 540, crane) });
}

export const PILLARS = [];
for (let i = 0; i < N; i++)
  for (let j = 0; j < N; j++) {
    const x = (i - HALF) * SP, z = (j - HALF) * SP;
    const d = Math.hypot(i - HALF, j - HALF);
    PILLARS.push({ i, j, x, z, d, base: 70 + 150 * hash(i, j, 3) * (0.4 + 0.6 * (1 - d / 9)), centre: i === HALF && j === HALF });
  }

// screen positions of the lattice at the first frame (particle targets)
export function latticeTargets() {
  const cam = camAt(0);
  return PILLARS.map((p) => {
    const [x, y, , s] = cam.project(p.x, 0, p.z);
    return { x, y, s };
  });
}

function pulseAt(d, u) {
  // ring pulses launched on every beat, travelling outward
  let a = 0;
  for (let k = 0; k <= 3; k++) {
    const dt = u - k;
    if (dt < 0) continue;
    const front = dt * 9.5;
    a += Math.exp(-((d - front) ** 2) / 2.2) * Math.exp(-dt * 1.2);
  }
  return a;
}

function heightAt(p, u) {
  const rise = outBack(seg(u, p.d * 0.045, p.d * 0.045 + 0.55), 1.3);
  const flat = 1 - inOutCubic(seg(u, 2.9, 3.45));
  const wave = 0.5 + 0.5 * Math.sin(p.d * 0.7 - u * 2.2 + p.i * 0.3);
  const pulse = pulseAt(p.d, u);
  return { h: rise * flat * (p.base * (0.55 + 0.45 * wave) + pulse * 210), pulse };
}

const faceIdx = [
  [4, 5, 6, 7], // top (y = -h)
  [0, 1, 5, 4], // -z
  [1, 2, 6, 5], // +x
  [2, 3, 7, 6], // +z
  [3, 0, 4, 7], // -x
];
const SHADE = [1, 0.62, 0.8, 0.5, 0.7];

export default {
  samples: (lt) => (lt / BEAT > 3.3 ? 14 : 8),
  hud: () => C.paper,
  vignette: 0.3,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, W, H);
    const cam = camAt(u);
    const grow = (p) => lerp(0.16, 1, outBack(seg(u, p.d * 0.045, p.d * 0.045 + 0.5), 1.6));
    // depth sort (far first)
    const items = PILLARS.map((p) => {
      const [, , depth] = cam.project(p.x, 0, p.z);
      return { p, depth };
    }).sort((a, b) => b.depth - a.depth);
    const v = Array.from({ length: 8 }, () => [0, 0, 0, 0]);
    for (const { p } of items) {
      const { h, pulse } = heightAt(p, u);
      const hw = (PW / 2) * grow(p);
      const cs = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
      for (let k = 0; k < 4; k++) {
        cam.project(p.x + cs[k][0] * hw, 0, p.z + cs[k][1] * hw, v[k]);
        cam.project(p.x + cs[k][0] * hw, -h - 0.01, p.z + cs[k][1] * hw, v[k + 4]);
      }
      if (v[0][2] < 5) continue; // behind camera
      const lit = clamp01(pulse * 1.1);
      let top = p.centre ? RGB.signal : mixRgb(RGB.paper, RGB.signal, lit);
      for (let f = 0; f < 5; f++) {
        const q = faceIdx[f];
        // backface cull via projected winding
        const a = v[q[0]], b = v[q[1]], c = v[q[2]];
        const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
        if (cross > 0) continue;
        if (f > 0 && h < 0.5) continue;
        const col = f === 0 ? top : mixRgb(top, [20, 20, 26], 1 - SHADE[f]);
        if (f === 0) ctx.fillStyle = rgbStr(col);
        else {
          // ambient occlusion: sides darken toward the floor
          const b0 = v[q[0]], b1 = v[q[1]], t1 = v[q[2]], t0 = v[q[3]];
          const g = ctx.createLinearGradient((t0[0] + t1[0]) / 2, (t0[1] + t1[1]) / 2, (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2);
          g.addColorStop(0, rgbStr(col));
          g.addColorStop(1, rgbStr(mixRgb(col, [12, 12, 14], 0.55)));
          ctx.fillStyle = g;
        }
        ctx.beginPath();
        ctx.moveTo(v[q[0]][0], v[q[0]][1]);
        for (let k = 1; k < 4; k++) ctx.lineTo(v[q[k]][0], v[q[k]][1]);
        ctx.closePath();
        ctx.fill();
      }
    }
  },
};
