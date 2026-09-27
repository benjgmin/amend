// EVERY 28 DAYS — an instrument dial with one tick per day of the NASR cycle.
// Ticks light on the grid, the day counter runs 01 -> 28, the dial slides left
// for the headline, and the completed ring flashes into the next cycle.
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, outBack, inOutCubic, clamp01, lerp } from '../lib/ease.js';
import { TAU } from '../lib/math.js';
import { hexA } from '../lib/ui.js';

export const TICK_AT = Array.from({ length: 28 }, (_, k) => 0.3 + k * 0.233);

function dial(ctx, u, cx, cy, s) {
  const R0 = 236 * s, R1 = 284 * s;
  const lit = TICK_AT.filter((t) => u >= t).length;
  // outer ring + progress arc
  ctx.lineCap = 'round';
  ctx.strokeStyle = 'rgba(255,255,255,0.1)';
  ctx.lineWidth = 1.5 * s;
  const rp = outExpo(seg(u, 0, 0.9));
  ctx.beginPath();
  ctx.arc(cx, cy, 306 * s, -Math.PI / 2, -Math.PI / 2 + TAU * rp);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(cx, cy, 214 * s, -Math.PI / 2, -Math.PI / 2 - TAU * rp, true);
  ctx.stroke();
  const prog = lit === 0 ? 0 : (lit - 1 + clamp01((u - TICK_AT[lit - 1]) / 0.233)) / 28;
  if (lit > 0) {
    ctx.save();
    ctx.strokeStyle = C.cyan;
    ctx.shadowColor = C.cyan;
    ctx.shadowBlur = 14 * s;
    ctx.lineWidth = 3 * s;
    ctx.beginPath();
    ctx.arc(cx, cy, 306 * s, -Math.PI / 2, -Math.PI / 2 + TAU * Math.min(1, prog + 1 / 56));
    ctx.stroke();
    ctx.restore();
  }
  // day ticks
  for (let k = 0; k < 28; k++) {
    const a = -Math.PI / 2 + ((k + 0.5) / 28) * TAU;
    const appear = outBack(seg(u, k * 0.02, k * 0.02 + 0.45), 2);
    if (appear <= 0) continue;
    const on = u >= TICK_AT[k];
    const flare = on ? Math.exp(-(u - TICK_AT[k]) * 6) : 0;
    const r0 = R0 + (1 - appear) * 30 * s, r1 = r0 + (R1 - R0) * appear;
    ctx.save();
    ctx.strokeStyle = on ? (flare > 0.5 ? '#CFF4FF' : C.cyan) : '#1E252F';
    if (on) {
      ctx.shadowColor = C.cyan;
      ctx.shadowBlur = (10 + 30 * flare) * s;
    }
    ctx.lineWidth = (8 + 3 * flare) * s;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0);
    ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
    ctx.stroke();
    ctx.restore();
  }
  // counter
  const cp = outExpo(seg(u, 0.2, 0.8));
  ctx.globalAlpha = cp;
  ctx.textAlign = 'center';
  ctx.font = `500 ${20 * s}px ${MONO}`;
  ctx.letterSpacing = `${5 * s}px`;
  ctx.fillStyle = C.dim;
  ctx.fillText('DAY', cx + 2.5 * s, cy - 88 * s);
  ctx.font = `700 ${150 * s}px ${MONO}`;
  ctx.letterSpacing = '0px';
  ctx.fillStyle = lit === 28 ? C.cyan : C.text;
  ctx.fillText(String(Math.max(1, lit)).padStart(2, '0'), cx, cy + 52 * s);
  ctx.font = `500 ${18 * s}px ${MONO}`;
  ctx.letterSpacing = `${4 * s}px`;
  ctx.fillStyle = C.faint;
  ctx.fillText('OF 28', cx + 2 * s, cy + 108 * s);
  ctx.textAlign = 'left';
  ctx.letterSpacing = '0px';
  ctx.globalAlpha = 1;
}

function riseWord(ctx, text, x, y, size, color, p) {
  if (p <= 0) return;
  ctx.save();
  ctx.beginPath();
  ctx.rect(x - 20, y - size * 1.05, 1400, size * 1.3);
  ctx.clip();
  ctx.fillStyle = color;
  ctx.fillText(text, x, y + (1 - outExpo(p)) * size * 1.15);
  ctx.restore();
}

export default {
  samples: (lt) => (lt / BEAT > 6.6 ? 12 : 8),
  hud: false,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const slide = inOutCubic(seg(u, 1.5, 2.2));
    const out = seg(u, 7.3, 8.0);
    const zs = 1 - 0.05 * Math.sin(Math.PI * Math.min(1, out * 1.6));
    ctx.save();
    ctx.translate(960, 540);
    ctx.scale(zs, zs);
    ctx.translate(-960, -540);
    dial(ctx, u, lerp(960, 600, slide), 540, lerp(1, 0.92, slide));
    // headline
    ctx.font = `800 150px ${SANS}`;
    ctx.letterSpacing = '-3px';
    riseWord(ctx, 'EVERY', 1000, 470, 150, C.text, seg(u, 1.7, 2.2));
    riseWord(ctx, '28 DAYS', 1000, 625, 150, C.text, seg(u, 2.0, 2.5));
    if (u > 2.0) {
      // repaint "28" in cyan on top
      ctx.save();
      ctx.beginPath();
      ctx.rect(980, 470, 1400, 200);
      ctx.clip();
      ctx.fillStyle = C.cyan;
      const p = outExpo(seg(u, 2.0, 2.5));
      ctx.fillText('28', 1000, 625 + (1 - p) * 172);
      ctx.restore();
    }
    ctx.letterSpacing = '0px';
    const sp = outExpo(seg(u, 3.0, 3.6));
    if (sp > 0) {
      ctx.globalAlpha = sp;
      ctx.font = `400 32px ${SANS}`;
      ctx.fillStyle = C.dim;
      ctx.fillText('the FAA publishes a new cycle of airport,', 1004, 712 + (1 - sp) * 16);
      ctx.fillText('airspace, frequency and chart data.', 1004, 754 + (1 - sp) * 16);
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    // cycle rollover flash
    const fl = seg(u, 6.59, 6.9);
    if (fl > 0 && fl < 1) {
      ctx.fillStyle = hexA(C.cyan, 0.12 * (1 - fl));
      ctx.fillRect(0, 0, W, H);
    }
  },
};
