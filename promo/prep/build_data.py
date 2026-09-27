"""Build the promo's data files from real sources.

  dataset/map.json      contiguous-US airports (OurAirports, public domain) in an Albers
                     equal-area projection, each with bitmasks of the Amend cycles in
                     which it had a change, taken from ../history/*.json
  dataset/stats.json    totals from ../history/index.json
  dataset/wordmark.json vector outlines of the "amend." wordmark, traced from the app icon

usage: python3 promo/prep/build_data.py path/to/ourairports/airports.csv
       (https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv)
"""
import csv
import glob
import json
import math
import os
import sys

import numpy as np
from PIL import Image
import contourpy

HERE = os.path.dirname(os.path.abspath(__file__))
PROMO = os.path.dirname(HERE)
REPO = os.path.dirname(PROMO)
OUT = os.path.join(PROMO, 'dataset')


def albers(lat, lon, lat1=29.5, lat2=45.5, lat0=37.5, lon0=-96.0):
    r = math.radians
    n = (math.sin(r(lat1)) + math.sin(r(lat2))) / 2
    c = math.cos(r(lat1)) ** 2 + 2 * n * math.sin(r(lat1))
    rho0 = math.sqrt(c - 2 * n * math.sin(r(lat0))) / n
    rho = math.sqrt(c - 2 * n * math.sin(r(lat))) / n
    th = n * r(lon - lon0)
    return rho * math.sin(th), rho0 - rho * math.cos(th)


def build_map(csv_path):
    idx = json.load(open(os.path.join(REPO, 'history', 'index.json')))
    cycles = idx['cycles']
    ci = {c: i for i, c in enumerate(cycles)}
    masks = {}
    for f in glob.glob(os.path.join(REPO, 'history', '*.json')):
        d = json.load(open(f))
        if 'entries' not in d:
            continue
        m = masks.setdefault(d['airport'], [0, 0, 0])
        for e in d['entries']:
            b = 1 << ci[e['cycle']]
            m[0] |= b
            if e['priority'] == 'action':
                m[1] |= b
            elif e['priority'] == 'ifr':
                m[2] |= b
    pts = []
    for r in csv.DictReader(open(csv_path, encoding='utf-8')):
        if r['iso_country'] != 'US' or r['type'] == 'closed' or not r['local_code']:
            continue
        lat, lon = float(r['latitude_deg']), float(r['longitude_deg'])
        if not (24.3 < lat < 49.6 and -125.0 < lon < -66.8):
            continue
        x, y = albers(lat, lon)
        pts.append((x, y, masks.get(r['local_code'], [0, 0, 0]), r['local_code']))
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    s = 4095 / max(x1 - x0, y1 - y0)
    out = {
        'cycles': cycles,
        'w': int(round((x1 - x0) * s)),
        'h': int(round((y1 - y0) * s)),
        # y flipped so +y is down (screen space)
        'xy': [v for p in pts for v in (int(round((p[0] - x0) * s)), int(round((y1 - p[1]) * s)))],
        'any': [p[2][0] for p in pts],
        'act': [p[2][1] for p in pts],
        'ifr': [p[2][2] for p in pts],
    }
    ids = [p[3] for p in pts]
    out['vrb'] = ids.index('VRB')
    json.dump(out, open(os.path.join(OUT, 'map.json'), 'w'), separators=(',', ':'))
    matched = sum(1 for p in pts if p[2][0])
    print(f'map: {len(pts)} CONUS airports, {matched} with Amend history, {len(cycles)} cycles')


def build_stats():
    idx = json.load(open(os.path.join(REPO, 'history', 'index.json')))
    a = idx['airports']
    ci = {c: i for i, c in enumerate(idx['cycles'])}
    per_changes = [0] * len(ci)
    per_airports = [0] * len(ci)
    per_action = [0] * len(ci)
    for f in glob.glob(os.path.join(REPO, 'history', '*.json')):
        d = json.load(open(f))
        if 'entries' not in d:
            continue
        seen = set()
        for e in d['entries']:
            i = ci[e['cycle']]
            per_changes[i] += 1
            per_action[i] += e['priority'] == 'action'
            if i not in seen:
                seen.add(i)
                per_airports[i] += 1
    stats = {
        'cycles': len(idx['cycles']),
        'first_cycle': idx['cycles'][0],
        'last_cycle': idx['cycles'][-1],
        'airports': len(a),
        'changes': sum(v['entries'] for v in a.values()),
        'action': sum(v.get('action', 0) for v in a.values()),
        'per_cycle': {'changes': per_changes, 'airports': per_airports, 'action': per_action},
        # real FAA ids for the "raw data" texture rows
        'sample_ids': sorted(a)[::53][:200],
    }
    json.dump(stats, open(os.path.join(OUT, 'stats.json'), 'w'), separators=(',', ':'))
    print('stats:', {k: v for k, v in stats.items() if k not in ('per_cycle', 'sample_ids')})


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.hypot(*ab) or 1e-9
    d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([rdp(pts[: i + 1], eps)[:-1], rdp(pts[i:], eps)])
    return np.vstack([a, b])


def simplify_loop(loop, eps):
    # closed loop: split at the point farthest from the start, simplify both halves
    loop = loop[:-1] if np.allclose(loop[0], loop[-1]) else loop
    k = int(np.argmax(np.hypot(*(loop - loop[0]).T)))
    a = rdp(loop[: k + 1], eps)
    b = rdp(np.vstack([loop[k:], loop[:1]]), eps)
    return np.vstack([a[:-1], b[:-1]])


def inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def build_wordmark():
    icon = os.path.join(REPO, 'ios', 'Amend', 'Assets.xcassets', 'AppIcon.appiconset', 'AppIcon-amend-rounded-B.png')
    im = Image.open(icon).convert('RGB')
    up = 4
    im = im.resize((im.width * up, im.height * up), Image.LANCZOS)
    a = np.asarray(im).astype(float) / 255
    white = a.min(axis=2)  # letters are near-white; the cyan dot has almost no red
    cyan = a[:, :, 2] - a[:, :, 0]
    gen = contourpy.contour_generator(z=white, line_type='Separate')
    lines = [np.asarray(l) for l in gen.lines(0.55) if len(l) > 40]
    polys = [simplify_loop(l, 0.35) for l in lines]
    outers = [p for p in polys if not any(inside(p[0], q) for q in polys if q is not p)]
    letters = []
    for o in sorted(outers, key=lambda p: p[:, 0].min()):
        holes = [p for p in polys if p is not o and inside(p[0], o)]
        letters.append({'outer': o, 'holes': holes})
    ys = np.concatenate([l['outer'][:, 1] for l in letters])
    xs = np.concatenate([l['outer'][:, 0] for l in letters])
    # baseline / x-height from the x-height letters (a, m, e, n)
    base = np.median([l['outer'][:, 1].max() for l in letters[:4]])
    xh = base - np.median([l['outer'][:, 1].min() for l in letters[:4]])
    left = xs.min()
    m = cyan > 0.35
    yy, xx = np.nonzero(m)
    dot = {'cx': float((xx.mean() - left) / xh), 'cy': float((yy.mean() - base) / xh), 'r': float(math.sqrt(m.sum() / math.pi) / xh)}
    norm = lambda p: [[round(float((x - left) / xh), 4), round(float((y - base) / xh), 4)] for x, y in p]
    out = {
        'unit': 'x-height',
        'chars': 'amend',
        'width': round(float((xs.max() - left) / xh), 4),
        'ascender': round(float((base - ys.min()) / xh), 4),
        'letters': [{'outer': norm(l['outer']), 'holes': [norm(h) for h in l['holes']]} for l in letters],
        'dot': dot,
    }
    json.dump(out, open(os.path.join(OUT, 'wordmark.json'), 'w'), separators=(',', ':'))
    print('wordmark:', len(letters), 'letters', [len(l['outer']) for l in letters], 'holes', [len(l['holes']) for l in letters], 'dot', {k: round(v, 3) for k, v in dot.items()})


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    build_map(sys.argv[1])
    build_stats()
    build_wordmark()
