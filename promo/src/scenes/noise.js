// THE NOISE — a new cycle lands as a wall of raw NASR rows. Most of it is
// bookkeeping (coordinates, survey dates, pavement codes: the columns that
// amend/rules.py hides). A scan line filters it and only real changes from
// Amend's history stay lit, then they collapse into one line.
import { W, H, C, BEAT, MONO, SANS } from '../config.js';
import { seg, outExpo, inOutCubic, outCubic, inCubic, clamp01, lerp, inOutQuart } from '../lib/ease.js';
import { rng } from '../lib/math.js';
import { hexA } from '../lib/ui.js';
import { DATA } from '../data.js';

const LH = 31;
const COLS = [70, 995];
let ROWS = [];

// real changes (history/*.json), shown the way they arrive: file, id, column, old -> new
const SIGNAL = [
  { row: 11, col: 0, file: 'ATC_BASE', id: 'VRB', f: 'TWR_HRS', v: '0700-2300 → 0700-0100', c: C.amber },
  { row: 14, col: 1, file: 'APT_RWY', id: 'HOB', f: 'RWY_ID', v: '03/21 → 04/22', c: C.amber },
  { row: 17, col: 0, file: 'NAV_BASE', id: 'LOR', f: 'NDB 269', v: 'DECOMMISSIONED', c: C.amber },
  { row: 20, col: 1, file: 'CLS_ARSP', id: 'VRB', f: 'AIRSPACE_HRS', v: 'CLASS D 0700-2300 → 0700-0100', c: C.amber },
  { row: 23, col: 0, file: 'PFR_RMT_FMT', id: 'VRB', f: 'ROUTES', v: '+4 PREFERRED IFR ROUTES', c: C.cyan },
  { row: 26, col: 1, file: 'APT_RMK', id: 'VRB', f: 'REMARK', v: 'RSCD NOT MNT 2300-0600 M-F …', c: C.dim },
];

function fmt(file, id, f, v) {
  return file.padEnd(12) + id.padEnd(6) + f.padEnd(21) + v;
}

function init() {
  const r = rng(28);
  const ids = DATA.stats.sample_ids;
  const pick = (a) => a[Math.floor(r() * a.length)];
  const d2 = (n) => String(n).padStart(2, '0');
  const date = () => `20${24 + Math.floor(r() * 2)}/${d2(1 + Math.floor(r() * 12))}/${d2(1 + Math.floor(r() * 28))}`;
  const gens = [
    ['APT_BASE', 'LAT_DECIMAL', () => { const a = (25 + r() * 23).toFixed(5); return `${a} → ${(+a + 0.00001).toFixed(5)}`; }],
    ['APT_BASE', 'LONG_DECIMAL', () => { const a = (-70 - r() * 50).toFixed(5); return `${a} → ${(+a - 0.00002).toFixed(5)}`; }],
    ['APT_BASE', 'LAST_INSPECTION', () => `${date()} → ${date()}`],
    ['APT_BASE', 'ANNUAL_OPS_DATE', () => `${date()} → ${date()}`],
    ['APT_BASE', 'BASED_SINGLE_ENG', () => { const a = Math.floor(r() * 90); return `${a} → ${a + 1 + Math.floor(r() * 3)}`; }],
    ['APT_BASE', 'LOCAL_OPS', () => { const a = Math.floor(r() * 30) * 500; return `${a} → ${a + 500}`; }],
    ['APT_RWY', 'PAVEMENT_TYPE_CODE', () => pick(['ASPH-G → ASPH-F', 'CONC-G → CONC-E', 'TURF-F → TURF-G'])],
    ['APT_RWY', 'PCN', () => pick(['32/F/B/X/T → 34/F/B/X/T', '58/R/B/W/T → 60/R/B/W/T'])],
    ['APT_RWY', 'LENGTH_SOURCE_DATE', () => `${date()} → ${date()}`],
    ['APT_RWY', 'GROSS_WT_SW', () => { const a = 12 + Math.floor(r() * 60); return `${a} → ${a + 2}`; }],
    ['APT_RWY_END', 'ELEV', () => { const a = (r() * 900).toFixed(1); return `${a} → ${(+a + 0.1).toFixed(1)}`; }],
    ['APT_RWY_END', 'TIRE_PRES_CODE', () => pick(['W → X', 'X → Y'])],
    ['NAV_BASE', 'MAG_VARN', () => { const a = 1 + Math.floor(r() * 18); return `${a}W → ${a}W`; }],
    ['APT_BASE', 'EFF_DATE', () => '2026/09/03 → 2026/10/01'],
    ['APT_ATT', 'LAST_INFO_RESPONSE', () => `${date()} → ${date()}`],
    ['AWOS', 'LAT_DECIMAL', () => { const a = (25 + r() * 23).toFixed(5); return `${a} → ${(+a - 0.00001).toFixed(5)}`; }],
  ];
  ROWS = [];
  for (let i = 0; i < 400; i++) {
    const [file, f, v] = gens[Math.floor(r() * gens.length)];
    ROWS.push([fmt(file, pick(ids), f, v()), fmt(...gens[Math.floor(r() * gens.length)].slice(0, 1), pick(ids), '', '')]);
    const g2 = gens[Math.floor(r() * gens.length)];
    ROWS[i][1] = fmt(g2[0], pick(ids), g2[1], g2[2]());
  }
}

// scroll offset in px: a burst on the downbeat, settling by the filter pass
function scrollAt(u) {
  return 3600 * outCubic(seg(u, 0, 4.1)) + 45 * u;
}

function band(ctx, y, h, a) {
  const g = ctx.createLinearGradient(0, y - h, 0, y + h);
  g.addColorStop(0, hexA(C.bg, 0));
  g.addColorStop(0.3, hexA(C.bg, a));
  g.addColorStop(0.7, hexA(C.bg, a));
  g.addColorStop(1, hexA(C.bg, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, y - h, W, h * 2);
}

export default {
  init,
  samples: (lt) => (lt / BEAT < 1.5 ? 12 : 8),
  vignette: 0.35,
  render(ctx, lt) {
    const u = lt / BEAT;
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);
    const sc = scrollAt(u);
    const base = Math.floor(sc / LH);
    const off = sc - base * LH;
    const scanY = lerp(-40, H + 40, inOutCubic(seg(u, 4.2, 5.8)));
    const collapse = inOutQuart(seg(u, 7.0, 7.9));
    const appear = outExpo(seg(u, 0, 0.35));
    ctx.font = `500 18px ${MONO}`;
    ctx.letterSpacing = '0.5px';
    ctx.textBaseline = 'middle';
    // noise rows
    for (let i = -1; i < H / LH + 2; i++) {
      const y = i * LH - off + 12;
      const idx = (base + i + 4000) % ROWS.length;
      const passed = y < scanY;
      for (let c = 0; c < 2; c++) {
        if (SIGNAL.some((s) => s.row === i && s.col === c) && u > 4.15) continue;
        let a = passed ? 0.07 : 0.36 + 0.26 * (((idx * 7 + c * 13) % 10) / 10);
        a *= appear * (1 - collapse);
        if (a < 0.01) continue;
        ctx.fillStyle = `rgba(143,143,143,${a.toFixed(3)})`;
        ctx.fillText(ROWS[idx][c], COLS[c], y);
      }
    }
    // signal rows: pinned once the wall settles, lit when the scan passes
    if (u > 4.15) {
      for (const s of SIGNAL) {
        const y0 = s.row * LH - off + 12;
        const on = y0 < scanY;
        const tgtY = 540 + (SIGNAL.indexOf(s) - 2.5) * 44;
        const y = lerp(y0, lerp(tgtY, 540, inCubic(seg(u, 7.5, 7.9))), inOutCubic(seg(u, 7.0, 7.6)));
        const x = lerp(COLS[s.col], 560, inOutCubic(seg(u, 7.0, 7.6)));
        const sy = 1 - inCubic(seg(u, 7.6, 7.95));
        const big = 1 + 0.22 * outExpo(clamp01((scanY - y0) / 160)) * (on ? 1 : 0);
        ctx.save();
        ctx.translate(x, y);
        ctx.scale(big, Math.max(0.02, sy) * big);
        const txt = fmt(s.file, s.id, s.f, s.v);
        const tw = ctx.measureText(txt).width;
        if (on) {
          ctx.fillStyle = hexA(s.c, 0.1);
          ctx.fillRect(-14, -15, tw + 28, 30);
          ctx.fillStyle = s.c;
          ctx.fillRect(-14, -15, 3, 30);
          ctx.shadowColor = s.c;
          ctx.shadowBlur = 12;
        }
        ctx.fillStyle = on ? s.c : 'rgba(143,143,143,0.34)';
        ctx.fillText(txt, 0, 0);
        ctx.restore();
      }
    }
    // scan line
    if (u > 4.2 && u < 5.9) {
      ctx.save();
      ctx.fillStyle = C.cyan;
      ctx.shadowColor = C.cyan;
      ctx.shadowBlur = 18;
      ctx.fillRect(0, scanY - 1, W, 2);
      ctx.restore();
      const g = ctx.createLinearGradient(0, scanY - 120, 0, scanY);
      g.addColorStop(0, hexA(C.cyan, 0));
      g.addColorStop(1, hexA(C.cyan, 0.08));
      ctx.fillStyle = g;
      ctx.fillRect(0, scanY - 120, W, 120);
    }
    ctx.textBaseline = 'alphabetic';
    // headline copy on a soft backing band
    const h1 = outExpo(seg(u, 0.15, 0.6)) * (1 - seg(u, 3.4, 3.6));
    const h2 = outExpo(seg(u, 3.7, 4.1)) * (1 - seg(u, 6.8, 7.1));
    if (h1 > 0) band(ctx, 470, 190, 0.9 * h1);
    if (h2 > 0) band(ctx, 205, 150, 0.92 * h2);
    ctx.textAlign = 'center';
    ctx.font = `800 104px ${SANS}`;
    ctx.letterSpacing = '-2px';
    if (h1 > 0) {
      ctx.globalAlpha = h1;
      ctx.fillStyle = C.text;
      ctx.fillText('TENS OF THOUSANDS', 960, 445 + (1 - h1) * 30);
      ctx.fillText('OF ROWS CHANGE.', 960, 555 + (1 - h1) * 30);
    }
    if (h2 > 0) {
      ctx.globalAlpha = h2;
      ctx.font = `800 88px ${SANS}`;
      ctx.textAlign = 'left';
      const a = 'MOST OF IT ', b = 'IS NOISE.';
      const wa = ctx.measureText(a).width, wb = ctx.measureText(b).width;
      const x0 = 960 - (wa + wb) / 2;
      ctx.fillStyle = C.text;
      ctx.fillText(a, x0, 236 + (1 - h2) * 24);
      ctx.fillStyle = C.faint;
      ctx.fillText(b, x0 + wa, 236 + (1 - h2) * 24);
    }
    ctx.globalAlpha = 1;
    ctx.textAlign = 'left';
    ctx.letterSpacing = '0px';
  },
};
