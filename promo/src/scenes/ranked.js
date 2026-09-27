// 02 RANKED — the app's annunciator legend (copy from WelcomeView) lights up
// like a cockpit panel on the beat, next to the real CLT detail screen.
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, inOutCubic, lerp, spring } from '../lib/ease.js';
import { annunciator, phone, wrap } from '../lib/ui.js';
import { IMG } from '../data.js';

const ROWS = [
  ['ACT', C.amber, 'Changes how you fly it: tower hours, frequencies, runways, navaids', 0.08],
  ['IFR', C.cyan, 'Approaches, STARs, departures and IFR routes', 0.95],
  ['FYI', C.dim, 'Worth knowing: phone numbers, fees, obstacles, reworded remarks', 1.8],
  ['NO CHG', C.green, 'Nothing changed there this cycle', 2.6],
];

export default {
  samples: (lt) => (lt / BEAT < 0.7 ? 12 : 6),
  vignette: 0.3,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const exit = inOutCubic(seg(u, 3.62, 4.0));
    // phone with the real detail screen
    const rise = spring(lt, 1.6, 0.55);
    const py = lerp(1500, 560, Math.min(1.02, rise)) + exit * 700;
    phone(ctx, IMG.detail, 1400, py, 880);
    // legend
    ctx.save();
    ctx.globalAlpha = 1 - exit;
    ctx.translate(-exit * 200, 0);
    const hp = outExpo(seg(u, 0, 0.4));
    ctx.font = `700 20px ${MONO}`;
    ctx.letterSpacing = '6px';
    ctx.fillStyle = C.text;
    ctx.globalAlpha = hp * (1 - exit);
    ctx.fillText('HOW TO READ IT', 180, 230);
    ROWS.forEach(([label, col, text, t0], i) => {
      const y = 300 + i * 158;
      const p = seg(u, t0, t0 + 0.4);
      if (p <= 0) return;
      const lit = Math.exp(-(u - t0) * 3.2) * 0.9 + 0.22;
      const flick = u - t0 < 0.06 ? (Math.floor((u - t0) * 120) % 2 ? 0.3 : 1) : 1;
      ctx.globalAlpha = (1 - exit) * flick;
      annunciator(ctx, label, 180, y, col, 2.6, lit);
      ctx.globalAlpha = (1 - exit) * outExpo(p);
      ctx.font = `400 34px ${SANS}`;
      ctx.letterSpacing = '-0.2px';
      ctx.fillStyle = C.text;
      wrap(ctx, text, 560).forEach((l, k) => ctx.fillText(l, 430 + (1 - outExpo(p)) * 40, y + 34 + k * 44));
    });
    ctx.restore();
    ctx.letterSpacing = '0px';
  },
};
