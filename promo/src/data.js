// Real data loaded at start-up: US airport dots + per-cycle change masks from
// Amend's history (prep/build_data.py), repo stats, and the app's screenshots.
export const DATA = { map: null, stats: null };
export const IMG = {};

export async function loadData() {
  DATA.map = await (await fetch('dataset/map.json')).json();
  DATA.stats = await (await fetch('dataset/stats.json')).json();
  for (const k of ['home', 'detail', 'history', 'welcome']) {
    const im = new Image();
    im.src = `../docs/screenshots/${k}.png`;
    await im.decode();
    IMG[k] = im;
  }
}
