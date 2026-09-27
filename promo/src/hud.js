// EFB-style chrome: corner brackets, the feature tag (index + name, scrambles
// in on each cut), the AMEND nav title, and the next-cycle readout.
import { W, H, SCENES, C, MONO } from './config.js';
import { seg as prog, clamp01 } from './lib/ease.js';
import { hash } from './lib/math.js';

const M = 44;
const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-';

function scramble(text, p, seed) {
  let s = '';
  for (let i = 0; i < text.length; i++) {
    const th = (i / Math.max(1, text.length)) * 0.7;
    if (text[i] === ' ') s += ' ';
    else if (p >= th + 0.3) s += text[i];
    else if (p >= th) s += GLYPHS[Math.floor(hash(seed, i, Math.floor(p * 40)) * GLYPHS.length)];
  }
  return s;
}

export function drawHud(ctx, t, seg) {
  const idx = SCENES.indexOf(seg);
  const since = t - seg.start;
  const on = prog(t, 0.2, 0.9);
  if (on <= 0) return;
  ctx.save();
  ctx.textBaseline = 'alphabetic';
  // corner brackets
  ctx.strokeStyle = 'rgba(255,255,255,0.22)';
  ctx.lineWidth = 1.5;
  const arm = 20 * on;
  ctx.beginPath();
  for (const [x, y, sx, sy] of [[M - 16, M - 16, 1, 1], [W - M + 16, M - 16, -1, 1], [M - 16, H - M + 16, 1, -1], [W - M + 16, H - M + 16, -1, -1]]) {
    ctx.moveTo(x, y + sy * arm);
    ctx.lineTo(x, y);
    ctx.lineTo(x + sx * arm, y);
  }
  ctx.stroke();

  // feature tag (scenes 3..6)
  if (seg.label) {
    const p = clamp01(since / 0.3);
    const n = String(idx - 2).padStart(2, '0');
    ctx.font = `600 16px ${MONO}`;
    ctx.letterSpacing = '2px';
    ctx.fillStyle = C.cyan;
    ctx.beginPath();
    ctx.arc(M + 16, M + 12, 5 * clamp01(p * 3), 0, Math.PI * 2);
    ctx.fill();
    ctx.fillText(scramble(n, p, idx), M + 32, M + 18);
    ctx.fillStyle = C.dim;
    ctx.fillText(scramble('/ ' + seg.label, p, idx * 7), M + 32 + 34, M + 18);
  }
  // nav title once the brand is out
  if (idx >= 3 && idx <= 6) {
    ctx.font = `700 17px ${MONO}`;
    ctx.letterSpacing = '4px';
    ctx.fillStyle = C.text;
    ctx.textAlign = 'right';
    ctx.fillText('AMEND', W - M - 12, M + 18);
    ctx.textAlign = 'left';
  }
  // next-cycle readout (the real upcoming NASR cycle)
  if (idx >= 1 && idx <= 6) {
    ctx.font = `500 14px ${MONO}`;
    ctx.letterSpacing = '2px';
    ctx.fillStyle = C.faint;
    ctx.fillText('NASR 28-DAY CYCLE', M + 12, H - M - 8);
    ctx.textAlign = 'right';
    ctx.fillText('NEXT: 01 OCT 2026 0901Z', W - M - 12, H - M - 8);
    ctx.textAlign = 'left';
  }
  ctx.restore();
}
