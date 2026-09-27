import { W, H, FPS, SCENES } from './config.js';
import { shakeAt } from './cues.js';
import { drawHud } from './hud.js';
import { post } from './post.js';
import { loadData } from './data.js';
import { loadWordmark } from './lib/wordmark.js';
import cycle from './scenes/cycle.js';
import noise from './scenes/noise.js';
import brand from './scenes/brand.js';
import remarks from './scenes/remarks.js';
import ranked from './scenes/ranked.js';
import history from './scenes/history.js';
import map from './scenes/map.js';
import end from './scenes/end.js';

const IMPL = { cycle, noise, brand, remarks, ranked, history, map, end };

const out = document.getElementById('out');
const octx = out.getContext('2d', { alpha: false, willReadFrequently: true });
const mk = (w = W, h = H) => {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
};
const scn = mk();
const sctx = scn.getContext('2d', { alpha: false });

export function sceneAt(t) {
  for (let i = SCENES.length - 1; i >= 0; i--) if (t >= SCENES[i].start) return SCENES[i];
  return SCENES[0];
}

function renderWorld(ctx, t, seg) {
  const impl = IMPL[seg.id];
  const sh = shakeAt(t);
  ctx.save();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, W, H);
  // overscan just enough that a shaken frame never exposes its edge
  const z = Math.max(1 + (2 * Math.abs(sh.x)) / W, 1 + (2 * Math.abs(sh.y)) / H) + 2.2 * Math.abs(sh.r);
  ctx.translate(W / 2 + sh.x, H / 2 + sh.y);
  ctx.rotate(sh.r);
  ctx.scale(z, z);
  ctx.translate(-W / 2, -H / 2);
  impl.render(ctx, t - seg.start, t);
  ctx.restore();
}

window.renderFrame = function (i, samplesOverride) {
  const t = i / FPS;
  const seg = sceneAt(t);
  const impl = IMPL[seg.id];
  const N = samplesOverride || (impl.samples ? impl.samples(t - seg.start) : 8);
  const shutter = 0.5; // 180 degrees
  let lo = seg.start, hi = seg.end - 1e-6;
  if (impl.bounds) {
    const [a, b] = impl.bounds(t - seg.start);
    lo = Math.max(lo, seg.start + a);
    hi = Math.min(hi, seg.start + b - 1e-6);
  }
  for (let k = 0; k < N; k++) {
    let tk = t + ((k + 0.5) / N - 0.5) * (shutter / FPS);
    tk = Math.min(hi, Math.max(lo, tk));
    renderWorld(sctx, tk, seg);
    octx.globalCompositeOperation = 'source-over';
    octx.globalAlpha = 1 / (k + 1);
    octx.drawImage(scn, 0, 0);
  }
  octx.globalAlpha = 1;
  octx.globalCompositeOperation = 'source-over';
  if (impl.hud !== false) drawHud(octx, t, seg);
  const img = octx.getImageData(0, 0, W, H);
  post(img.data, i, { ca: shakeAt(t).ca, grain: impl.grain ?? 0.03, vignette: impl.vignette ?? 0.25 });
  return img;
};

window.renderRange = async function (frames, job) {
  for (const i of frames) {
    const img = window.renderFrame(i);
    await fetch(`/frame?job=${job}&i=${i}`, { method: 'POST', body: new Blob([img.data]) });
  }
};

async function init() {
  const faces = [
    new FontFace('Geist Mono', 'url(fonts/GeistMono-VF.ttf)', { weight: '100 900' }),
    new FontFace('Inter', 'url(fonts/Inter-VF.ttf)', { weight: '100 900' }),
  ];
  for (const f of faces) {
    await f.load();
    document.fonts.add(f);
  }
  await loadData();
  await loadWordmark('dataset/wordmark.json');
  for (const s of Object.values(IMPL)) if (s.init) await s.init();
  window.__ready = true;
}
init().catch((e) => {
  console.error('init failed', e.stack || e);
  window.__ready = 'error';
});
