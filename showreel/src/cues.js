// Shared cue sheet: impacts drive camera shake + chromatic aberration in the
// picture, and the very same list is exported for the soundtrack synth.
import { BEAT, BAR } from './config.js';

const b = (bar, beat = 0) => bar * BAR + beat * BEAT;

// kind: 'boom' (big), 'hit' (medium), 'tick' (small)
export const IMPACTS = [
  { t: b(1), amp: 1.0, kind: 'boom' }, // drop into type
  ...[0.14, 0.21, 0.28, 0.35].map((o) => ({ t: b(1, o), amp: 0.3, kind: 'tick' })), // SNAP letters land
  { t: b(1, 1.1), amp: 0.3, kind: 'hit' }, // BOUNCE lands
  { t: b(2), amp: 0.3, kind: 'hit' },
  { t: b(3), amp: 0.85, kind: 'boom' }, // shatter
  { t: b(4), amp: 0.6, kind: 'hit' }, // pillars
  { t: b(5), amp: 0.5, kind: 'hit' }, // ink drop
  ...[1.03, 2.03, 3.03].map((o) => ({ t: b(5, o), amp: 0.18, kind: 'tick' })), // goo snaps
  { t: b(6), amp: 0.55, kind: 'hit' }, // montage
  ...[0.5, 1, 1.5, 2, 2.5, 3, 3.25].map((o) => ({ t: b(6, o), amp: 0.28, kind: 'tick' })),
  { t: b(7), amp: 1.0, kind: 'boom' }, // logo slam
  ...[0.12, 0.19, 0.26, 0.33].map((o) => ({ t: b(7, o), amp: 0.25, kind: 'tick' })), // mark pieces
];

export function shakeAt(t) {
  let x = 0, y = 0, r = 0, ca = 0;
  for (const im of IMPACTS) {
    const d = t - im.t;
    if (d < 0 || d > 0.6) continue;
    const e = Math.exp(-d * 11) * im.amp;
    const f = 38;
    x += Math.sin(d * f * 6.1 + im.t * 13) * e * 14;
    y += Math.cos(d * f * 5.3 + im.t * 7) * e * 10;
    r += Math.sin(d * f * 4.7 + im.t) * e * 0.006;
    ca += Math.exp(-d * 9) * im.amp;
  }
  return { x, y, r, ca };
}
