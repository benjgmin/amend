// Pixel-level finishing pass on the final RGBA buffer: radial chromatic
// aberration (impact frames), a soft vignette and luminance-weighted film grain.
import { W, H } from './config.js';
import { rng } from './lib/math.js';

let vig = null; // Uint16 multipliers (x/256)
let noise = null; // Int8 grain table
let caSrc = null;
const NOISE_N = 1 << 22;

function init() {
  vig = new Uint16Array(W * H);
  const cx = W / 2, cy = H / 2;
  const R = Math.hypot(cx, cy);
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      const d = Math.hypot((x - cx) * 0.92, y - cy) / R;
      const k = d < 0.45 ? 0 : Math.pow((d - 0.45) / 0.55, 2.2);
      vig[y * W + x] = Math.round(1024 * k);
    }
  noise = new Int8Array(NOISE_N);
  const r = rng(77);
  for (let i = 0; i < NOISE_N; i++) noise[i] = Math.round((r() + r() + r() - 1.5) * 84);
  caSrc = new Uint8ClampedArray(W * H * 4);
}

function aberrate(d, amt) {
  caSrc.set(d);
  const s = caSrc;
  const k = 0.014 * amt;
  const cx = W / 2, cy = H / 2;
  // channel 0 (R) sampled from a shrunk coord => appears scaled up; B the opposite
  for (const [ch, sc] of [[0, 1 / (1 + k)], [2, 1 / (1 - k * 0.6)]]) {
    for (let y = 0; y < H; y++) {
      let sy = cy + (y - cy) * sc;
      if (sy < 0) sy = 0; else if (sy > H - 1.001) sy = H - 1.001;
      const y0 = sy | 0, fy = sy - y0;
      const r0 = y0 * W, r1 = r0 + W;
      let o = y * W * 4 + ch;
      for (let x = 0; x < W; x++, o += 4) {
        let sx = cx + (x - cx) * sc;
        if (sx < 0) sx = 0; else if (sx > W - 1.001) sx = W - 1.001;
        const x0 = sx | 0, fx = sx - x0;
        const a = s[(r0 + x0) * 4 + ch], b = s[(r0 + x0 + 1) * 4 + ch];
        const c = s[(r1 + x0) * 4 + ch], e = s[(r1 + x0 + 1) * 4 + ch];
        d[o] = (a + (b - a) * fx) * (1 - fy) + (c + (e - c) * fx) * fy;
      }
    }
  }
}

export function post(d, frame, { ca = 0, grain = 0.06, vignette = 0.22 } = {}) {
  if (!vig) init();
  if (ca > 0.03) aberrate(d, ca);
  const off = (Math.imul(frame + 1, 2654435761) >>> 0) % (NOISE_N - W * H - 1);
  const g = grain * 256; // fixed point
  const vg = Math.round(vignette * 256);
  for (let i = 0, p = 0; i < W * H; i++, p += 4) {
    let r = d[p], gg = d[p + 1], b = d[p + 2];
    if (vg) {
      const v = 256 - ((vig[i] * vg) >> 10);
      r = (r * v) >> 8; gg = (gg * v) >> 8; b = (b * v) >> 8;
    }
    // overlay-like weighting: strongest in mid-tones, gentle in blacks/whites
    const l = (r * 77 + gg * 150 + b * 29) >> 8;
    const w = 0.25 + (l * (255 - l)) / 16256; // 0.25..1.25
    const n = (noise[off + i] * g * w) / 256;
    d[p] = r + n;
    d[p + 1] = gg + n;
    d[p + 2] = b + n;
  }
}
