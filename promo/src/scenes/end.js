// END — the real home screen, the wordmark, and "AMEND" keyed in morse like a
// navaid ident (the soundtrack plays the same pattern at 1020 Hz).
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, lerp, spring } from '../lib/ease.js';
import { TAU } from '../lib/math.js';
import { phone, hexA } from '../lib/ui.js';
import { drawWordmark } from '../lib/wordmark.js';
import { IMG } from '../data.js';

// morse: unit 75 ms, starts 0.5 s into the shot (mirrored in audio/synth.py)
export const MORSE_UNIT = 0.075, MORSE_T0 = 0.5;
const LETTERS = [
  ['A', '.-'],
  ['M', '--'],
  ['E', '.'],
  ['N', '-.'],
  ['D', '-..'],
];
export function morseSchedule() {
  const out = [];
  let t = 0;
  LETTERS.forEach(([ch, code], li) => {
    [...code].forEach((sym, si) => {
      const len = sym === '.' ? 1 : 3;
      out.push({ li, si, sym, t0: MORSE_T0 + t * MORSE_UNIT, t1: MORSE_T0 + (t + len) * MORSE_UNIT });
      t += len + 1;
    });
    t += 2; // letter gap = 3 units total
  });
  return out;
}
const SCHED = morseSchedule();

export default {
  samples: (lt) => (lt / BEAT < 0.9 ? 12 : 6),
  vignette: 0.3,
  hud: false,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    // phone with the real home screen
    const r = spring(lt, 1.5, 0.6);
    phone(ctx, IMG.home, 1380, lerp(1560, 545, Math.min(1.03, r)), 900);
    const X = 250;
    // wordmark
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, 1100, 432);
    ctx.clip();
    drawWordmark(ctx, X, 428, 118, {
      color: C.mark,
      per: (i) => {
        const p = seg(u, 0.08 + i * 0.06, 0.55 + i * 0.06);
        const e = p <= 0 ? 0 : spring(p * 0.5, 2.6, 0.45);
        return { dy: (1 - e) * 1.6 };
      },
      dot: { alpha: 0 },
    });
    ctx.restore();
    const dp = seg(u, 0.4, 0.6);
    if (dp > 0) {
      const land = u - 0.6;
      let dy = -(1 - dp * dp) * 3, sx = 1, sy = 1;
      if (land > 0) {
        const k = Math.exp(-land * 9) * Math.cos(land * 26);
        sx = 1 + 0.35 * k;
        sy = 1 - 0.3 * k;
      }
      drawWordmark(ctx, X, 428, 118, { color: 'rgba(0,0,0,0)', per: () => ({ alpha: 0 }), dot: { dy, sx, sy } });
    }
    // tagline
    const tp = outExpo(seg(u, 0.7, 1.2));
    ctx.globalAlpha = tp;
    ctx.font = `500 42px ${SANS}`;
    ctx.letterSpacing = '-0.4px';
    ctx.fillStyle = C.text;
    ctx.fillText('Know what changed at your', X + 4, 530 + (1 - tp) * 16);
    ctx.fillText('airports every FAA cycle.', X + 4, 584 + (1 - tp) * 16);
    const ip = outExpo(seg(u, 1.3, 1.8));
    ctx.globalAlpha = ip;
    ctx.font = `600 20px ${MONO}`;
    ctx.letterSpacing = '4px';
    ctx.fillStyle = C.dim;
    ctx.fillText('FOR IPHONE · IOS 17+', X + 6, 664);
    // morse ident
    const mp = outExpo(seg(u, 0.1, 0.4));
    ctx.globalAlpha = mp;
    ctx.font = `600 15px ${MONO}`;
    ctx.letterSpacing = '4px';
    ctx.fillStyle = C.faint;
    ctx.fillText('IDENT', X + 6, 760);
    let x = X + 6;
    let lastLetter = -1;
    for (const e of SCHED) {
      if (e.li !== lastLetter && lastLetter !== -1) x += 26;
      lastLetter = e.li;
      const on = lt >= e.t0 && lt < e.t1 + 0.03;
      const done = lt >= e.t0;
      const col = on ? C.cyan : done ? hexA(C.cyan, 0.55) : 'rgba(255,255,255,0.14)';
      ctx.save();
      if (on) {
        ctx.shadowColor = C.cyan;
        ctx.shadowBlur = 18;
      }
      ctx.fillStyle = col;
      if (e.sym === '.') {
        ctx.beginPath();
        ctx.arc(x + 6, 800, 6, 0, TAU);
        ctx.fill();
        x += 12 + 12;
      } else {
        ctx.beginPath();
        ctx.roundRect(x, 794, 34, 12, 6);
        ctx.fill();
        x += 34 + 12;
      }
      ctx.restore();
    }
    // disclaimer, as in the app footer
    const dsp = outExpo(seg(u, 2.4, 3.0));
    ctx.globalAlpha = dsp;
    ctx.font = `500 14px ${MONO}`;
    ctx.letterSpacing = '2px';
    ctx.fillStyle = C.faint;
    ctx.fillText('NOT FOR NAVIGATION. ALWAYS CHECK OFFICIAL FAA PUBLICATIONS AND NOTAMS.', X + 6, 1000);
    ctx.globalAlpha = 1;
    ctx.letterSpacing = '0px';
    // soft fade to black on the last half-beat
    const fo = seg(u, 7.5, 8.0);
    if (fo > 0) {
      ctx.fillStyle = C.bg;
      ctx.globalAlpha = fo * fo;
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = 1;
    }
  },
};
