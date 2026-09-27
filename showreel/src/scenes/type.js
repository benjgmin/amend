// 01 KINETIC TYPE — four words, one per beat, each animated to *mean* itself:
// SNAP (hard ease slams), BOUNCE (gravity + squash/stretch), STRETCH (variable
// width axis on a spring, live dimension line), SHAPE (glyph outlines morph
// into the primitives that drive the next scene).
import { W, H, C, BEAT } from '../config.js';
import { seg, outExpo, inQuad, outCubic, inOutCubic, inOutQuart, spring, clamp01, lerp } from '../lib/ease.js';
import { layout, cmdsToPath, cmdsToContours } from '../lib/glyphs.js';
import { resample, orient, align, centroid, signedArea, shapePts } from '../lib/shapes.js';
import { TAU } from '../lib/math.js';

export const SHAPE_ROW = [
  { type: 'circle', col: C.signal, x: 480 },
  { type: 'square', col: C.volt, x: 720 },
  { type: 'triangle', col: C.acid, x: 960 },
  { type: 'semi', col: C.paper, x: 1200 },
  { type: 'quarter', col: C.blush, x: 1440 },
];
export const SHAPE_SIZE = 150;

let SNAP, BOUNCE, SHAPE;
const MORPH = [];
const N = 260;

function fit(text, wght, wdth, targetW, tracking = 0) {
  const l = layout('display', text, { size: 100, wght, wdth, tracking: tracking * 100 });
  const size = (100 * targetW) / l.width;
  return layout('display', text, { size, wght, wdth, tracking: tracking * size });
}

function drawGlyphAt(ctx, g, x, y) {
  ctx.fill(cmdsToPath(g.cmds, g.s, x, y));
}

function init() {
  SNAP = fit('SNAP', 900, 118, 1500, -0.01);
  BOUNCE = fit('BOUNCE', 900, 96, 1480, -0.005);
  SHAPE = fit('SHAPE', 900, 104, 1320, 0.02);
  // Precompute morph correspondences: glyph outer contour -> primitive outline.
  const base = 540 + SHAPE.capHeight / 2;
  const x0 = 960 - SHAPE.width / 2;
  SHAPE.glyphs.forEach((g, k) => {
    const cs = cmdsToContours(g.cmds, g.s, x0 + g.x, base, 12);
    cs.sort((a, b) => Math.abs(signedArea(b)) - Math.abs(signedArea(a)));
    const outer = orient(resample(cs[0], N), true);
    const ca = centroid(outer);
    const localA = outer.map((p) => [p[0] - ca[0], p[1] - ca[1]]);
    const tgt = SHAPE_ROW[k];
    let localB = orient(shapePts(tgt.type, SHAPE_SIZE, N), true);
    localB = align(localA, localB, 1);
    const holes = cs.slice(1).map((h) => {
      const r = resample(h, 120);
      return { pts: r, c: centroid(r) };
    });
    MORPH.push({ localA, localB, ca, cb: [tgt.x, 540], holes, col: tgt.col });
  });
}

// ---- word 1: SNAP ---------------------------------------------------------
const SNAP_DIRS = [[-1, 0], [0, -1], [0, 1], [1, 0]];
function drawSnap(ctx, u) {
  // SIGNAL bursts out of the collapse point
  const pr = outExpo(seg(u, 0, 0.16));
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = C.signal;
  ctx.beginPath();
  ctx.arc(960, 540, 1150 * pr, 0, TAU);
  ctx.fill();
  const L = SNAP;
  const base = 540 + L.capHeight / 2;
  const x0 = 960 - L.width / 2;
  const push = 1 + 0.035 * outCubic(seg(u, 0.3, 1.0));
  ctx.save();
  ctx.translate(960, 540);
  ctx.scale(push, push);
  ctx.translate(-960, -540);
  L.glyphs.forEach((g, k) => {
    const t0 = 0.04 + k * 0.07;
    const p = seg(u, t0, t0 + 0.14);
    if (p <= 0) return;
    const e = outExpo(p);
    const [dx, dy] = SNAP_DIRS[k];
    const off = (1 - e) * 1500;
    // perceived contact: expo ease is ~98% home after 0.1 beats
    const land = u - (t0 + 0.1);
    const pop = land > 0 ? 0.09 * Math.exp(-land * 30) * Math.cos(land * 60) : 0;
    const cx = x0 + g.x + g.adv / 2;
    const cy = base - L.capHeight / 2;
    ctx.save();
    ctx.translate(cx + dx * off, cy + dy * off);
    // stretch along travel while moving fast
    const st = (1 - e) * 0.5;
    ctx.scale(1 + pop + Math.abs(dx) * st, 1 + pop + Math.abs(dy) * st);
    ctx.fillStyle = C.ink;
    drawGlyphAt(ctx, g, -g.adv / 2, L.capHeight / 2);
    ctx.restore();
    // speed lines trailing the letter, retracting into it after it lands
    const sl = seg(u, t0 + 0.06, t0 + 0.36);
    if (sl > 0 && sl < 1) {
      const len = 420 * (1 - outCubic(sl));
      ctx.fillStyle = C.ink;
      const half = (dx !== 0 ? L.capHeight : g.adv) * 0.3;
      for (let q = -1; q <= 1; q++) {
        const o = q * half;
        const lw = q === 0 ? 10 : 6;
        const ln = len * (q === 0 ? 1 : 0.7);
        if (dx !== 0) {
          const ex = cx + dx * off + dx * (g.adv / 2 + 30);
          const x1 = ex + dx * ln;
          ctx.fillRect(Math.min(ex, x1), cy + o - lw / 2, Math.abs(ln), lw);
        } else {
          const ey = cy + dy * off + dy * (L.capHeight / 2 + 30);
          const y1 = ey + dy * ln;
          ctx.fillRect(cx + o - lw / 2, Math.min(ey, y1), lw, Math.abs(ln));
        }
      }
    }
  });
  ctx.restore();
}

// ---- word 2: BOUNCE -------------------------------------------------------
const BOUNCES = [
  { h: 150, d: 0.25 },
  { h: 42, d: 0.13 },
  { h: 10, d: 0.07 },
];
export const BOUNCE_LAND = [0, 1, 2, 3, 4, 5].map((k) => 1.1 + k * 0.045);
function bounceState(v) {
  // v: beats since first landing. Returns height above floor, squash amount, vertical speed.
  if (v < 0) {
    const f = clamp01(1 + v / 0.18); // falling for 0.18 beats
    return { y: 820 * (1 - f * f), sq: 0, vel: 2 * f };
  }
  let t = v;
  let prevH = 820;
  for (const b of BOUNCES) {
    const imp = Math.sqrt(prevH / 820);
    if (t < b.d) {
      const x = t / b.d;
      const y = 4 * b.h * x * (1 - x);
      const sq = 0.34 * imp * Math.exp(-t * 55);
      return { y, sq, vel: Math.abs(1 - 2 * x) * Math.sqrt(b.h / 820) * 2 };
    }
    t -= b.d;
    prevH = b.h;
  }
  return { y: 0, sq: 0.1 * Math.exp(-t * 55) * Math.sqrt(prevH / 820), vel: 0 };
}
function drawBounce(ctx, u) {
  ctx.fillStyle = C.volt;
  ctx.fillRect(0, 0, W, H);
  const L = BOUNCE;
  const base = 540 + L.capHeight / 2 + 30;
  const x0 = 960 - L.width / 2;
  // floor shadows first
  L.glyphs.forEach((g, k) => {
    const s = bounceState(u - BOUNCE_LAND[k]);
    const cx = x0 + g.x + g.adv / 2;
    const k2 = clamp01(1 - s.y / 700);
    ctx.fillStyle = 'rgba(8,10,70,' + (0.45 * k2 * k2).toFixed(3) + ')';
    ctx.beginPath();
    ctx.ellipse(cx, base + 26, g.adv * 0.46 * (0.4 + 0.6 * k2) * (1 + s.sq), 14 * k2 + 2, 0, 0, TAU);
    ctx.fill();
  });
  L.glyphs.forEach((g, k) => {
    const s = bounceState(u - BOUNCE_LAND[k]);
    const cx = x0 + g.x + g.adv / 2;
    const stretch = s.y > 0 ? 0.16 * s.vel : 0;
    const sy = 1 - s.sq + stretch;
    const sx = 1 + s.sq * 0.85 - stretch * 0.5;
    ctx.save();
    ctx.translate(cx, base - s.y);
    ctx.scale(sx, sy);
    ctx.fillStyle = C.paper;
    drawGlyphAt(ctx, g, -g.adv / 2, 0);
    ctx.restore();
  });
}

// ---- word 3: STRETCH ------------------------------------------------------
const STRETCH_SIZE = 250;
function drawStretch(ctx, u) {
  ctx.fillStyle = C.paper;
  ctx.fillRect(0, 0, W, H);
  const text = 'STRETCH';
  const gl = [];
  let total = 0;
  let wd = 0;
  for (let k = 0; k < text.length; k++) {
    const st = 2.06 + Math.abs(k - 3) * 0.04;
    const sp = spring((u - st) * BEAT, 2.1, 0.32);
    const wdth = Math.min(150, Math.max(50, 50 + 92 * sp));
    const wght = lerp(600, 900, clamp01(sp));
    const l = layout('display', text[k], { size: STRETCH_SIZE, wght, wdth });
    const g = l.glyphs[0];
    gl.push({ g, cap: l.capHeight });
    total += g.adv;
    wd += wdth;
  }
  const trk = -4;
  total += trk * (text.length - 1);
  const cap = gl[0].cap;
  const base = 540 + cap / 2;
  let x = 960 - total / 2;
  ctx.fillStyle = C.ink;
  for (const { g } of gl) {
    drawGlyphAt(ctx, g, x - g.x, base);
    x += g.adv + trk;
  }
  // live dimension line
  const dp = outExpo(seg(u, 2.12, 2.4));
  if (dp > 0) {
    const y = base - cap - 70;
    const l = 960 - total / 2, r = 960 + total / 2;
    ctx.globalAlpha = dp;
    ctx.fillStyle = C.ink;
    ctx.fillRect(l, y - 1, total, 2);
    ctx.fillRect(l - 1, y - 14, 2, 28);
    ctx.fillRect(r - 1, y - 14, 2, 28);
    // arrowheads
    ctx.beginPath();
    ctx.moveTo(l, y); ctx.lineTo(l + 14, y - 7); ctx.lineTo(l + 14, y + 7); ctx.closePath();
    ctx.moveTo(r, y); ctx.lineTo(r - 14, y - 7); ctx.lineTo(r - 14, y + 7); ctx.closePath();
    ctx.fill();
    const label = `${Math.round(total)} PX`;
    ctx.font = '500 20px "Geist Mono"';
    ctx.letterSpacing = '2px';
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = C.paper;
    ctx.fillRect(960 - tw / 2 - 16, y - 16, tw + 32, 32);
    ctx.fillStyle = C.ink;
    ctx.fillText(label, 960 - tw / 2, y + 7);
    // axis readout
    ctx.font = '400 17px "Geist Mono"';
    ctx.letterSpacing = '1.5px';
    const ax = `WDTH ${(wd / text.length).toFixed(1).padStart(5, '0')}   WGHT 900`;
    ctx.fillText(ax, l, base + 64);
    ctx.textAlign = 'right';
    ctx.fillText('ANYBODY VF', r, base + 64);
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
  }
}

// ---- word 4: SHAPE -> primitives ------------------------------------------
function drawShapeWord(ctx, u) {
  ctx.fillStyle = C.ink;
  ctx.fillRect(0, 0, W, H);
  const L = SHAPE;
  const base = 540 + L.capHeight / 2;
  MORPH.forEach((m, k) => {
    const rise = outExpo(seg(u, 3.0 + k * 0.03, 3.22 + k * 0.03));
    const mt = seg(u, 3.3 + k * 0.04, 3.8 + k * 0.04);
    const e = inOutQuart(mt);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, base + 4 + e * 400);
    ctx.clip();
    const dy = (1 - rise) * (L.capHeight + 20);
    const cx = lerp(m.ca[0], m.cb[0], e);
    const cy = lerp(m.ca[1], m.cb[1], e) + dy;
    const spin = Math.sin(Math.PI * e) * 0.5 * (k % 2 ? -1 : 1);
    const c = Math.cos(spin), s = Math.sin(spin);
    const path = new Path2D();
    const pts = m.localA.map((a, i) => {
      const b = m.localB[i];
      const x = a[0] + (b[0] - a[0]) * e, y = a[1] + (b[1] - a[1]) * e;
      return [cx + x * c - y * s, cy + x * s + y * c];
    });
    path.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) path.lineTo(pts[i][0], pts[i][1]);
    path.closePath();
    const hs = 1 - clamp01(e / 0.55);
    if (hs > 0) {
      for (const h of m.holes) {
        const hc = h.c;
        const ox = cx - m.ca[0] * 0, oy = 0;
        h.pts.forEach((p, i) => {
          const lx = (p[0] - hc[0]) * hs + (hc[0] - m.ca[0]), ly = (p[1] - hc[1]) * hs + (hc[1] - m.ca[1]);
          const X = cx + lx * c - ly * s, Y = cy + lx * s + ly * c;
          if (i === 0) path.moveTo(X, Y); else path.lineTo(X, Y);
        });
        path.closePath();
      }
    }
    ctx.fillStyle = m.col;
    ctx.fill(path, 'evenodd');
    ctx.restore();
  });
}

function wipe(ctx, u) {
  // transitions between words, each with its own logic
  const a = seg(u, 0.86, 1.0); // SNAP -> BOUNCE: panel drops with gravity
  if (a > 0 && u < 1) {
    ctx.fillStyle = C.volt;
    const y = H * inQuad(a);
    ctx.fillRect(0, 0, W, y);
  }
  const b = seg(u, 1.86, 2.0); // BOUNCE -> STRETCH: sliver stretches open
  if (b > 0 && u < 2) {
    ctx.fillStyle = C.paper;
    const w = W * inOutCubic(b);
    ctx.fillRect(960 - w / 2 - 3, 0, w + 6, H);
  }
  const c = seg(u, 2.86, 3.0); // STRETCH -> SHAPE: iris
  if (c > 0 && u < 3) {
    ctx.fillStyle = C.ink;
    ctx.beginPath();
    ctx.arc(960, 540, 1120 * inQuad(c), 0, TAU);
    ctx.fill();
  }
}

export default {
  init,
  samples: (lt) => {
    const u = lt / BEAT;
    if (u < 0.16) return 32; // the orange burst expands ~100px per sub-sample
    if (u < 0.5) return 16;
    return 10;
  },
  vignette: 0.12,
  hud: (lt) => {
    const u = lt / BEAT;
    if (u < 0.93) return C.ink;
    if (u < 1.93) return C.paper;
    if (u < 2.93) return C.ink;
    return C.paper;
  },
  render(ctx, lt) {
    const u = lt / BEAT;
    if (u < 1) drawSnap(ctx, u);
    else if (u < 2) drawBounce(ctx, u);
    else if (u < 3) drawStretch(ctx, u);
    else drawShapeWord(ctx, u);
    wipe(ctx, u);
  },
};
