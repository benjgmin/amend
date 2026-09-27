// 04 EVERY US AIRPORT — ~20k real airports (OurAirports, contiguous US) as
// dots. Match cut from the VRB dial: we start inside VRB's dot and pull out,
// then two years of real cycles play back: every airport that changed in a
// cycle flashes in its priority colour while the counters run.
import { W, H, C, BEAT, MONO, RGB } from '../config.js';
import { seg, outExpo, inOutCubic, lerp } from '../lib/ease.js';
import { TAU } from '../lib/math.js';
import { hexA } from '../lib/ui.js';
import { DATA } from '../data.js';

let PX, PY, N, BOX;
const CYCLE_AT = (c) => 1.3 + c * 0.19; // 27 cycles over ~5 beats
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const fmtDate = (iso) => {
  const [y, m, d] = iso.split('-');
  return `${d} ${MON[+m - 1]} ${y}`;
};

function init() {
  const m = DATA.map;
  N = m.any.length;
  const bw = 1300, bh = 780;
  const s = Math.min(bw / m.w, bh / m.h);
  BOX = { x: 860 - (m.w * s) / 2, y: 585 - (m.h * s) / 2, s };
  PX = new Float32Array(N);
  PY = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    PX[i] = BOX.x + m.xy[i * 2] * s;
    PY[i] = BOX.y + m.xy[i * 2 + 1] * s;
  }
}

export const vrbScreen = () => [PX[DATA.map.vrb], PY[DATA.map.vrb]];

function camera(u) {
  const e = inOutCubic(seg(u, 0, 1.4));
  const s = Math.exp(lerp(Math.log(6.5), 0, e));
  const [vx, vy] = vrbScreen();
  return { s, px: lerp(560, vx, e), py: lerp(560, vy, e), vx, vy };
}

function counters(ctx, u) {
  const st = DATA.stats;
  const cycles = DATA.map.cycles;
  const c = Math.max(-1, Math.min(26, Math.floor((u - 1.3) / 0.19)));
  const cum = (arr) => arr.slice(0, c + 1).reduce((a, b) => a + b, 0);
  const x = 1560;
  const p = outExpo(seg(u, 0.9, 1.4));
  if (p <= 0) return;
  ctx.save();
  ctx.globalAlpha = p;
  const row = (label, value, y, color = C.text, big = 46) => {
    ctx.font = `600 15px ${MONO}`;
    ctx.letterSpacing = '3px';
    ctx.fillStyle = C.faint;
    ctx.fillText(label, x, y);
    ctx.font = `700 ${big}px ${MONO}`;
    ctx.letterSpacing = '0px';
    ctx.fillStyle = color;
    ctx.fillText(value, x, y + big + 6);
  };
  row('CYCLE', `${String(c + 1).padStart(2, '0')}/27`, 250);
  row('EFFECTIVE', c >= 0 ? fmtDate(cycles[c]) : '—', 370, C.cyan, 30);
  row('CHANGES', cum(st.per_cycle.changes).toLocaleString('en-US'), 470);
  row('ACTION ITEMS', cum(st.per_cycle.action).toLocaleString('en-US'), 590, C.amber);
  const ap = outExpo(seg(u, 6.4, 6.9));
  if (ap > 0) {
    ctx.globalAlpha = p * ap;
    row('AIRPORTS', st.airports.toLocaleString('en-US'), 710, C.green);
  }
  ctx.restore();
}

export default {
  init,
  samples: (lt) => (lt / BEAT < 1.5 ? 12 : 5),
  vignette: 0.3,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const m = DATA.map;
    const cam = camera(u);
    const exit = inOutCubic(seg(u, 7.5, 8.0));
    const reveal = outExpo(seg(u, 0.0, 0.7));
    const ds = 2.3 * Math.pow(cam.s, 0.45);
    const cNow = (u - 1.3) / 0.19;
    // base dots
    const zoomBoost = 1 + 0.9 * (1 - inOutCubic(seg(u, 0, 1.4)));
    ctx.fillStyle = `rgba(120,140,160,${Math.min(0.75, 0.32 * reveal * zoomBoost * (1 - exit)).toFixed(3)})`;
    ctx.beginPath();
    const tx = (i) => cam.px + (PX[i] - cam.vx) * cam.s;
    const ty = (i) => cam.py + (PY[i] - cam.vy) * cam.s + exit * 90;
    for (let i = 0; i < N; i++) {
      const x = tx(i), y = ty(i);
      if (x < -10 || x > W + 10 || y < -10 || y > H + 10) continue;
      ctx.rect(x - ds / 2, y - ds / 2, ds, ds);
    }
    ctx.fill();
    // cycle flashes
    if (cNow > -1) {
      const buckets = [[], [], []];
      const cHi = Math.min(26, Math.floor(cNow));
      for (let i = 0; i < N; i++) {
        const any = m.any[i];
        if (!any) continue;
        // most recent cycle (<= now) this airport changed in
        let best = -1;
        for (let c = cHi; c >= Math.max(0, cHi - 4); c--) {
          if (any & (1 << c)) {
            best = c;
            break;
          }
        }
        if (best < 0) continue;
        const age = u - CYCLE_AT(best);
        if (age < 0) continue;
        const f = Math.exp(-age * 3.5);
        if (f < 0.04) continue;
        const k = m.act[i] & (1 << best) ? 0 : m.ifr[i] & (1 << best) ? 1 : 2;
        buckets[k].push(i, f);
      }
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      const cols = [RGB.amber, RGB.cyan, [210, 220, 230]];
      buckets.forEach((b, k) => {
        for (let j = 0; j < b.length; j += 2) {
          const i = b[j], f = b[j + 1] * (1 - exit);
          const x = tx(i), y = ty(i);
          if (x < -10 || x > W + 10 || y < -10 || y > H + 10) continue;
          const r = ds * (1 + 1.6 * f);
          ctx.fillStyle = `rgba(${cols[k][0]},${cols[k][1]},${cols[k][2]},${(0.85 * f).toFixed(3)})`;
          ctx.fillRect(x - r / 2, y - r / 2, r, r);
        }
      });
      ctx.restore();
    }
    // VRB: where we came from
    const vp = 1 - seg(u, 1.0, 1.7);
    if (vp > 0) {
      const x = tx(m.vrb), y = ty(m.vrb);
      ctx.save();
      ctx.strokeStyle = hexA(C.green, vp);
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, 10 + 30 * (1 - vp), 0, TAU);
      ctx.stroke();
      ctx.font = `700 20px ${MONO}`;
      ctx.fillStyle = hexA(C.text, vp);
      ctx.fillText('VRB', x + 22, y - 16);
      ctx.restore();
    }
    ctx.save();
    ctx.globalAlpha = 1 - exit;
    counters(ctx, u);
    ctx.restore();
  },
};
