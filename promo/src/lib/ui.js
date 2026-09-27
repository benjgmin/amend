// The app's UI vocabulary, redrawn for video: EFB panels, annunciator lights,
// change rows with a priority bar + category icon, and a phone frame.
import { C, MONO, SANS } from '../config.js';
import { TAU } from './math.js';

export function rrect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

export function panel(ctx, x, y, w, h, s = 1, fill = C.panel) {
  rrect(ctx, x, y, w, h, 8 * s);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 1 * s;
  ctx.stroke();
}

export function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// boxed label, like an annunciator light (Theme.swift: Annunciator)
// returns its width. `lit` 0..1 adds the light-up glow.
export function annunciator(ctx, text, x, y, color, s = 1, lit = 0, alpha = 1) {
  ctx.save();
  ctx.font = `700 ${11 * s}px ${MONO}`;
  ctx.letterSpacing = `${0.6 * s}px`;
  const tw = ctx.measureText(text).width;
  const w = tw + 12 * s, h = 11 * s + 7 * s;
  ctx.globalAlpha = alpha;
  if (lit > 0) {
    ctx.shadowColor = color;
    ctx.shadowBlur = 26 * s * lit;
  }
  rrect(ctx, x, y, w, h, 3 * s);
  ctx.fillStyle = hexA(color, 0.12 + 0.22 * lit);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = hexA(color, 0.55 + 0.45 * lit);
  ctx.lineWidth = 1 * s;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x + 6 * s, y + h / 2 + 0.5 * s);
  ctx.restore();
  return w;
}

export function wrap(ctx, text, maxW) {
  const words = text.split(' ');
  const lines = [];
  let cur = '';
  for (const w of words) {
    const t = cur ? cur + ' ' + w : w;
    if (ctx.measureText(t).width > maxW && cur) {
      lines.push(cur);
      cur = w;
    } else cur = t;
  }
  if (cur) lines.push(cur);
  return lines;
}

// SF Symbol stand-ins, drawn as strokes in a size x size box centred at (x, y)
export function icon(ctx, name, x, y, size, color) {
  const s = size / 20;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 1.9;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  const arcs = (r0, n) => {
    for (let k = 0; k < n; k++) {
      const r = r0 + k * 3.6;
      ctx.beginPath();
      ctx.arc(0, 0, r, -Math.PI * 0.28, Math.PI * 0.28);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, 0, r, Math.PI * 0.72, Math.PI * 1.28);
      ctx.stroke();
    }
  };
  switch (name) {
    case 'tower':
      arcs(4.5, 2);
      ctx.beginPath();
      ctx.moveTo(0, -1);
      ctx.lineTo(0, 9);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(0, -2, 1.8, 0, TAU);
      ctx.fill();
      break;
    case 'frequency':
      arcs(4.2, 3);
      ctx.beginPath();
      ctx.arc(0, 0, 2.1, 0, TAU);
      ctx.fill();
      break;
    case 'remark':
      ctx.beginPath();
      ctx.roundRect(-8.5, -7.5, 17, 12.5, 3);
      ctx.moveTo(-3.5, 5);
      ctx.lineTo(-5.5, 8.8);
      ctx.lineTo(0.5, 5);
      ctx.stroke();
      for (const [yy, ww] of [[-3.5, 10], [-0.5, 10], [2.3, 6]]) {
        ctx.beginPath();
        ctx.moveTo(-5, yy);
        ctx.lineTo(-5 + ww, yy);
        ctx.stroke();
      }
      break;
    case 'route':
      ctx.beginPath();
      ctx.arc(-6, -6, 2.4, 0, TAU);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(6, 6, 2.4, 0, TAU);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-3.8, -5);
      ctx.bezierCurveTo(8, -5, -8, 5, 3.8, 5);
      ctx.stroke();
      break;
    case 'runway':
      ctx.beginPath();
      ctx.moveTo(-5, 9);
      ctx.lineTo(-2.5, -9);
      ctx.moveTo(5, 9);
      ctx.lineTo(2.5, -9);
      ctx.stroke();
      ctx.setLineDash([2.5, 2.5]);
      ctx.beginPath();
      ctx.moveTo(0, 8);
      ctx.lineTo(0, -8);
      ctx.stroke();
      ctx.setLineDash([]);
      break;
    case 'navaid':
      ctx.beginPath();
      ctx.arc(0, 0, 8.5, 0, TAU);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, -5.5);
      ctx.lineTo(3.4, 4);
      ctx.lineTo(0, 2.2);
      ctx.lineTo(-3.4, 4);
      ctx.closePath();
      ctx.fill();
      break;
    case 'airspace':
      ctx.setLineDash([3, 2.6]);
      ctx.beginPath();
      ctx.arc(0, 0, 8, 0, TAU);
      ctx.stroke();
      ctx.setLineDash([]);
      break;
    case 'chart':
      ctx.beginPath();
      ctx.moveTo(-6, -9);
      ctx.lineTo(3, -9);
      ctx.lineTo(7, -5);
      ctx.lineTo(7, 9);
      ctx.lineTo(-6, 9);
      ctx.closePath();
      ctx.stroke();
      break;
    default:
      ctx.beginPath();
      ctx.arc(0, 0, 8, 0, TAU);
      ctx.stroke();
  }
  ctx.restore();
}

// A change row exactly like ChangeRow.swift: priority bar, icon, summary,
// category label, optional "FAA TEXT" disclosure. Returns its height.
export function changeRow(ctx, x, y, w, row, s = 1, opts = {}) {
  const color = row.color;
  const pad = 12 * s;
  ctx.save();
  ctx.font = `400 ${15 * s}px ${SANS}`;
  const textX = x + pad + 3 * s + 30 * s;
  const lines = wrap(ctx, row.summary, w - (textX - x) - pad);
  const lineH = 19 * s;
  const origH = opts.original ? opts.original.length * 15 * s + 22 * s : 0;
  const h = pad * 2 + lines.length * lineH + 8 * s + 11 * s + origH;
  // panel with the 3pt priority bar
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, 8 * s);
  ctx.fillStyle = C.panel;
  ctx.fill();
  ctx.strokeStyle = C.line;
  ctx.lineWidth = s;
  ctx.stroke();
  ctx.save();
  ctx.clip();
  ctx.fillStyle = color;
  ctx.fillRect(x, y, 3 * s, h);
  ctx.restore();
  icon(ctx, row.icon, x + pad + 3 * s + 10 * s, y + pad + 9 * s, 17 * s, color);
  ctx.fillStyle = C.text;
  ctx.textBaseline = 'alphabetic';
  lines.forEach((l, i) => ctx.fillText(l, textX, y + pad + 14 * s + i * lineH));
  const ly = y + pad + lines.length * lineH + 8 * s + 8 * s;
  ctx.font = `600 ${9 * s}px ${MONO}`;
  ctx.letterSpacing = `${1 * s}px`;
  ctx.fillStyle = C.faint;
  ctx.fillText(row.category.toUpperCase(), textX, ly);
  if (row.more) {
    ctx.font = `700 ${11 * s}px ${MONO}`;
    ctx.letterSpacing = '0px';
    ctx.fillStyle = C.dim;
    ctx.textAlign = 'right';
    ctx.fillText(row.more, x + w - pad, ly);
    ctx.textAlign = 'left';
  }
  if (opts.original) {
    const by = ly + 10 * s;
    ctx.beginPath();
    ctx.roundRect(textX, by, w - (textX - x) - pad, origH - 12 * s, 5 * s);
    ctx.fillStyle = C.bg;
    ctx.fill();
    ctx.font = `400 ${11 * s}px ${MONO}`;
    ctx.fillStyle = hexA(C.amber, 0.85);
    opts.original.forEach((l, i) => ctx.fillText(l, textX + 10 * s, by + 17 * s + i * 15 * s));
  }
  ctx.restore();
  return h;
}

// Generic phone body around a real app screenshot. (cx, cy) centre, h height.
export function phone(ctx, img, cx, cy, h, opts = {}) {
  const ratio = img ? img.width / img.height : 0.46;
  const b = h * 0.018;
  const sh = h - 2 * b, sw = sh * ratio;
  const w = sw + 2 * b;
  const x = cx - w / 2, y = cy - h / 2;
  ctx.save();
  // soft drop shadow
  ctx.shadowColor = 'rgba(0,0,0,0.55)';
  ctx.shadowBlur = h * 0.06;
  ctx.shadowOffsetY = h * 0.025;
  rrect(ctx, x, y, w, h, w * 0.155);
  const g = ctx.createLinearGradient(x, y, x + w, y + h);
  g.addColorStop(0, '#2A2F37');
  g.addColorStop(0.5, '#15181D');
  g.addColorStop(1, '#23272E');
  ctx.fillStyle = g;
  ctx.fill();
  ctx.shadowColor = 'transparent';
  ctx.strokeStyle = 'rgba(255,255,255,0.16)';
  ctx.lineWidth = Math.max(1, h * 0.0018);
  ctx.stroke();
  // screen
  rrect(ctx, x + b, y + b, sw, sh, sw * 0.13);
  ctx.clip();
  ctx.fillStyle = C.bg;
  ctx.fillRect(x + b, y + b, sw, sh);
  if (img) ctx.drawImage(img, x + b, y + b - (opts.scroll || 0) * sh, sw, sw / ratio);
  if (opts.overlay) opts.overlay(ctx, x + b, y + b, sw, sh);
  // dynamic island
  ctx.fillStyle = '#000';
  rrect(ctx, cx - sw * 0.15, y + b + sh * 0.013, sw * 0.3, sw * 0.085, sw * 0.0425);
  ctx.fill();
  ctx.restore();
  return { x: x + b, y: y + b, w: sw, h: sh };
}

// glow text helper
export function glowText(ctx, text, x, y, color, blur) {
  ctx.save();
  ctx.shadowColor = color;
  ctx.shadowBlur = blur;
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
  ctx.restore();
  ctx.fillText(text, x, y);
}
