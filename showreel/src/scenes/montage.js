// 06 RHYTHM — hard cuts on 8th notes, then 16ths, then a half-beat of black
// with a single dot (the breath before the drop). Each cut is a different
// craft: halftone field, op-art twist, slot-machine counter, radar, glitch
// type, a textbook bouncing ball with onion skin, sunburst, ridge lines.
import { W, H, C, BEAT } from '../config.js';
import { seg, outExpo, outBack, outCubic, clamp01, lerp } from '../lib/ease.js';
import { hash, TAU } from '../lib/math.js';
import { layout, cmdsToPath } from '../lib/glyphs.js';
import { makeNoise } from '../lib/noise.js';

const noise = makeNoise(4);
// [startBeat, endBeat, fn, hudColour]
let CUTS;
let DIGITS, RHYTHM;
let glitchCv;

function init() {
  DIGITS = layout('display', '0123456789', { size: 520, wght: 900, wdth: 96 });
  RHYTHM = layout('display', 'RHYTHM', { size: 300, wght: 900, wdth: 125 });
  glitchCv = document.createElement('canvas');
  glitchCv.width = W;
  glitchCv.height = H;
  const g = glitchCv.getContext('2d');
  g.fillStyle = '#fff';
  const x0 = 960 - RHYTHM.width / 2, base = 540 + RHYTHM.capHeight / 2;
  for (const gl of RHYTHM.glyphs) g.fill(cmdsToPath(gl.cmds, gl.s, x0 + gl.x, base));
  CUTS = [
    [0.0, 0.5, halftone, C.paper],
    [0.5, 1.0, opart, C.ink],
    [1.0, 1.5, counter, C.paper],
    [1.5, 2.0, radar, C.ink],
    [2.0, 2.5, glitch, C.paper],
    [2.5, 3.0, ball, C.ink],
    [3.0, 3.25, sunburst, C.ink],
    [3.25, 3.5, ridges, C.paper],
    [3.5, 4.0, breath, null],
  ];
}

function halftone(ctx, p) {
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = C.signal;
  const S = 40;
  const cx = 960 + Math.sin(p * 3) * 200, cy = 540;
  ctx.beginPath();
  for (let y = S / 2; y < H + S; y += S)
    for (let x = S / 2 + ((y / S) % 2) * (S / 2); x < W + S; x += S) {
      const d = Math.hypot(x - cx, y - cy);
      const w = 0.5 + 0.5 * Math.sin(d * 0.016 - p * 14);
      const r = S * 0.5 * Math.pow(w, 1.4) * 1.05;
      if (r < 0.6) continue;
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, TAU);
    }
  ctx.fill();
}

function opart(ctx, p) {
  ctx.fillStyle = C.paper;
  ctx.fillRect(0, 0, W, H);
  const n = 18;
  ctx.save();
  ctx.translate(960, 540);
  for (let k = 0; k < n; k++) {
    const s = 2300 * Math.pow(0.8, k);
    const e = outCubic(clamp01(p * 1.5 - k * 0.028));
    ctx.save();
    ctx.rotate(e * (Math.PI / 2) + k * 0.02);
    ctx.fillStyle = k % 2 ? C.paper : C.ink;
    ctx.fillRect(-s / 2, -s / 2, s, s);
    ctx.restore();
  }
  ctx.restore();
}

function counter(ctx, p) {
  ctx.fillStyle = C.volt;
  ctx.fillRect(0, 0, W, H);
  const L = DIGITS;
  const g0 = L.glyphs[0];
  const adv = g0.adv;
  const cap = L.capHeight;
  const base = 540 + cap / 2 - 30;
  const target = [9, 0, 0];
  const total = adv * 3;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, base - cap - 40, W, cap + 80);
  ctx.clip();
  ctx.fillStyle = C.paper;
  for (let k = 0; k < 3; k++) {
    const spins = 10 * (k + 1) + target[k];
    const e = outExpo(seg(p, 0.02 + k * 0.08, 0.72 + k * 0.06));
    const s = e * spins;
    const d0 = Math.floor(s) % 10, d1 = (d0 + 1) % 10;
    const f = s - Math.floor(s);
    const x = 960 - total / 2 + k * adv;
    const step = cap + 70;
    for (const [d, off] of [[d0, -f * step], [d1, (1 - f) * step]]) {
      const g = L.glyphs[d];
      ctx.fill(cmdsToPath(g.cmds, g.s, x + (adv - g.adv) / 2, base - off));
    }
  }
  ctx.restore();
  ctx.font = '500 24px "Geist Mono"';
  ctx.letterSpacing = '3px';
  ctx.fillStyle = C.paper;
  ctx.textAlign = 'center';
  const lbl = 'FRAMES  ·  0 KEYFRAMES';
  const n = Math.floor(clamp01((p - 0.2) * 2.5) * lbl.length);
  ctx.fillText(lbl.slice(0, n), 960, base + 90);
  ctx.textAlign = 'left';
}

function radar(ctx, p) {
  ctx.fillStyle = C.acid;
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = C.ink;
  ctx.fillStyle = C.ink;
  for (let j = 0; j < 14; j++) {
    const r = j * 95 + p * 190 + 30;
    ctx.lineWidth = Math.max(1, 26 - j * 1.9);
    ctx.beginPath();
    ctx.arc(960, 540, r, 0, TAU);
    ctx.stroke();
  }
  // sweep wedge
  const a = p * 5.5 - 1;
  const g = ctx.createConicGradient(a, 960, 540);
  g.addColorStop(0, 'rgba(12,12,14,0.55)');
  g.addColorStop(0.12, 'rgba(12,12,14,0)');
  g.addColorStop(1, 'rgba(12,12,14,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  const pr = 40 + 30 * Math.exp(-p * 6);
  ctx.fillStyle = C.ink;
  ctx.beginPath();
  ctx.arc(960, 540, pr, 0, TAU);
  ctx.fill();
}

function glitch(ctx, p, t) {
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  const fr = Math.floor(t * 30);
  const strips = 18;
  const sh = H / strips;
  const tints = [[255, 40, 60], [40, 255, 120], [60, 90, 255]];
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  for (let c = 0; c < 3; c++) {
    // tint via a coloured copy of the text canvas
    for (let s = 0; s < strips; s++) {
      const h = hash(fr, s, 3);
      const amp = h > 0.7 ? (hash(fr, s, 5) - 0.5) * 260 : (hash(fr, s, 6) - 0.5) * 16;
      const dx = amp + (c - 1) * (10 + 18 * hash(fr, 9));
      ctx.globalAlpha = 1;
      ctx.drawImage(tinted[c], 0, s * sh, W, sh + 1, dx, s * sh, W, sh + 1);
    }
  }
  ctx.restore();
  // scanline blocks
  ctx.fillStyle = C.paper;
  for (let k = 0; k < 5; k++) {
    if (hash(fr, k, 11) < 0.5) continue;
    const y = hash(fr, k, 12) * H, w = 80 + hash(fr, k, 13) * 600, x = hash(fr, k, 14) * W;
    ctx.globalAlpha = 0.85;
    ctx.fillRect(x, y, w, 3 + hash(fr, k, 15) * 10);
  }
  ctx.globalAlpha = 1;
}
let tinted = [];
function makeTints() {
  tinted = [[255, 40, 60], [40, 255, 120], [60, 90, 255]].map((c) => {
    const cv = document.createElement('canvas');
    cv.width = W;
    cv.height = H;
    const x = cv.getContext('2d');
    x.drawImage(glitchCv, 0, 0);
    x.globalCompositeOperation = 'source-in';
    x.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
    x.fillRect(0, 0, W, H);
    return cv;
  });
}

// textbook bouncing ball: arcs, squash & stretch, onion skin, path of action
function ballAt(q) {
  // q in [0,1] across the whole move; two bounces
  const x = lerp(260, 1660, q);
  const arcs = [[0, 0.46, 520], [0.46, 0.8, 260], [0.8, 1.0, 110]];
  for (const [a, b, h] of arcs) {
    if (q <= b) {
      const s = (q - a) / (b - a);
      return { x, y: 820 - 46 - 4 * h * s * (1 - s) - (a === 0 ? 4 * h * 0.25 * (1 - s) * 0 : 0), s, edge: Math.min(s, 1 - s) };
    }
  }
  return { x, y: 774, s: 1, edge: 0 };
}
function ball(ctx, p) {
  ctx.fillStyle = C.paper;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = C.ink;
  ctx.fillRect(160, 820, 1600, 3);
  // path of action
  ctx.strokeStyle = 'rgba(12,12,14,0.35)';
  ctx.setLineDash([2, 12]);
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= 120; i++) {
    const b = ballAt(i / 120);
    if (i === 0) ctx.moveTo(b.x, b.y); else ctx.lineTo(b.x, b.y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  const q = clamp01(p * 1.05);
  // onion skin: fixed spacing samples behind the ball
  for (let k = 1; k <= 12; k++) {
    const qq = q - k * 0.045;
    if (qq < 0) break;
    const b = ballAt(qq);
    ctx.strokeStyle = `rgba(12,12,14,${(0.5 * (1 - k / 13)).toFixed(3)})`;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(b.x, b.y, 46, 0, TAU);
    ctx.stroke();
    // spacing ticks on the ground
    ctx.fillStyle = 'rgba(12,12,14,0.5)';
    ctx.fillRect(b.x - 1, 830, 2, 14);
  }
  const b = ballAt(q);
  const sq = b.edge < 0.06 ? (0.06 - b.edge) / 0.06 : 0;
  const st = b.edge > 0.06 && b.edge < 0.3 ? 0.12 * (0.3 - b.edge) / 0.24 : 0;
  ctx.save();
  ctx.translate(b.x, b.y + 46);
  ctx.scale(1 + sq * 0.35 - st * 0.4, 1 - sq * 0.3 + st);
  ctx.fillStyle = C.signal;
  ctx.beginPath();
  ctx.arc(0, -46, 46, 0, TAU);
  ctx.fill();
  ctx.restore();
  ctx.font = '400 17px "Geist Mono"';
  ctx.letterSpacing = '1.5px';
  ctx.fillStyle = C.ink;
  ctx.fillText('SQUASH / STRETCH / ARCS / SPACING', 160, 880);
}

function sunburst(ctx, p) {
  ctx.fillStyle = C.signal;
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.translate(960, 540);
  ctx.rotate(p * 0.9);
  ctx.fillStyle = C.paper;
  const n = 18;
  ctx.beginPath();
  for (let k = 0; k < n; k++) {
    const a0 = (k / n) * TAU, a1 = a0 + (TAU / n) * 0.5;
    ctx.moveTo(0, 0);
    ctx.arc(0, 0, 1400, a0, a1);
    ctx.closePath();
  }
  ctx.fill();
  ctx.fillStyle = C.ink;
  ctx.beginPath();
  ctx.arc(0, 0, 150 + 60 * outBack(clamp01(p * 2), 3), 0, TAU);
  ctx.fill();
  ctx.restore();
}

function ridges(ctx, p) {
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  const rows = 26;
  ctx.lineWidth = 3;
  ctx.strokeStyle = C.paper;
  ctx.fillStyle = C.ink;
  for (let r = 0; r < rows; r++) {
    const y0 = 250 + r * 23;
    ctx.beginPath();
    ctx.moveTo(460, y0);
    for (let x = 460; x <= 1460; x += 8) {
      const c = Math.exp(-Math.pow((x - 960) / 170, 2));
      const n = noise.n2(x * 0.012, r * 0.8 + p * 3) * 0.5 + 0.5;
      const n2 = noise.n2(x * 0.03 + 7, r * 1.3 - p * 4) * 0.5 + 0.5;
      ctx.lineTo(x, y0 - c * (n * 140 + n2 * 50) - 3 * (n2 - 0.5));
    }
    ctx.lineTo(1460, y0 + 30);
    ctx.lineTo(460, y0 + 30);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(460, y0);
    for (let x = 460; x <= 1460; x += 8) {
      const c = Math.exp(-Math.pow((x - 960) / 170, 2));
      const n = noise.n2(x * 0.012, r * 0.8 + p * 3) * 0.5 + 0.5;
      const n2 = noise.n2(x * 0.03 + 7, r * 1.3 - p * 4) * 0.5 + 0.5;
      ctx.lineTo(x, y0 - c * (n * 140 + n2 * 50) - 3 * (n2 - 0.5));
    }
    ctx.stroke();
  }
}

function breath(ctx, p) {
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  const a = outBack(seg(p, 0.12, 0.45), 3);
  const pre = seg(p, 0.75, 1);
  const r = 9 * a * (1 - 0.35 * Math.sin(pre * Math.PI));
  if (r > 0) {
    ctx.fillStyle = C.paper;
    ctx.beginPath();
    ctx.arc(960, 540, r, 0, TAU);
    ctx.fill();
  }
}

function cutAt(u) {
  for (const c of CUTS) if (u >= c[0] && u < c[1]) return c;
  return CUTS[CUTS.length - 1];
}

export default {
  init() {
    init();
    makeTints();
  },
  samples: () => 6,
  vignette: 0.18,
  // keep motion-blur subframes inside the current cut
  bounds(lt) {
    const c = cutAt(lt / BEAT);
    return [c[0] * BEAT, c[1] * BEAT];
  },
  hud: (lt) => cutAt(lt / BEAT)[3],
  render(ctx, lt, t) {
    const u = lt / BEAT;
    const c = cutAt(u);
    const p = (u - c[0]) / (c[1] - c[0]);
    c[2](ctx, p, t);
  },
};
