// AMEND — the real wordmark (traced from the app icon) rises out of the
// collapsed line with a rounded, springy stagger; the cyan dot drops in last.
import { W, H, C, BEAT, SANS } from '../config.js';
import { seg, outExpo, inOutCubic, clamp01, lerp, spring } from '../lib/ease.js';
import { drawWordmark, wordmarkInfo } from '../lib/wordmark.js';

export default {
  samples: (lt) => (lt / BEAT < 0.9 ? 12 : 6),
  vignette: 0.3,
  hud: false,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const wm = wordmarkInfo();
    const xh = 168;
    const total = (wm.dot.cx + wm.dot.r) * xh;
    const x0 = 960 - total / 2;
    const base = 560;
    const exit = inOutCubic(seg(u, 3.35, 3.95));
    // the line the rows collapsed into
    const ln = 1 - outExpo(seg(u, 0.0, 0.35));
    if (ln > 0) {
      ctx.fillStyle = C.cyan;
      ctx.globalAlpha = ln;
      ctx.fillRect(560 - 400 * (1 - ln), base - 1, 800 + 800 * (1 - ln), 2);
      ctx.globalAlpha = 1;
    }
    ctx.save();
    ctx.translate(960, 540);
    const z = lerp(1, 0.9, exit) * (1 + 0.035 * inOutCubic(seg(u, 0.5, 3.4)));
    ctx.scale(z, z);
    ctx.translate(-960, -540 - exit * 60);
    ctx.globalAlpha = 1 - exit;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, base + 4);
    ctx.clip();
    drawWordmark(ctx, x0, base, xh, {
      color: C.mark,
      per: (i) => {
        const p = seg(u, 0.03 + i * 0.07, 0.03 + i * 0.07 + 0.55);
        const e = p <= 0 ? 0 : 1 - (1 - spring(p * 0.55, 2.6, 0.42));
        return { dy: (1 - e) * 1.6, sy: 1 + 0.12 * (1 - clamp01(p * 2)) * (p > 0 ? 1 : 0) };
      },
      dot: { alpha: 0 },
    });
    ctx.restore();
    // dot: falls, squashes on landing, settles
    const dp = seg(u, 0.4, 0.62);
    if (dp > 0) {
      const land = u - 0.62;
      let dy = -(1 - dp * dp) * 3.2;
      let sx = 1, sy = 1;
      if (land > 0) {
        const k = Math.exp(-land * 9) * Math.cos(land * 26);
        sx = 1 + 0.35 * k;
        sy = 1 - 0.3 * k;
        dy = 0.06 * (1 - sy);
      }
      drawWordmark(ctx, x0, base, xh, { color: 'rgba(0,0,0,0)', per: () => ({ alpha: 0 }), dot: { dy, sx, sy } });
    }
    // tagline
    const words = 'Know what changed at your airports every FAA cycle.'.split(' ');
    ctx.font = `500 44px ${SANS}`;
    ctx.letterSpacing = '-0.3px';
    const full = ctx.measureText(words.join(' ')).width;
    let x = 960 - full / 2;
    words.forEach((w, i) => {
      const p = outExpo(seg(u, 1.0 + i * 0.05, 1.45 + i * 0.05));
      ctx.globalAlpha = p * (1 - exit);
      ctx.fillStyle = w === 'FAA' || w === 'cycle.' ? C.text : 'rgba(240,240,240,0.78)';
      ctx.fillText(w, x, 694 + (1 - p) * 18);
      x += ctx.measureText(w + ' ').width;
    });
    ctx.restore();
    ctx.globalAlpha = 1;
    ctx.letterSpacing = '0px';
  },
};
