// Offline renderer: drives headless Chromium frame-by-frame (deterministic clock),
// receives raw RGBA frames over a local HTTP POST and pipes them into ffmpeg.
//
//   node render.mjs video  [--from 0] [--to 900] [--jobs 3] [--out master.mkv]
//   node render.mjs frames --f 30,60,90 [--out dir]         (PNG stills)
//   node render.mjs sheet  --from 0 --to 112 --step 8 [--cols 5] [--out sheet.png]
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';
import { chromium } from 'playwright-core';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
// served from the repo root so the page can use the app's own screenshots (docs/)
const SERVE = path.dirname(ROOT);
const W = 1920, H = 1080, FPS = 60, TOTAL = 900;

const argv = process.argv.slice(2);
const mode = argv[0] || 'video';
const opt = (k, d) => {
  const i = argv.indexOf('--' + k);
  return i >= 0 ? argv[i + 1] : d;
};

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.ttf': 'font/ttf', '.json': 'application/json', '.png': 'image/png' };

function ffmpeg(args) {
  const p = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', ...args], { stdio: ['pipe', 'inherit', 'inherit'] });
  p.done = new Promise((res, rej) => p.on('close', (c) => (c === 0 ? res() : rej(new Error('ffmpeg exited ' + c)))));
  return p;
}
const write = (stream, buf) =>
  new Promise((res) => (stream.write(buf) ? res() : stream.once('drain', res)));

// One HTTP server for all workers; frames are routed to the worker's sink by id.
const sinks = new Map();
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  if (req.method === 'POST' && u.pathname === '/frame') {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', async () => {
      const buf = Buffer.concat(chunks);
      const sink = sinks.get(u.searchParams.get('job'));
      await sink(Number(u.searchParams.get('i')), buf);
      res.end('ok');
    });
    return;
  }
  const f = path.join(SERVE, decodeURIComponent(u.pathname));
  if (!f.startsWith(SERVE) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) {
    res.statusCode = 404;
    return res.end();
  }
  res.setHeader('Content-Type', MIME[path.extname(f)] || 'application/octet-stream');
  fs.createReadStream(f).pipe(res);
});

async function bundle() {
  await esbuild.build({
    entryPoints: [path.join(ROOT, 'src/main.js')],
    bundle: true,
    format: 'iife',
    platform: 'browser',
    outfile: path.join(ROOT, 'dist/bundle.js'),
    external: ['fs'],
    define: { 'process.env.NODE_ENV': '"production"' },
    logLevel: 'warning',
  });
}

async function openPage(port) {
  const browser = await chromium.launch({
    args: ['--force-color-profile=srgb', '--disable-lcd-text', '--font-render-hinting=none', '--disable-gpu-vsync', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
      // keep 2D canvases on the CPU rasteriser; only WebGL goes through SwiftShader
      '--disable-accelerated-2d-canvas'],
  });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('console', (m) => {
    const t = m.text();
    if (!t.startsWith('[progress]')) console.log('[page]', t);
  });
  page.on('pageerror', (e) => console.error('[pageerror]', e.message));
  await page.goto(`http://127.0.0.1:${port}/${path.basename(ROOT)}/index.html`);
  await page.waitForFunction(() => window.__ready === true || window.__ready === 'error', null, { timeout: 120000 });
  if ((await page.evaluate(() => window.__ready)) !== true) throw new Error('page init failed');
  return { browser, page };
}

async function renderFrames(port, job, frames, sink) {
  sinks.set(job, sink);
  const { browser, page } = await openPage(port);
  const t0 = Date.now();
  // Render in chunks so progress is visible.
  const CH = 30;
  for (let i = 0; i < frames.length; i += CH) {
    const part = frames.slice(i, i + CH);
    await page.evaluate(([fr, j]) => window.renderRange(fr, j), [part, job]);
    const done = Math.min(i + CH, frames.length);
    const el = (Date.now() - t0) / 1000;
    process.stdout.write(`[job ${job}] ${done}/${frames.length}  ${(el / done).toFixed(3)} s/frame\n`);
  }
  await browser.close();
}

await bundle();
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const raw = ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-r', String(FPS), '-i', '-'];

if (mode === 'video') {
  const from = Number(opt('from', 0)), to = Number(opt('to', TOTAL));
  const jobs = Number(opt('jobs', 3));
  const out = path.resolve(opt('out', path.join(ROOT, 'build/master.mkv')));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const span = Math.ceil((to - from) / jobs);
  const parts = [];
  await Promise.all(
    Array.from({ length: jobs }, async (_, j) => {
      const a = from + j * span, b = Math.min(to, a + span);
      if (a >= b) return;
      const file = out.replace(/\.mkv$/, `.part${j}.mkv`);
      parts[j] = file;
      const ff = ffmpeg(['-y', ...raw, '-c:v', 'libx264rgb', '-qp', '0', '-preset', 'ultrafast', file]);
      const frames = Array.from({ length: b - a }, (_, k) => a + k);
      await renderFrames(port, String(j), frames, (i, buf) => write(ff.stdin, buf));
      ff.stdin.end();
      await ff.done;
    })
  );
  const list = out + '.txt';
  fs.writeFileSync(list, parts.filter(Boolean).map((p) => `file '${p}'`).join('\n'));
  const cat = ffmpeg(['-y', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', out]);
  cat.stdin.end();
  await cat.done;
  for (const p of parts.filter(Boolean)) fs.unlinkSync(p);
  fs.unlinkSync(list);
  console.log('wrote', out);
} else if (mode === 'frames') {
  const frames = opt('f', '0').split(',').map(Number);
  const dir = path.resolve(opt('out', path.join(ROOT, 'build/frames')));
  fs.mkdirSync(dir, { recursive: true });
  await renderFrames(port, 'f', frames, async (i, buf) => {
    const ff = ffmpeg(['-y', ...raw, '-frames:v', '1', path.join(dir, `f${String(i).padStart(4, '0')}.png`)]);
    await write(ff.stdin, buf);
    ff.stdin.end();
    await ff.done;
  });
  console.log('wrote', dir);
} else if (mode === 'sheet') {
  const from = Number(opt('from', 0)), to = Number(opt('to', TOTAL)), step = Number(opt('step', 10));
  const cols = Number(opt('cols', 5));
  const frames = [];
  for (let i = from; i < to; i += step) frames.push(i);
  const rows = Math.ceil(frames.length / cols);
  const out = path.resolve(opt('out', path.join(ROOT, 'build/sheet.png')));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const tw = Number(opt('tw', 480));
  const ff = ffmpeg(['-y', ...raw, '-vf',
    `scale=${tw}:-1:flags=area,tile=${cols}x${rows}:padding=4:color=gray`,
    '-frames:v', '1', out]);
  const labels = [];
  await renderFrames(port, 's', frames, (i, buf) => { labels.push(i); return write(ff.stdin, buf); });
  ff.stdin.end();
  await ff.done;
  console.log('wrote', out, 'frames:', labels.join(','));
}
server.close();
