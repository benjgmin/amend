// 00 INTRO — a single dot, squash & stretch into a line, the line unfolds into a
// layout grid, a diagonal cascade of shapes pops in, then everything is sucked
// back into the centre point (anticipation -> collapse) for the drop.
import { W, H, C, BEAT } from '../config.js';
import { seg, outBack, outExpo, inBack, inCubic, outQuad, outCubic, lerp } from '../lib/ease.js';
import { hash, TAU } from '../lib/math.js';
import { drawShape } from '../lib/shapes.js';

const COLS = [C.signal, C.signal, C.signal, C.volt, C.volt, C.acid, C.acid, C.paper, C.blush, C.blush];
const TYPES = ['square', 'circle', 'quarter', 'semi', 'triangle', 'plus', 'ring', 'circle', 'square'];

const tiles = [];
for (let i = 0; i < 16; i++)
  for (let j = 0; j < 8; j++) {
    const d = i / 15 - (1 - j / 7);
    const p = Math.exp(-(d * d) / 0.05) * 0.8 + 0.06;
    if (hash(i, j, 5) < p) {
      tiles.push({
        cx: 120 * i + 60,
        cy: 60 + 120 * j + 60,
        type: TYPES[Math.floor(hash(i, j, 9) * TYPES.length)],
        col: COLS[Math.floor(hash(j, i, 2) * COLS.length)],
        rot: Math.floor(hash(i, j, 4) * 4) * (Math.PI / 2),
        delay: (i + (7 - j)) * 0.026,
      });
    }
  }

function capsule(ctx, cx, cy, w, h) {
  const r = Math.min(w, h) / 2;
  ctx.beginPath();
  ctx.roundRect(cx - w / 2, cy - h / 2, w, h, r);
  ctx.fill();
}

export default {
  samples: (lt) => {
    const u = lt / BEAT;
    return (u > 1.1 && u < 1.6) || u > 3.4 ? 16 : 8;
  },
  hud: () => C.paper,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.ink;
    ctx.fillRect(0, 0, W, H);

    // collapse: anticipation swell then implode into the centre
    const pc = seg(u, 3.3, 4.0);
    const sc = 1 - inBack(pc, 1.4);
    ctx.save();
    ctx.translate(W / 2, H / 2);
    ctx.rotate(inCubic(pc) * (Math.PI / 2));
    ctx.scale(Math.max(sc, 0.0001), Math.max(sc, 0.0001));
    ctx.translate(-W / 2, -H / 2);
    const bright = 0.28 + 0.6 * inCubic(pc);

    // horizontal grid lines unfold from the centre line
    ctx.fillStyle = C.paper;
    for (let j = 0; j < 9; j++) {
      if (j === 4) continue;
      const p = outExpo(seg(u, 2.0 + Math.abs(j - 4) * 0.05, 2.55 + Math.abs(j - 4) * 0.05));
      if (p <= 0) continue;
      const y = lerp(540, 60 + 120 * j, p);
      ctx.globalAlpha = bright * Math.min(1, p * 3);
      ctx.fillRect(-40, y - 1, W + 80, 2);
    }
    // vertical lines grow out of the centre line
    for (let i = 1; i < 16; i++) {
      const d0 = 2.1 + Math.abs(i - 8) * 0.035;
      const p = outExpo(seg(u, d0, d0 + 0.55));
      if (p <= 0) continue;
      const hh = 600 * p;
      ctx.globalAlpha = bright;
      ctx.fillRect(120 * i - 1, 540 - hh, 2, hh * 2);
    }
    ctx.globalAlpha = 1;

    // tiles: diagonal cascade with overshoot + quarter-turn settle
    for (const tl of tiles) {
      const p = seg(u, 2.45 + tl.delay, 2.45 + tl.delay + 0.42);
      if (p <= 0) continue;
      const s = outBack(p, 2.6);
      ctx.save();
      ctx.translate(tl.cx, tl.cy);
      ctx.rotate(tl.rot + (1 - outCubic(p)) * -Math.PI / 2);
      ctx.fillStyle = tl.col;
      drawShape(ctx, tl.type, 72 * s);
      ctx.fill('evenodd');
      ctx.restore();
    }

    // the dot / line
    ctx.fillStyle = C.paper;
    if (u < 1.0) {
      const r = 11 * outBack(seg(u, 0, 0.3), 3);
      const breathe = 1 + 0.06 * Math.sin(u * TAU * 2) * seg(u, 0.3, 0.5);
      ctx.beginPath();
      ctx.arc(960, 540, r * breathe, 0, TAU);
      ctx.fill();
      // sonar ping
      const pr = seg(u, 0.02, 0.8);
      if (pr > 0 && pr < 1) {
        ctx.strokeStyle = C.paper;
        ctx.globalAlpha = 0.55 * (1 - pr);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(960, 540, 12 + 150 * outCubic(pr), 0, TAU);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      // coordinate callout
      const cp = seg(u, 0.25, 0.55);
      if (cp > 0 && u < 0.97) {
        ctx.globalAlpha = 0.85;
        ctx.strokeStyle = C.paper;
        ctx.lineWidth = 1.5;
        const lx = 960 + 18, ly = 540 - 18;
        const L = 40 * outExpo(cp);
        ctx.beginPath();
        ctx.moveTo(lx, ly);
        ctx.lineTo(lx + L * 0.7, ly - L * 0.7);
        ctx.lineTo(lx + L * 0.7 + L * 1.4, ly - L * 0.7);
        ctx.stroke();
        ctx.font = '400 14px "Geist Mono"';
        ctx.letterSpacing = '1px';
        const txt = 'X 960  Y 540';
        const n = Math.floor(seg(u, 0.4, 0.7) * txt.length);
        ctx.fillText(txt.slice(0, n), lx + 30, ly - 36);
        ctx.globalAlpha = 1;
      }
    } else {
      // anticipation squash, then stretch to a full-bleed hairline
      const pa = outQuad(seg(u, 1.0, 1.14));
      const ps = seg(u, 1.14, 1.8);
      let w = lerp(22, 34, pa), h = lerp(22, 13, pa);
      if (ps > 0) {
        w = lerp(34, W + 120, outExpo(ps));
        h = lerp(13, 2, outExpo(Math.min(1, ps * 1.6)));
      }
      ctx.globalAlpha = u > 2.0 ? lerp(1, bright, seg(u, 2.0, 2.6)) : 1;
      if (pc > 0) ctx.globalAlpha = bright;
      capsule(ctx, 960, 540, w, h);
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    // energy core right before the drop
    const pe = seg(u, 3.75, 4.0);
    if (pe > 0) {
      const g = ctx.createRadialGradient(960, 540, 0, 960, 540, 90 * pe + 4);
      g.addColorStop(0, 'rgba(242,237,228,1)');
      g.addColorStop(0.25, 'rgba(242,237,228,0.9)');
      g.addColorStop(1, 'rgba(242,237,228,0)');
      ctx.fillStyle = g;
      ctx.fillRect(760, 340, 400, 400);
    }
  },
};
