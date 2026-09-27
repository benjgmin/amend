// 07 CONTACT — the drop. Shockwave out of the breath dot, four primitives slam
// together into a mark, the wordmark rises and tightens, credits type on, the
// mark idles on the beat... then everything implodes back into the single dot
// the reel opened with, so the piece loops.
import { W, H, C, BEAT } from '../config.js';
import { seg, outExpo, outBack, inBack, outCubic, inCubic, clamp01, lerp } from '../lib/ease.js';
import { TAU } from '../lib/math.js';
import { layout, cmdsToPath } from '../lib/glyphs.js';
import { drawShape } from '../lib/shapes.js';

let WORD;
const S = 96, GAP = 12, M = S * 2 + GAP;
let lock = {};
const MARK = [
  { type: 'quarter', col: C.signal, cx: 0, cy: 0, rot: 0, from: [-1, -1] },
  { type: 'circle', col: C.paper, cx: 1, cy: 0, rot: 0, from: [1, -1] },
  { type: 'square', col: C.volt, cx: 0, cy: 1, rot: 0, from: [-1, 1] },
  { type: 'triangle', col: C.acid, cx: 1, cy: 1, rot: 0, from: [1, 1] },
];

function init() {
  WORD = layout('display', 'claude', { size: 260, wght: 820, wdth: 100 });
  const gap = 58;
  const lockW = M + gap + WORD.width;
  const x0 = Math.round(960 - lockW / 2);
  const base = 548;
  lock = { x0, base, wordX: x0 + M + gap, lockW };
}

function mark(ctx, u) {
  const { x0, base } = lock;
  MARK.forEach((m, k) => {
    const t0 = 0.02 + k * 0.07;
    const p = seg(u, t0, t0 + 0.3);
    if (p <= 0) return;
    const e = outExpo(p);
    const tx = x0 + m.cx * (S + GAP) + S / 2;
    const ty = base - M + m.cy * (S + GAP) + S / 2;
    const fx = tx + m.from[0] * 1300 * (1 - e);
    const fy = ty + m.from[1] * 800 * (1 - e);
    const land = u - (t0 + 0.3);
    const pop = land > -0.2 ? 0.1 * Math.exp(-Math.max(0, land + 0.2) * 16) * Math.sin(Math.max(0, land + 0.2) * 40) : 0;
    // idle: each tile gets one move on a later beat
    let rot = m.rot + (1 - outCubic(p)) * -Math.PI * 0.75;
    let sx = 1, sy = 1, dy = 0;
    const beatMove = seg(u, 1.0 + k * 0.5, 1.0 + k * 0.5 + 0.45);
    if (beatMove > 0) {
      if (m.type === 'quarter') rot += outBack(beatMove, 2) * (Math.PI / 2);
      if (m.type === 'circle') {
        const h = Math.sin(beatMove * Math.PI);
        dy = -26 * h;
        sy = 1 + 0.06 * h;
        sx = 1 - 0.04 * h;
      }
      if (m.type === 'square') rot += outBack(beatMove, 2) * (Math.PI / 2);
      if (m.type === 'triangle') rot += outBack(beatMove, 1.6) * ((Math.PI * 2) / 3);
    }
    ctx.save();
    ctx.translate(fx, fy + dy);
    ctx.rotate(rot);
    ctx.scale((1 + pop) * sx, (1 + pop) * sy);
    ctx.fillStyle = m.col;
    // shapes drawn to fill their S x S cell
    if (m.type === 'triangle') {
      ctx.beginPath();
      ctx.moveTo(0, -S * 0.5);
      ctx.lineTo(S * 0.5, S * 0.5);
      ctx.lineTo(-S * 0.5, S * 0.5);
      ctx.closePath();
    } else if (m.type === 'quarter') {
      ctx.beginPath();
      ctx.moveTo(S / 2, S / 2);
      ctx.arc(S / 2, S / 2, S, Math.PI, Math.PI * 1.5);
      ctx.closePath();
    } else {
      drawShape(ctx, m.type, S);
    }
    ctx.fill();
    ctx.restore();
  });
}

function wordmark(ctx, u) {
  const { base, wordX } = lock;
  const trk = lerp(0.14, -0.012, outExpo(seg(u, 0.1, 1.0))) * 260;
  const cap = WORD.capHeight;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, W, base + 70);
  ctx.clip();
  let x = wordX;
  // centre the tracking change around the word's resting width
  WORD.glyphs.forEach((g, k) => {
    const p = outExpo(seg(u, 0.14 + k * 0.045, 0.5 + k * 0.045));
    const dy = (1 - p) * (cap * 1.25 + 60);
    ctx.fillStyle = C.paper;
    ctx.fill(cmdsToPath(g.cmds, g.s, wordX + g.x + k * (trk + 0.012 * 260), base + dy));
  });
  ctx.restore();
}

function credits(ctx, u) {
  const { x0, base, wordX, lockW } = lock;
  // serif italic role line
  const ps = outExpo(seg(u, 0.5, 1.05));
  if (ps > 0) {
    ctx.save();
    ctx.globalAlpha = ps;
    ctx.font = 'italic 400 92px "Instrument Serif"';
    ctx.fillStyle = C.paper;
    ctx.beginPath();
    ctx.rect(wordX - 10, base + 20, 1200 * ps, 140);
    ctx.clip();
    ctx.fillText('motion designer', wordX + 4, base + 112 + (1 - ps) * 20);
    ctx.restore();
  }
  // hairline rule
  const pr = outExpo(seg(u, 0.75, 1.35));
  if (pr > 0) {
    ctx.fillStyle = 'rgba(242,237,228,0.35)';
    ctx.fillRect(x0, base + 170, lockW * pr, 2);
  }
  // typed info line
  const pi = seg(u, 0.95, 1.6);
  if (pi > 0) {
    ctx.font = '500 19px "Geist Mono"';
    ctx.letterSpacing = '3px';
    ctx.fillStyle = C.paper;
    ctx.globalAlpha = 0.85;
    const a = 'SHOWREEL 2026  ·  8 BARS  ·  128 BPM';
    const b = 'EVERY FRAME WRITTEN IN CODE';
    const na = Math.floor(clamp01(pi * 1.4) * a.length);
    const nb = Math.floor(clamp01(pi * 1.4 - 0.3) * b.length);
    ctx.fillText(a.slice(0, na) + (na < a.length && Math.floor(u * 16) % 2 ? '▍' : ''), x0, base + 214);
    ctx.textAlign = 'right';
    ctx.fillText(b.slice(0, nb), x0 + lockW, base + 214);
    ctx.textAlign = 'left';
    ctx.globalAlpha = 1;
  }
}

export default {
  init,
  samples: (lt) => {
    const u = lt / BEAT;
    return u < 0.6 || u > 3.5 ? 14 : 6;
  },
  vignette: 0.28,
  hud: (lt) => (lt / BEAT > 3.55 ? null : C.paper),
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, W, H);
    // implode back into the dot (anticipation swell, then collapse)
    const pc = seg(u, 3.58, 3.92);
    const sc = 1 - inBack(pc, 1.6);
    if (pc < 1) {
      ctx.save();
      ctx.translate(960, 540);
      ctx.rotate(inCubic(pc) * 0.5);
      ctx.scale(Math.max(sc, 1e-4), Math.max(sc, 1e-4));
      ctx.translate(-960, -540);
      // shockwave
      const pw = seg(u, 0, 0.55);
      if (pw > 0 && pw < 1) {
        ctx.strokeStyle = C.paper;
        ctx.globalAlpha = 0.9 * (1 - pw);
        ctx.lineWidth = 40 * (1 - pw) + 1;
        ctx.beginPath();
        ctx.arc(960, 540, 20 + 1500 * outCubic(pw), 0, TAU);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      mark(ctx, u);
      wordmark(ctx, u);
      credits(ctx, u);
      ctx.restore();
    }
    // the dot we started with
    if (pc > 0.7) {
      const r = 11 * outBack(seg(pc, 0.7, 1), 2.5);
      ctx.fillStyle = C.paper;
      ctx.beginPath();
      ctx.arc(960, 540, r, 0, TAU);
      ctx.fill();
    }
    // impact flash
    const fl = seg(u, 0, 0.14);
    if (fl < 1) {
      ctx.fillStyle = C.paper;
      ctx.globalAlpha = 0.8 * (1 - outCubic(fl));
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = 1;
    }
  },
};
