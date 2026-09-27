// 03 HISTORY — the story from the README, straight from history/VRB.json:
// Vero Beach tower hours on a 24-hour dial, extended twice (EFF 23 JAN 2025,
// EFF 10 JUL 2025), each change landing as a row on the airport's timeline.
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, inOutCubic, inCubic, clamp01 } from '../lib/ease.js';
import { TAU } from '../lib/math.js';
import { changeRow, hexA } from '../lib/ui.js';

const CX = 560, CY = 560, R = 262;
const ang = (h) => -Math.PI / 2 + (h / 24) * TAU;

function closeHour(u) {
  const a = inOutCubic(seg(u, 1.8, 2.3));
  const b = inOutCubic(seg(u, 3.8, 4.3));
  return 21 + 2 * a + 2 * b;
}
const fmt = (h) => String(Math.floor(((h % 24) + 24) % 24)).padStart(2, '0') + String(Math.round((h % 1) * 60)).padStart(2, '0');

function dial(ctx, u) {
  const draw = outExpo(seg(u, 0, 0.9));
  ctx.lineCap = 'butt';
  // hour ticks
  for (let h = 0; h < 24; h++) {
    const a = ang(h);
    const major = h % 6 === 0;
    const p = clamp01(draw * 24 - h * 0.6);
    if (p <= 0) continue;
    const r0 = R + 26, r1 = r0 + (major ? 22 : 11);
    ctx.strokeStyle = major ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.22)';
    ctx.lineWidth = major ? 3 : 2;
    ctx.globalAlpha = p;
    ctx.beginPath();
    ctx.moveTo(CX + Math.cos(a) * r0, CY + Math.sin(a) * r0);
    ctx.lineTo(CX + Math.cos(a) * r1, CY + Math.sin(a) * r1);
    ctx.stroke();
    if (major) {
      ctx.font = `600 20px ${MONO}`;
      ctx.fillStyle = C.dim;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(h).padStart(2, '0'), CX + Math.cos(a) * (R + 76), CY + Math.sin(a) * (R + 76));
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';
    }
  }
  ctx.globalAlpha = 1;
  // class E (closed) track
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 26;
  ctx.beginPath();
  ctx.arc(CX, CY, R, ang(0), ang(0) + TAU * draw);
  ctx.stroke();
  // class D (tower open) arc
  const end = closeHour(u);
  const open = outExpo(seg(u, 0.3, 1.2));
  const e0 = 7 + (21 - 7) * open;
  ctx.save();
  ctx.strokeStyle = C.green;
  ctx.shadowColor = hexA(C.green, 0.8);
  ctx.shadowBlur = 20;
  ctx.lineWidth = 26;
  ctx.beginPath();
  ctx.arc(CX, CY, R, ang(7), ang(u < 1.8 ? e0 : 21));
  ctx.stroke();
  // each extension flashes amber: that's the change
  for (const [h0, h1, t0] of [[21, 23, 1.8], [23, 25, 3.8]]) {
    const p = seg(u, t0, t0 + 0.5);
    if (p <= 0) continue;
    const hot = Math.exp(-(u - t0 - 0.5) * 1.6);
    const hh = h0 + (h1 - h0) * inOutCubic(p);
    ctx.strokeStyle = p < 1 || hot > 0.05 ? mix(C.amber, C.green, 1 - Math.min(1, hot)) : C.green;
    ctx.shadowColor = hexA(C.amber, 0.8 * Math.min(1, hot));
    ctx.beginPath();
    ctx.arc(CX, CY, R, ang(h0) - 0.002, ang(hh));
    ctx.stroke();
  }
  ctx.restore();
  // closing-time marker
  if (open > 0.9) {
    const a = ang(end);
    ctx.save();
    ctx.translate(CX + Math.cos(a) * (R - 36), CY + Math.sin(a) * (R - 36));
    ctx.rotate(a + Math.PI / 2);
    ctx.fillStyle = C.text;
    ctx.beginPath();
    ctx.moveTo(0, -12);
    ctx.lineTo(9, 6);
    ctx.lineTo(-9, 6);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
  // centre readout
  const cp = outExpo(seg(u, 0.3, 0.9));
  ctx.globalAlpha = cp;
  ctx.textAlign = 'center';
  ctx.font = `600 20px ${MONO}`;
  ctx.letterSpacing = '5px';
  ctx.fillStyle = C.dim;
  ctx.fillText('VRB TOWER', CX + 2, CY - 58);
  ctx.font = `700 64px ${MONO}`;
  ctx.letterSpacing = '0px';
  ctx.fillStyle = C.text;
  ctx.fillText(`0700–${fmt(end)}`, CX, CY + 20);
  ctx.font = `500 17px ${MONO}`;
  ctx.letterSpacing = '3px';
  ctx.fillStyle = C.green;
  ctx.fillText('CLASS D · LOCAL', CX + 1, CY + 66);
  ctx.textAlign = 'left';
  ctx.letterSpacing = '0px';
  ctx.globalAlpha = 1;
}

function mix(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const c = [16, 8, 0].map((s) => Math.round(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export default {
  samples: (lt) => (lt / BEAT > 7.2 ? 12 : 6),
  vignette: 0.3,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    // match cut out: the dial collapses toward VRB's spot on the next scene's map
    const out = inCubic(seg(u, 7.3, 8.0));
    ctx.save();
    ctx.translate(CX, CY);
    ctx.scale(1 - 0.97 * out, 1 - 0.97 * out);
    ctx.translate(-CX, -CY);
    dial(ctx, u);
    ctx.restore();
    // airport header + timeline, like the app's History tab
    const fade = 1 - seg(u, 7.2, 7.6);
    ctx.save();
    ctx.globalAlpha = fade * outExpo(seg(u, 0.3, 0.8));
    ctx.font = `800 64px ${SANS}`;
    ctx.fillStyle = C.text;
    ctx.fillText('VRB', 1000, 290);
    ctx.font = `500 30px ${SANS}`;
    ctx.fillStyle = C.dim;
    ctx.fillText('Vero Beach Rgnl · Vero Beach, FL', 1000, 336);
    ctx.restore();
    const entries = [
      ['EFF 23 JAN 2025', 'Tower hours changed: 0700-2100 -> 0700-2300 local', 1.8, 400],
      ['EFF 10 JUL 2025', 'Tower hours changed: 0700-2300 -> 0700-0100 local', 3.8, 640],
    ];
    for (const [date, text, t0, y] of entries) {
      const p = outExpo(seg(u, t0 - 0.05, t0 + 0.5));
      if (p <= 0) continue;
      ctx.save();
      ctx.globalAlpha = p * fade;
      ctx.translate((1 - p) * 60, 0);
      ctx.fillStyle = C.cyan;
      ctx.beginPath();
      ctx.arc(1008, y + 2, 7, 0, TAU);
      ctx.fill();
      ctx.font = `600 22px ${MONO}`;
      ctx.letterSpacing = '4px';
      ctx.fillStyle = C.text;
      ctx.fillText(date, 1030, y + 10);
      ctx.fillStyle = 'rgba(255,255,255,0.1)';
      ctx.fillRect(1030 + 330, y + 1, 400, 1);
      ctx.letterSpacing = '0px';
      changeRow(ctx, 1000, y + 36, 780, { color: C.amber, icon: 'tower', summary: text, category: 'tower' }, 2.15);
      ctx.restore();
    }
  },
};
