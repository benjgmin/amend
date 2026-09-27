// The "amend." wordmark, traced from the app icon (dataset/wordmark.json, units of
// x-height). Letters can be transformed individually.
let WM = null;
let paths = null;

export async function loadWordmark(url) {
  WM = await (await fetch(url)).json();
  paths = WM.letters.map((l) => {
    const p = new Path2D();
    for (const poly of [l.outer, ...l.holes]) smoothPoly(p, poly);
    let x0 = Infinity, x1 = -Infinity;
    for (const [x] of l.outer) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
    }
    return { p, cx: (x0 + x1) / 2 };
  });
  return WM;
}

// quadratic smoothing through segment midpoints (removes trace faceting)
function smoothPoly(p, pts) {
  const n = pts.length;
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const m0 = mid(pts[n - 1], pts[0]);
  p.moveTo(m0[0], m0[1]);
  for (let i = 0; i < n; i++) {
    const a = pts[i], b = pts[(i + 1) % n];
    const m = mid(a, b);
    p.quadraticCurveTo(a[0], a[1], m[0], m[1]);
  }
  p.closePath();
}

export const wordmarkInfo = () => WM;

// draw at baseline-left (x, y) with x-height `xh`.
// per(i) -> {dx, dy, sx, sy, rot, alpha} in x-height units, optional.
export function drawWordmark(ctx, x, y, xh, { color = '#F2F2F2', dotColor = '#3DD6FF', per, dot } = {}) {
  paths.forEach((L, i) => {
    const t = per ? per(i) : null;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(xh, xh);
    if (t) {
      ctx.translate(L.cx + (t.dx || 0), t.dy || 0);
      ctx.rotate(t.rot || 0);
      ctx.scale(t.sx ?? 1, t.sy ?? 1);
      ctx.translate(-L.cx, 0);
      ctx.globalAlpha *= t.alpha ?? 1;
    }
    ctx.fillStyle = color;
    ctx.fill(L.p, 'evenodd');
    ctx.restore();
  });
  const d = WM.dot;
  const t = dot || {};
  if ((t.alpha ?? 1) > 0) {
    ctx.save();
    ctx.globalAlpha *= t.alpha ?? 1;
    ctx.fillStyle = dotColor;
    ctx.translate(x + (d.cx + (t.dx || 0)) * xh, y + (d.cy + (t.dy || 0)) * xh);
    ctx.scale(t.sx ?? 1, t.sy ?? 1);
    ctx.beginPath();
    ctx.arc(0, 0, d.r * xh * (t.s ?? 1), 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}
