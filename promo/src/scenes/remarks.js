// 01 PLAIN-ENGLISH REMARKS — a real VRB remark (history/VRB.json, EFF 15 MAY
// 2025) types in as the FAA wrote it; each contraction is underlined and
// resolves into English, then the whole thing folds into the app's change row
// with the original FAA text expanded underneath.
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, inOutCubic, outCubic, clamp01, lerp } from '../lib/ease.js';
import { hash } from '../lib/math.js';
import { changeRow, hexA } from '../lib/ui.js';

const FAA = 'RSCD NOT MNT 2300-0600 M-F 1530-0600 WKEND AND HOL.';
// [faa token, english, line, t0 (beats), abbreviation?]
const SEGS = [
  ['RSCD', 'Runway surface condition', 0, 1.6, true],
  ['NOT MNT', 'not monitored', 0, 2.05, true],
  ['2300-0600', '2300–0600', 0, 2.45, false],
  ['M-F', 'Monday through Friday', 1, 2.85, true],
  ['1530-0600', 'and 1530–0600', 1, 3.25, false],
  ['WKEND AND HOL.', 'weekends and holidays.', 1, 3.65, true],
];
const SCR = 'abcdefghijklmnopqrstuvwxyz';

function scramble(text, p, seed) {
  let s = '';
  for (let i = 0; i < text.length; i++) {
    const th = (i / text.length) * 0.6;
    if (text[i] === ' ' || p >= th + 0.4) s += text[i];
    else if (p >= th) s += SCR[Math.floor(hash(seed, i, Math.floor(p * 30)) * 26)];
  }
  return s;
}

export default {
  samples: (lt) => (lt / BEAT > 5.8 ? 10 : 6),
  vignette: 0.3,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const fold = inOutCubic(seg(u, 5.9, 6.5));
    const exit = inOutCubic(seg(u, 9.55, 10.0));

    // ---- big decode layout
    if (fold < 1) {
      ctx.save();
      ctx.globalAlpha = 1 - fold;
      const z = lerp(1, 0.62, fold);
      ctx.translate(960, 500);
      ctx.scale(z, z);
      ctx.translate(-960, -500 + fold * 40);
      ctx.font = `600 44px ${MONO}`;
      ctx.letterSpacing = '1px';
      const tw = ctx.measureText(FAA).width;
      const fx = 960 - tw / 2, fy = 440;
      // label
      ctx.font = `600 16px ${MONO}`;
      ctx.letterSpacing = '4px';
      ctx.fillStyle = C.faint;
      ctx.fillText('FAA TEXT', fx, fy - 72);
      ctx.fillStyle = C.cyan;
      const lp = outExpo(seg(u, 1.4, 1.8));
      ctx.globalAlpha = (1 - fold) * lp;
      ctx.fillText('PLAIN ENGLISH', fx, fy + 152);
      ctx.globalAlpha = 1 - fold;
      // typed FAA text
      ctx.font = `600 44px ${MONO}`;
      ctx.letterSpacing = '1px';
      const n = Math.floor(clamp01(u / 1.2) * FAA.length);
      ctx.fillStyle = C.amber;
      ctx.shadowColor = hexA(C.amber, 0.6);
      ctx.shadowBlur = 16;
      ctx.fillText(FAA.slice(0, n), fx, fy);
      ctx.shadowBlur = 0;
      if (n < FAA.length || Math.floor(u * 4) % 2 === 0) {
        const cx = fx + ctx.measureText(FAA.slice(0, n)).width + 4;
        ctx.fillRect(cx, fy - 35, 22, 44);
      }
      // english segments laid out on two lines
      ctx.font = `500 56px ${SANS}`;
      ctx.letterSpacing = '-0.5px';
      const lines = [[], []];
      SEGS.forEach((sg) => lines[sg[2]].push(sg));
      const pos = new Map();
      lines.forEach((ln, li) => {
        const full = ln.map((s) => s[1]).join(' ');
        let x = fx;
        ln.forEach((sg) => {
          pos.set(sg, { x, y: fy + 240 + li * 76, w: ctx.measureText(sg[1]).width });
          x += ctx.measureText(sg[1] + ' ').width;
        });
      });
      ctx.font = `600 44px ${MONO}`;
      ctx.letterSpacing = '1px';
      SEGS.forEach((sg, k) => {
        const i0 = FAA.indexOf(sg[0]);
        const sx = fx + ctx.measureText(FAA.slice(0, i0)).width;
        const sw = ctx.measureText(sg[0]).width;
        const t0 = sg[3];
        const ul = outExpo(seg(u, t0, t0 + 0.25));
        const cn = outCubic(seg(u, t0 + 0.05, t0 + 0.4));
        const tp = seg(u, t0 + 0.15, t0 + 0.65);
        const P = pos.get(sg);
        const col = sg[4] ? C.cyan : C.dim;
        if (ul > 0) {
          ctx.fillStyle = col;
          ctx.fillRect(sx, fy + 14, sw * ul, 3);
        }
        if (cn > 0 && sg[4]) {
          // connector: underline -> english phrase
          const ax = sx + sw / 2, ay = fy + 20, bx = P.x + P.w / 2, by = P.y - 48;
          ctx.save();
          ctx.strokeStyle = hexA(C.cyan, 0.55);
          ctx.lineWidth = 1.5;
          ctx.setLineDash([5, 6]);
          ctx.beginPath();
          const steps = 30;
          for (let i = 0; i <= steps * cn; i++) {
            const t = i / steps;
            const x = (1 - t) ** 3 * ax + 3 * (1 - t) ** 2 * t * ax + 3 * (1 - t) * t * t * bx + t ** 3 * bx;
            const y = (1 - t) ** 3 * ay + 3 * (1 - t) ** 2 * t * (ay + 60) + 3 * (1 - t) * t * t * (by - 60) + t ** 3 * by;
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
          }
          ctx.stroke();
          ctx.restore();
        }
        if (tp > 0) {
          ctx.save();
          ctx.font = `500 56px ${SANS}`;
          ctx.letterSpacing = '-0.5px';
          ctx.fillStyle = C.text;
          ctx.fillText(scramble(sg[1], tp, k), P.x, P.y + (1 - outExpo(tp)) * 14);
          ctx.restore();
        }
      });
      ctx.restore();
    }

    // ---- folded into the app's change row
    if (fold > 0) {
      const s = 2.15;
      const w = 1060;
      ctx.save();
      ctx.globalAlpha = clamp01(fold * 1.4) * (1 - exit);
      const z = lerp(1.18, 1, fold);
      ctx.translate(960, 540);
      ctx.scale(z, z);
      ctx.translate(-960, -540 - exit * 80);
      changeRow(ctx, 960 - w / 2, 420, w, {
        color: C.dim,
        icon: 'remark',
        summary: 'Remark updated: Runway surface condition not monitored 2300-0600 Monday through Friday and 1530-0600 weekends and holidays.',
        category: 'remark',
        more: 'HIDE ▾',
      }, s, { original: ['RSCD NOT MNT 2300-0600 M-F 1530-0600 WKEND AND HOL.'] });
      // app-style date header above the card
      ctx.font = `600 ${11 * s}px ${MONO}`;
      ctx.letterSpacing = `${2 * s}px`;
      ctx.fillStyle = C.cyan;
      ctx.beginPath();
      ctx.arc(960 - w / 2 + 6, 380, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = C.text;
      ctx.fillText('EFF 15 MAY 2025', 960 - w / 2 + 26, 389);
      ctx.fillStyle = C.faint;
      ctx.textAlign = 'right';
      ctx.fillText('VRB', 960 + w / 2, 389);
      ctx.textAlign = 'left';
      ctx.restore();
    }
    ctx.letterSpacing = '0px';
  },
};
