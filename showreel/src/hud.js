// Broadcast-style HUD: crop marks, timecode, scene index + name (with a text
// scramble on change), bar.beat counter and beat pips. Drawn sharp, post-blur.
import { W, H, FPS, BEAT, BAR, SCENES, C } from './config.js';
import { seg as prog, outExpo, clamp01 } from './lib/ease.js';
import { hash } from './lib/math.js';

const M = 44; // margin
const GLYPHS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/#*+-';

function scramble(text, p, seed) {
  // p: 0..1 reveal progress (left to right), unresolved chars flicker
  let s = '';
  for (let i = 0; i < text.length; i++) {
    const th = (i / Math.max(1, text.length)) * 0.75;
    if (text[i] === ' ') s += ' ';
    else if (p >= th + 0.25) s += text[i];
    else if (p >= th) s += GLYPHS[Math.floor(hash(seed, i, Math.floor(p * 40)) * GLYPHS.length)];
    else s += '';
  }
  return s;
}

function pad(n, w = 2) {
  return String(n).padStart(w, '0');
}

export function drawHud(ctx, t, seg, impl) {
  // global visibility: boots on during the intro, drops out before the end card
  const on = prog(t, 0.9, 1.5);
  const gone = t >= 12.89;
  if (on <= 0 || (gone && t < 13.3) || t > 14.8) return;
  const endCard = t >= 13.125;
  const col = impl.hud ? impl.hud(t - seg.start, t) : C.paper;
  if (!col) return;
  ctx.save();
  ctx.fillStyle = col;
  ctx.strokeStyle = col;
  ctx.globalAlpha = 0.92;
  ctx.textBaseline = 'alphabetic';

  // crop marks
  const arm = 22 * outExpo(on);
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (const [x, y, sx, sy] of [[M - 16, M - 16, 1, 1], [W - M + 16, M - 16, -1, 1], [M - 16, H - M + 16, 1, -1], [W - M + 16, H - M + 16, -1, -1]]) {
    ctx.moveTo(x, y + sy * arm);
    ctx.lineTo(x, y);
    ctx.lineTo(x + sx * arm, y);
  }
  ctx.stroke();

  const f = Math.round(t * FPS);
  const typeP = prog(t, 1.0, 1.45);

  ctx.font = '600 15px "Geist Mono"';
  ctx.letterSpacing = '1.5px';
  // top-left: name
  if (!endCard) {
    const a = scramble('CLAUDE', typeP, 3);
    ctx.fillText(a, M + 12, M + 18);
    ctx.font = '400 15px "Geist Mono"';
    ctx.fillText(scramble('MOTION DESIGN REEL 2026', typeP, 5), M + 12 + 86, M + 18);
  }

  // top-right: timecode
  ctx.font = '400 15px "Geist Mono"';
  ctx.textAlign = 'right';
  const tc = `${pad(0)}:${pad(0)}:${pad(Math.floor(f / FPS))}:${pad(f % FPS)}`;
  ctx.fillText(scramble('TC ' + tc, typeP, 9), W - M - 12, M + 18);
  ctx.textAlign = 'left';

  if (!endCard) {
    // bottom-left: scene index + label, scrambles in on every cut
    const idx = SCENES.indexOf(seg);
    const since = t - seg.start;
    const p = idx === 0 ? typeP : clamp01(since / 0.28);
    ctx.font = '600 15px "Geist Mono"';
    ctx.fillText(scramble(pad(idx), p, idx * 11), M + 12, H - M - 8);
    ctx.font = '400 15px "Geist Mono"';
    ctx.fillText(scramble('/ ' + seg.label, p, idx * 17 + 1), M + 12 + 34, H - M - 8);

    // bottom-right: bpm + bar.beat + beat pips
    const beatF = t / BEAT;
    const beatIdx = Math.floor(beatF) % 4;
    const bar = Math.floor(t / BAR) + 1;
    ctx.textAlign = 'right';
    const label = `128 BPM  ${pad(bar)}.${beatIdx + 1}`;
    ctx.fillText(scramble(label, typeP, 21), W - M - 12 - 4 * 16 - 10, H - M - 8);
    ctx.textAlign = 'left';
    for (let k = 0; k < 4; k++) {
      const x = W - M - 12 - (4 - k) * 16 + 4;
      const y = H - M - 19;
      const pk = clamp01((typeP - 0.5 - k * 0.1) * 4);
      if (pk <= 0) continue;
      if (k === beatIdx) {
        const pulse = 1 + 0.5 * Math.exp(-(beatF % 1) * 8);
        const s = 10 * pulse * pk;
        ctx.fillRect(x + 5 - s / 2, y + 5 - s / 2, s, s);
      } else {
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 1, y + 1, 8, 8);
      }
    }
  }
  ctx.restore();
}
