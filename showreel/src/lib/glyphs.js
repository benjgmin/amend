// Variable-font glyph outlines via fontkit, so type can be animated on any axis
// (weight / width) continuously, stroked, morphed and split per letter.
import * as fontkit from 'fontkit';

const fonts = {};
export async function loadFont(name, url) {
  const buf = await (await fetch(url)).arrayBuffer();
  fonts[name] = fontkit.create(new Uint8Array(buf));
  return fonts[name];
}

const varCache = new Map();
function variation(name, wght, wdth) {
  const f = fonts[name];
  const kw = Math.round(wght * 2) / 2;
  const kd = Math.round(wdth * 4) / 4;
  const key = name + '|' + kw + '|' + kd;
  let v = varCache.get(key);
  if (!v) {
    v = f.getVariation({ wght: kw, wdth: kd });
    if (varCache.size > 4000) varCache.clear();
    varCache.set(key, v);
  }
  return v;
}


// Build a Path2D from fontkit commands scaled by s, y flipped, offset (ox, oy).
export function cmdsToPath(cmds, s, ox = 0, oy = 0, path = new Path2D()) {
  for (const c of cmds) {
    const a = c.args;
    switch (c.command) {
      case 'moveTo': path.moveTo(ox + a[0] * s, oy - a[1] * s); break;
      case 'lineTo': path.lineTo(ox + a[0] * s, oy - a[1] * s); break;
      case 'quadraticCurveTo': path.quadraticCurveTo(ox + a[0] * s, oy - a[1] * s, ox + a[2] * s, oy - a[3] * s); break;
      case 'bezierCurveTo':
        path.bezierCurveTo(ox + a[0] * s, oy - a[1] * s, ox + a[2] * s, oy - a[3] * s, ox + a[4] * s, oy - a[5] * s);
        break;
      case 'closePath': path.closePath(); break;
    }
  }
  return path;
}

// Flatten fontkit commands into polygon contours (arrays of [x,y]) in px, y-down.
export function cmdsToContours(cmds, s, ox = 0, oy = 0, steps = 10) {
  const contours = [];
  let cur = null, px = 0, py = 0;
  for (const c of cmds) {
    const a = c.args;
    if (c.command === 'moveTo') {
      if (cur && cur.length > 2) contours.push(cur);
      px = ox + a[0] * s; py = oy - a[1] * s;
      cur = [[px, py]];
    } else if (c.command === 'lineTo') {
      px = ox + a[0] * s; py = oy - a[1] * s;
      cur.push([px, py]);
    } else if (c.command === 'quadraticCurveTo') {
      const cx = ox + a[0] * s, cy = oy - a[1] * s, x = ox + a[2] * s, y = oy - a[3] * s;
      for (let i = 1; i <= steps; i++) {
        const t = i / steps, u = 1 - t;
        cur.push([u * u * px + 2 * u * t * cx + t * t * x, u * u * py + 2 * u * t * cy + t * t * y]);
      }
      px = x; py = y;
    } else if (c.command === 'bezierCurveTo') {
      const c1x = ox + a[0] * s, c1y = oy - a[1] * s, c2x = ox + a[2] * s, c2y = oy - a[3] * s;
      const x = ox + a[4] * s, y = oy - a[5] * s;
      for (let i = 1; i <= steps; i++) {
        const t = i / steps, u = 1 - t;
        cur.push([
          u * u * u * px + 3 * u * u * t * c1x + 3 * u * t * t * c2x + t * t * t * x,
          u * u * u * py + 3 * u * u * t * c1y + 3 * u * t * t * c2y + t * t * t * y,
        ]);
      }
      px = x; py = y;
    } else if (c.command === 'closePath') {
      if (cur && cur.length > 2) contours.push(cur);
      cur = null;
    }
  }
  if (cur && cur.length > 2) contours.push(cur);
  return contours;
}

// Lay out a string. Returns per-glyph records with x offsets (px) relative to the
// string origin (left edge, baseline), plus the font metrics at that size.
export function layout(name, text, { size = 100, wght = 700, wdth = 100, tracking = 0 } = {}) {
  const v = variation(name, wght, wdth);
  const run = v.layout(text);
  const s = size / v.unitsPerEm;
  const glyphs = [];
  let x = 0;
  for (let i = 0; i < run.glyphs.length; i++) {
    const g = run.glyphs[i];
    const pos = run.positions[i];
    const d = { cmds: g.path.commands, bbox: g.bbox }; // fontkit caches these per instance
    const adv = pos.xAdvance * s;
    glyphs.push({
      char: text[i],
      x: x + pos.xOffset * s,
      adv,
      s,
      cmds: d.cmds,
      bbox: { x0: d.bbox.minX * s, x1: d.bbox.maxX * s, y0: -d.bbox.maxY * s, y1: -d.bbox.minY * s },
    });
    x += adv + tracking;
  }
  const width = glyphs.length ? x - tracking : 0;
  return { glyphs, width, capHeight: v.capHeight * s, ascent: v.ascent * s, descent: v.descent * s, s };
}

// Convenience: draw a laid-out string with its left/baseline origin at (x,y).
export function glyphPath(g, x, y) {
  return cmdsToPath(g.cmds, g.s, x + g.x, y);
}
