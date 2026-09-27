// Impacts: camera shake + chromatic aberration in picture (kept gentle for a
// product film). The soundtrack is scored to the same beat grid.
import { BEAT, BAR } from './config.js';

const b = (bar, beat = 0) => bar * BAR + beat * BEAT;

export const IMPACTS = [
  { t: b(1), amp: 0.75 }, // new cycle: the flood
  { t: b(2), amp: 0.45 }, // wordmark
  { t: b(2, 0.62), amp: 0.2 }, // the dot lands
  { t: b(3), amp: 0.25 },
  { t: b(4), amp: 0.25 },
  { t: b(4, 0.1), amp: 0.2 }, // ACT lights
  { t: b(5), amp: 0.25 },
  { t: b(5, 1), amp: 0.15 },
  { t: b(5, 2), amp: 0.15 },
  { t: b(6), amp: 0.4 },
  { t: b(7), amp: 0.55 },
];

export function shakeAt(t) {
  let x = 0, y = 0, r = 0, ca = 0;
  for (const im of IMPACTS) {
    const d = t - im.t;
    if (d < 0 || d > 0.6) continue;
    const e = Math.exp(-d * 12) * im.amp;
    const f = 38;
    x += Math.sin(d * f * 6.1 + im.t * 13) * e * 10;
    y += Math.cos(d * f * 5.3 + im.t * 7) * e * 7;
    r += Math.sin(d * f * 4.7 + im.t) * e * 0.004;
    ca += Math.exp(-d * 10) * im.amp * 0.6;
  }
  return { x, y, r, ca };
}
