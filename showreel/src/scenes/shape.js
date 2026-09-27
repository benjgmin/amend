// 02 SHAPE SYSTEMS — the five primitives each perform a signature move (a
// relay on 16ths), the row grows into a Bauhaus tile grid, then three
// propagating waves (rotate / morph / flip) ripple through it before the tiles
// fall away and the shapes are left, ready to shatter.
import { W, H, C, BEAT } from '../config.js';
import { seg, outBack, inOutCubic, inOutQuart, inBack } from '../lib/ease.js';
import { hash } from '../lib/math.js';
import { drawShape, shapePts, orient, align } from '../lib/shapes.js';
import { SHAPE_ROW, SHAPE_SIZE } from './type.js';

const TILE = 240;
const TYPES = ['circle', 'semi', 'quarter', 'triangle', 'square', 'ring', 'plus', 'diamond'];
const NEXT = { circle: 'square', semi: 'circle', quarter: 'triangle', triangle: 'circle', square: 'diamond', ring: 'circle', plus: 'square', diamond: 'circle' };
const FG_FOR = {
  [C.signal]: [C.ink, C.paper, C.ink],
  [C.volt]: [C.paper, C.acid, C.blush],
  [C.acid]: [C.ink, C.volt, C.ink],
  [C.paper]: [C.ink, C.signal, C.volt],
  [C.blush]: [C.ink, C.volt, C.signal],
  [C.ink]: [C.signal, C.volt, C.acid, C.paper, C.blush],
};
const BGS = [C.signal, C.volt, C.acid, C.paper, C.blush, C.ink, C.ink, C.ink, C.signal, C.ink, C.volt];
const pick = (arr, h) => arr[Math.floor(h * arr.length) % arr.length];

const NP = 200;
export const TILES = [];
for (let r = 0; r < 5; r++)
  for (let c = 0; c < 9; c++) {
    const x = 240 * c, y = 60 + 240 * r;
    const row = SHAPE_ROW.findIndex((s) => s.x === x && y === 540);
    const corner = (c <= 1 || c >= 7) && (r === 0 || r === 4);
    let bgA = corner ? pick([C.ink, C.volt], hash(c, r, 1)) : pick(BGS, hash(c, r, 1));
    let fgA = pick(FG_FOR[bgA], hash(c, r, 2));
    let type = pick(TYPES, hash(c, r, 3));
    if (row >= 0) {
      bgA = C.ink;
      fgA = SHAPE_ROW[row].col;
      type = SHAPE_ROW[row].type;
    }
    // state B (after the flip wave): fg never ink, so shapes survive on black
    let bgB = pick(BGS, hash(c, r, 4));
    if (corner) bgB = pick([C.ink, C.volt], hash(c, r, 5));
    let fgB = pick(FG_FOR[bgB].filter((x) => x !== C.ink).concat([C.signal]), hash(c, r, 6));
    if (fgB === bgB) fgB = C.paper;
    const rot0 = row >= 0 ? 0 : Math.floor(hash(c, r, 7) * 4) * (Math.PI / 2);
    const d = Math.hypot(c - 4, (r - 2) * 1.2);
    TILES.push({ c, r, x, y, row, bgA, fgA, bgB, fgB, type, next: NEXT[type], rot0, d });
  }

function initMorphs() {
  for (const t of TILES) {
    const a = orient(shapePts(t.type, SHAPE_SIZE, NP), true);
    const b = align(a, orient(shapePts(t.next, SHAPE_SIZE, NP), true), 1);
    t.pa = a;
    t.pb = b;
  }
}

// timing (beats)
const BUILD = 1.0, WAVE_ROT = 2.0, WAVE_MORPH = 2.5, WAVE_FLIP = 3.0, DROP = 3.45;

// relay moves for the initial row (index = row slot)
function relay(k, u, ctx) {
  const t0 = 0.08 + k * 0.12;
  const p = seg(u, t0, t0 + 0.42);
  let dx = 0, dy = 0, rot = 0, sx = 1, sy = 1;
  if (p > 0 && p < 1) {
    switch (k) {
      case 0: { // hop with squash
        const x = seg(p, 0.15, 0.85);
        dy = -170 * 4 * x * (1 - x);
        const pre = seg(p, 0, 0.15), land = seg(p, 0.85, 1);
        const sq = pre > 0 && pre < 1 ? Math.sin(pre * Math.PI) * 0.25 : land > 0 ? Math.sin(land * Math.PI) * 0.22 : 0;
        const st = x > 0 && x < 1 ? 0.14 * Math.abs(1 - 2 * x) : 0;
        sy = 1 - sq + st;
        sx = 1 + sq * 0.9 - st * 0.5;
        break;
      }
      case 1: rot = outBack(p, 2.2) * (Math.PI / 2); break;
      case 2: rot = outBack(p, 1.8) * ((Math.PI * 2) / 3); break;
      case 3: rot = Math.sin(p * Math.PI * 3) * 0.55 * (1 - p); break;
      case 4: sx = Math.cos(inOutCubic(p) * Math.PI); break;
    }
  } else if (p >= 1) {
    if (k === 1) rot = Math.PI / 2;
    if (k === 2) rot = (Math.PI * 2) / 3;
    if (k === 4) sx = -1;
  }
  return { dx, dy, rot, sx, sy };
}

// state of every tile at beat u (exported so the particle scene can inherit it)
export function tileState(t, u) {
  const bp = seg(u, BUILD + t.d * 0.075, BUILD + t.d * 0.075 + 0.4);
  const bgScale = t.row >= 0 ? outBack(bp, 1.4) : outBack(bp, 1.6);
  const fgScale = t.row >= 0 ? 1 : outBack(seg(u, BUILD + 0.08 + t.d * 0.075, BUILD + 0.5 + t.d * 0.075), 2.2);
  const wr = outBack(seg(u, WAVE_ROT + t.d * 0.05, WAVE_ROT + t.d * 0.05 + 0.4), 2);
  const wm = inOutQuart(seg(u, WAVE_MORPH + (t.c + t.r) * 0.035, WAVE_MORPH + (t.c + t.r) * 0.035 + 0.38));
  const wf = seg(u, WAVE_FLIP + t.c * 0.045, WAVE_FLIP + t.c * 0.045 + 0.3);
  const drop = seg(u, DROP + hash(t.c, t.r, 9) * 0.25, DROP + hash(t.c, t.r, 9) * 0.25 + 0.22);
  let rot = t.rot0 + wr * (Math.PI / 2);
  let sx = 1, sy = 1, dx = 0, dy = 0;
  if (t.row >= 0 && u < BUILD + 0.5) {
    const m = relay(t.row, u);
    rot += m.rot;
    sx = m.sx;
    sy = m.sy;
    dx = m.dx;
    dy = m.dy;
  }
  // card flip: squash X to 0, swap colours, open again
  const fx = Math.cos(inOutCubic(wf) * Math.PI);
  const flipped = wf >= 0.5;
  return {
    x: t.x + dx, y: t.y + dy, rot, sx, sy,
    bgScale: bgScale * (1 - inBack(drop, 1.5)), fgScale,
    flipX: Math.abs(fx), flipped, morph: wm,
    bg: flipped ? t.bgB : t.bgA, fg: flipped ? t.fgB : t.fgA,
  };
}

export function shapePathAt(t, s) {
  const e = s.morph;
  const path = new Path2D();
  const c = Math.cos(s.rot), sn = Math.sin(s.rot);
  for (let i = 0; i < NP; i++) {
    const a = t.pa[i], b = t.pb[i];
    const x = (a[0] + (b[0] - a[0]) * e) * s.sx * s.fgScale * s.flipX;
    const y = (a[1] + (b[1] - a[1]) * e) * s.sy * s.fgScale;
    const X = s.x + x * c - y * sn, Y = s.y + x * sn + y * c;
    if (i === 0) path.moveTo(X, Y); else path.lineTo(X, Y);
  }
  path.closePath();
  return path;
}

export default {
  init: initMorphs,
  samples: (lt) => {
    const u = lt / BEAT;
    return u < 1.6 ? 12 : 10;
  },
  hud: () => C.paper,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, W, H);
    const z = 1 + 0.05 * inOutCubic(seg(u, 0.5, 4));
    ctx.save();
    ctx.translate(960, 540);
    ctx.scale(z, z);
    ctx.translate(-960, -540);
    // tile backgrounds
    for (const t of TILES) {
      const s = tileState(t, u);
      if (s.bgScale <= 0.001 || s.bg === C.ink) continue;
      const w = TILE * s.bgScale * s.flipX + 1;
      const h = TILE * s.bgScale + 1;
      ctx.fillStyle = s.bg;
      ctx.fillRect(t.x - w / 2, t.y - h / 2, w, h);
    }
    // shapes
    for (const t of TILES) {
      const s = tileState(t, u);
      if (s.fgScale <= 0.001) continue;
      ctx.fillStyle = s.fg;
      if (t.type === 'ring' && s.morph < 0.5) {
        // ring keeps its hole until it morphs
        ctx.save();
        ctx.translate(s.x, s.y);
        ctx.rotate(s.rot);
        ctx.scale(s.sx * s.fgScale * s.flipX, s.sy * s.fgScale);
        drawShape(ctx, 'ring', SHAPE_SIZE * (1 - s.morph * 0.1));
        ctx.fill('evenodd');
        ctx.restore();
      } else {
        ctx.fill(shapePathAt(t, s));
      }
    }
    ctx.restore();
  },
};
