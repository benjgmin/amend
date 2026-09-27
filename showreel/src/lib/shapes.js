// Contour utilities: primitive shapes as point lists, arc-length resampling and
// correspondence so any outline (glyphs included) can morph into any other.
import { TAU } from './math.js';

export function signedArea(pts) {
  let a = 0;
  for (let i = 0, n = pts.length; i < n; i++) {
    const p = pts[i], q = pts[(i + 1) % n];
    a += p[0] * q[1] - q[0] * p[1];
  }
  return a / 2;
}
export function centroid(pts) {
  let x = 0, y = 0;
  for (const p of pts) { x += p[0]; y += p[1]; }
  return [x / pts.length, y / pts.length];
}

export function resample(pts, n) {
  const m = pts.length;
  const L = new Float64Array(m + 1);
  for (let i = 0; i < m; i++) {
    const p = pts[i], q = pts[(i + 1) % m];
    L[i + 1] = L[i] + Math.hypot(q[0] - p[0], q[1] - p[1]);
  }
  const total = L[m];
  const out = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const d = (k / n) * total;
    while (j < m - 1 && L[j + 1] < d) j++;
    const p = pts[j], q = pts[(j + 1) % m];
    const seg = L[j + 1] - L[j] || 1;
    const t = (d - L[j]) / seg;
    out.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
  }
  return out;
}

// Make winding consistent (positive area in y-down == clockwise on screen).
export function orient(pts, positive = true) {
  const a = signedArea(pts);
  if ((a > 0) !== positive) return pts.slice().reverse();
  return pts;
}

// Rotate the index of `b` so its points line up with `a` (min total squared distance).
export function align(a, b, stride = 2) {
  const n = a.length;
  let best = 0, bestD = Infinity;
  for (let off = 0; off < n; off += stride) {
    let d = 0;
    for (let i = 0; i < n; i += 4) {
      const p = a[i], q = b[(i + off) % n];
      d += (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2;
    }
    if (d < bestD) { bestD = d; best = off; }
  }
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = b[(i + best) % n];
  return out;
}

export function lerpPts(a, b, t) {
  const out = new Array(a.length);
  for (let i = 0; i < a.length; i++) out[i] = [a[i][0] + (b[i][0] - a[i][0]) * t, a[i][1] + (b[i][1] - a[i][1]) * t];
  return out;
}

export function polyPath(pts, path = new Path2D()) {
  path.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) path.lineTo(pts[i][0], pts[i][1]);
  path.closePath();
  return path;
}

// ---- primitive outlines (centered at 0,0, "size" = nominal width) ----------
function poly(verts, n) {
  return resample(verts, n);
}
export function shapePts(type, size, n = 240) {
  const r = size / 2;
  switch (type) {
    case 'ring':
    case 'circle': {
      const out = [];
      for (let i = 0; i < n; i++) {
        const a = -Math.PI / 2 + (i / n) * TAU;
        out.push([Math.cos(a) * r, Math.sin(a) * r]);
      }
      return out;
    }
    case 'square':
      return poly([[-r, -r], [r, -r], [r, r], [-r, r]], n);
    case 'triangle': {
      // equilateral, visually centred (centroid slightly low)
      const h = size * 0.92;
      return poly([[0, -h * 0.6], [r * 1.02, h * 0.4], [-r * 1.02, h * 0.4]], n);
    }
    case 'semi': {
      // half disc, flat side down
      const pts = [];
      const k = 64;
      for (let i = 0; i <= k; i++) {
        const a = Math.PI + (i / k) * Math.PI;
        pts.push([Math.cos(a) * r, Math.sin(a) * r + r * 0.42]);
      }
      return poly(pts, n);
    }
    case 'quarter': {
      // quarter disc, corner bottom-left
      const pts = [[-r, r]];
      const k = 48;
      for (let i = 0; i <= k; i++) {
        const a = -Math.PI / 2 + (i / k) * (Math.PI / 2);
        pts.push([-r + Math.cos(a) * size, r + Math.sin(a) * size]);
      }
      return poly(pts, n);
    }
    case 'diamond':
      return poly([[0, -r * 1.1], [r * 1.1, 0], [0, r * 1.1], [-r * 1.1, 0]], n);
    case 'pill': {
      const pts = [];
      const k = 32, rr = r * 0.5;
      for (let i = 0; i <= k; i++) { const a = -Math.PI / 2 + (i / k) * Math.PI; pts.push([r - rr + Math.cos(a) * rr, Math.sin(a) * rr]); }
      for (let i = 0; i <= k; i++) { const a = Math.PI / 2 + (i / k) * Math.PI; pts.push([-r + rr + Math.cos(a) * rr, Math.sin(a) * rr]); }
      return poly(pts, n);
    }
    case 'plus': {
      const a = r, b = r * 0.36;
      return poly([[-b, -a], [b, -a], [b, -b], [a, -b], [a, b], [b, b], [b, a], [-b, a], [-b, b], [-a, b], [-a, -b], [-b, -b]], n);
    }
  }
  throw new Error('unknown shape ' + type);
}

export function transformPts(pts, x, y, rot = 0, sx = 1, sy = sx) {
  const c = Math.cos(rot), s = Math.sin(rot);
  const out = new Array(pts.length);
  for (let i = 0; i < pts.length; i++) {
    const px = pts[i][0] * sx, py = pts[i][1] * sy;
    out[i] = [x + px * c - py * s, y + px * s + py * c];
  }
  return out;
}

// Direct drawing of primitives (faster than point lists) ----------------------
export function drawShape(ctx, type, size) {
  const r = size / 2;
  ctx.beginPath();
  switch (type) {
    case 'circle': ctx.arc(0, 0, r, 0, TAU); break;
    case 'square': ctx.rect(-r, -r, size, size); break;
    case 'triangle': {
      const h = size * 0.92;
      ctx.moveTo(0, -h * 0.6); ctx.lineTo(r * 1.02, h * 0.4); ctx.lineTo(-r * 1.02, h * 0.4); ctx.closePath();
      break;
    }
    case 'semi': ctx.arc(0, r * 0.42, r, Math.PI, TAU); ctx.closePath(); break;
    case 'quarter': ctx.moveTo(-r, r); ctx.arc(-r, r, size, -Math.PI / 2, 0); ctx.closePath(); break;
    case 'diamond': ctx.moveTo(0, -r * 1.1); ctx.lineTo(r * 1.1, 0); ctx.lineTo(0, r * 1.1); ctx.lineTo(-r * 1.1, 0); ctx.closePath(); break;
    case 'ring': ctx.arc(0, 0, r, 0, TAU); ctx.moveTo(r * 0.52, 0); ctx.arc(0, 0, r * 0.52, 0, TAU, true); break;
    case 'plus': {
      const a = r, b = r * 0.36;
      ctx.moveTo(-b, -a); ctx.lineTo(b, -a); ctx.lineTo(b, -b); ctx.lineTo(a, -b); ctx.lineTo(a, b); ctx.lineTo(b, b);
      ctx.lineTo(b, a); ctx.lineTo(-b, a); ctx.lineTo(-b, b); ctx.lineTo(-a, b); ctx.lineTo(-a, -b); ctx.lineTo(-b, -b);
      ctx.closePath();
      break;
    }
  }
}
