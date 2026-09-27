"""Procedural soundtrack for the Amend promo: 128 BPM, 16 bars (exactly 30 s).

B minor, tuned so B5 is exactly 1020 Hz, the tone VORs and NDBs key their
morse idents on, so the "AMEND" ident at the end sits in key with the track.
Everything is synthesised from oscillators + noise and placed on the same beat
grid the picture is animated to: day ticks on the cycle dial, the data flood
and its filter pass, a ping for every real change that survives it, cockpit
annunciator chimes, the tower-hours dial, one blip per FAA cycle on the map.

    python3 audio/synth.py out.wav
"""
import sys
import wave

import numpy as np
import scipy.signal as ss

SR = 48000
BPM = 128
BEAT = 60 / BPM
DUR = 30.0
N = int(round(DUR * SR))
rng = np.random.default_rng(7)


def bt(b):
    return b * BEAT


def tt(n):
    return np.arange(n) / SR


def ns(sec):
    return max(1, int(round(sec * SR)))


# ---------------------------------------------------------------- buses
class Bus:
    def __init__(self):
        self.x = np.zeros((2, N + SR * 4))

    def add(self, sig, t, gain=1.0, pan=0.0):
        sig = np.asarray(sig, dtype=float)
        if sig.ndim == 1:
            a = (pan + 1) * np.pi / 4
            sig = np.vstack([sig * np.cos(a), sig * np.sin(a)]) * np.sqrt(2)
        i0 = int(round(t * SR))
        if i0 < 0:
            sig = sig[:, -i0:]
            i0 = 0
        n = min(sig.shape[1], self.x.shape[1] - i0)
        if n > 0:
            self.x[:, i0:i0 + n] += sig[:, :n] * gain


drums, bass, music, fx, verb = Bus(), Bus(), Bus(), Bus(), Bus()


# ---------------------------------------------------------------- dsp helpers
def noise(n):
    return rng.standard_normal(n)


def lp(x, fc, order=2):
    return ss.sosfilt(ss.butter(order, min(fc, SR * 0.45), 'low', fs=SR, output='sos'), x)


def hp(x, fc, order=2):
    return ss.sosfilt(ss.butter(order, fc, 'high', fs=SR, output='sos'), x)


def bp(x, f1, f2, order=2):
    return ss.sosfilt(ss.butter(order, [f1, min(f2, SR * 0.45)], 'band', fs=SR, output='sos'), x)


def phase(f, n):
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    return np.cumsum(f) / SR


def sine(f, n, ph=0.0):
    return np.sin(2 * np.pi * phase(f, n) + ph)


def saw(f, n, ph0=0.0):
    # polyBLEP band-limited saw
    f = np.broadcast_to(np.asarray(f, dtype=float), (n,))
    dt = f / SR
    p = (np.cumsum(dt) + ph0) % 1.0
    y = 2 * p - 1
    m = p < dt
    t = p[m] / dt[m]
    y[m] -= t + t - t * t - 1
    m = p > 1 - dt
    t = (p[m] - 1) / dt[m]
    y[m] -= t * t + t + t + 1
    return y


def svf(x, fc, q=0.7, mode='lp'):
    """Per-sample TPT state-variable filter with a time-varying cutoff."""
    fc = np.broadcast_to(np.asarray(fc, dtype=float), x.shape)
    g = np.tan(np.pi * np.clip(fc, 20, SR * 0.45) / SR)
    k = 1 / q
    ic1 = ic2 = 0.0
    out = np.empty_like(x)
    for i in range(len(x)):
        gi = g[i]
        a1 = 1 / (1 + gi * (gi + k))
        v3 = x[i] - ic2
        v1 = a1 * ic1 + gi * a1 * v3
        v2 = ic2 + gi * v1
        ic1 = 2 * v1 - ic1
        ic2 = 2 * v2 - ic2
        out[i] = v2 if mode == 'lp' else v1 if mode == 'bp' else x[i] - k * v1 - v2
    return out


def env(n, a=0.002, d=0.2, curve=1.0):
    t = tt(n)
    e = np.exp(-np.maximum(t - a, 0) / d) ** curve
    if a > 0:
        e *= np.clip(t / a, 0, 1)
    return e


def fade(x, fin=0.002, fout=0.01):
    n = x.shape[-1]
    a, b = ns(fin), ns(fout)
    w = np.ones(n)
    w[:a] = np.linspace(0, 1, a)
    w[-b:] *= np.linspace(1, 0, b)
    return x * w


def midi(m):
    return 440 * 2 ** ((m - 69) / 12)


# ---------------------------------------------------------------- instruments
def kick(dur=0.42, f0=160, f1=48, pd=0.04, ad=0.24, click=0.6, drive=1.8):
    n = ns(dur)
    t = tt(n)
    f = f1 + (f0 - f1) * np.exp(-t / pd)
    body = np.sin(2 * np.pi * phase(f, n)) * env(n, 0.0015, ad)
    body = np.tanh(body * drive) / np.tanh(drive)
    clk = hp(noise(n), 1800) * np.exp(-t / 0.0035) * click
    return fade(body + clk, 0.0005, 0.02)


def sub_boom(dur=2.6, f0=62, f1=31):
    n = ns(dur)
    t = tt(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.35)
    y = np.sin(2 * np.pi * phase(f, n)) * env(n, 0.003, 0.9)
    return fade(np.tanh(y * 2.2) * 0.9, 0.001, 0.2)


def clap(dur=0.4):
    n = ns(dur)
    t = tt(n)
    src = bp(noise(n), 900, 2600)
    e = np.zeros(n)
    for k, o in enumerate([0, 0.011, 0.021, 0.031]):
        e += np.exp(-np.maximum(t - o, 0) / (0.006 if k < 3 else 0.12)) * (t >= o)
    return fade(src * e * 0.9, 0.0005, 0.03)


_hat_osc = None


def hat(open_=False):
    global _hat_osc
    dur = 0.28 if open_ else 0.07
    n = ns(dur)
    if _hat_osc is None:
        m = ns(0.3)
        fr = np.array([205.3, 304.4, 369.6, 522.7, 540.0, 800.0]) * 1.72
        _hat_osc = sum(np.sign(np.sin(2 * np.pi * f * tt(m))) for f in fr)
        _hat_osc = lp(hp(bp(_hat_osc + noise(m) * 1.5, 6500, 14000), 7000), 11000)
    y = _hat_osc[:n] * env(n, 0.0005, 0.09 if open_ else 0.018)
    return fade(y * 0.1, 0.0003, 0.01)


def tick(f=2600, dur=0.05, d=0.012):
    n = ns(dur)
    return fade(np.sin(2 * np.pi * f * tt(n)) * env(n, 0.0005, d) + hp(noise(n), 3000) * env(n, 0, 0.002) * 0.3)


def pluck(f, dur=0.35, d=0.12, bright=1.0):
    n = ns(dur)
    t = tt(n)
    y = np.sin(2 * np.pi * f * t) * env(n, 0.001, d)
    y += 0.35 * bright * np.sin(2 * np.pi * 2 * f * t) * env(n, 0.001, d * 0.5)
    y += 0.12 * bright * np.sin(2 * np.pi * 4.01 * f * t) * env(n, 0.001, d * 0.25)
    return fade(y)


def marimba(f, dur=0.5):
    n = ns(dur)
    t = tt(n)
    y = np.sin(2 * np.pi * f * t) * env(n, 0.001, 0.16)
    y += 0.4 * np.sin(2 * np.pi * 3.93 * f * t) * env(n, 0.0005, 0.025)
    y += 0.12 * np.sin(2 * np.pi * 9.2 * f * t) * env(n, 0.0005, 0.008)
    return fade(y)


def whoosh(dur, f0, f1, q=1.2, peak=0.6, gain=1.0):
    n = ns(dur)
    x = noise(n)
    f = f0 * (f1 / f0) ** np.linspace(0, 1, n)
    y = svf(x, f, q, 'bp')
    ph = np.linspace(0, 1, n)
    e = np.where(ph < peak, (ph / peak) ** 2, ((1 - ph) / (1 - peak)) ** 1.5)
    return fade(y * e * gain * 0.7, 0.002, 0.02)


def riser(dur, f0=300, f1=9000, tone=True):
    n = ns(dur)
    ph = np.linspace(0, 1, n)
    f = f0 * (f1 / f0) ** (ph ** 1.4)
    f = np.minimum(f, 7500)
    y = lp(svf(noise(n), f, 2.0, 'bp'), 9000) * 0.8
    if tone:
        y += 0.25 * saw(180 * (6 ** (ph ** 1.6)), n) * ph
    return fade(y * ph ** 2.2, 0.01, 0.003)


def rev_cymbal(dur):
    n = ns(dur)
    ph = np.linspace(0, 1, n)
    y = lp(hp(noise(n), 4500), 10000) * (ph ** 3.2)
    return fade(y * 0.5, 0.01, 0.002)


def crash(dur=2.2):
    n = ns(dur)
    y = hp(noise(n), 2800) * env(n, 0.001, 0.55)
    y += hp(noise(n), 7000) * env(n, 0.001, 0.12) * 0.4
    return fade(lp(y, 11000) * 0.36, 0.001, 0.3)




def bloop(f0=900, f1=190, dur=0.3, gain=1.0):
    n = ns(dur)
    t = tt(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.035)
    y = np.sin(2 * np.pi * phase(f, n)) * env(n, 0.002, 0.08)
    y += 0.2 * np.sin(2 * np.pi * phase(f * 1.5, n)) * env(n, 0.002, 0.04)
    return fade(y * gain)



def chord_saws(freqs, n, detune=(-9, -3, 3, 9), seed=0):
    r = np.random.default_rng(seed)
    L = np.zeros(n)
    R = np.zeros(n)
    for f in freqs:
        for k, c in enumerate(detune):
            ff = f * 2 ** (c / 1200)
            s = saw(ff, n, r.random())
            if k % 2:
                L += s
            else:
                R += s
    return L / len(freqs), R / len(freqs)


def stab(freqs, dur=0.34, cutoff=(5200, 1000), d=0.18, seed=1):
    n = ns(dur)
    L, R = chord_saws(freqs, n, seed=seed)
    fc = cutoff[1] + (cutoff[0] - cutoff[1]) * np.exp(-tt(n) / 0.07)
    e = env(n, 0.002, d)
    return fade(np.vstack([svf(L, fc, 0.9), svf(R, fc, 0.9)]) * e * 0.5)


def pad(freqs, dur, fc0=500, fc1=2400, a=0.6, seed=3):
    n = ns(dur)
    L, R = chord_saws(freqs, n, detune=(-12, -5, 5, 12), seed=seed)
    ph = np.linspace(0, 1, n)
    fc = fc0 + (fc1 - fc0) * ph
    e = np.clip(tt(n) / a, 0, 1) * np.clip((dur - tt(n)) / 0.25, 0, 1)
    return np.vstack([svf(L, fc, 0.8), svf(R, fc, 0.8)]) * e * 0.35


def bass_note(f, dur, gain=1.0):
    n = ns(dur)
    t = tt(n)
    x = saw(f, n) * 0.7 + np.sign(np.sin(2 * np.pi * f / 2 * t)) * 0.25
    fc = 260 + 2300 * np.exp(-t / 0.05)
    y = svf(x, fc, 1.1) * env(n, 0.002, 0.16)
    y = np.tanh(y * 1.6)
    sub = np.sin(2 * np.pi * f / 2 * t) * env(n, 0.004, 0.2) * 0.4
    return fade((y * 0.8 + sub) * gain, 0.001, 0.01)


# ---------------------------------------------------------------- tuning / harmony
TUNE = 1020 / midi(83)  # B5 -> 1020 Hz (navaid ident tone)


def note(m):
    return midi(m) * TUNE


CH = {
    'Bm': [note(m) for m in (59, 62, 66, 69, 73)],  # B D F# A C#  (Bm9)
    'G': [note(m) for m in (55, 59, 62, 66, 69)],  # G B D F# A   (Gmaj9)
    'D': [note(m) for m in (62, 66, 69, 73, 76)],  # D F# A C# E
    'A': [note(m) for m in (57, 61, 64, 67, 71)],  # A C# E G B   (A9)
}
ROOT = {'Bm': note(35), 'G': note(31), 'D': note(38), 'A': note(33)}
SCALE = [note(m) for m in (71, 74, 76, 78, 81, 83, 86, 88, 90, 93, 95)]  # B minor pentatonic


def ident(dur):
    """a clean 1020 Hz ident tone with soft edges"""
    n = ns(dur)
    y = np.sin(2 * np.pi * 1020 * tt(n))
    return fade(y, 0.004, 0.006)


def chime(freqs, dur=0.9, bright=1.0):
    """bell-ish cockpit chime (stacked partials, fast attack)"""
    n = ns(dur)
    t = tt(n)
    y = np.zeros(n)
    for f in freqs:
        y += np.sin(2 * np.pi * f * t) * env(n, 0.002, 0.35)
        y += 0.35 * bright * np.sin(2 * np.pi * f * 2.76 * t) * env(n, 0.001, 0.08)
        y += 0.15 * bright * np.sin(2 * np.pi * f * 5.4 * t) * env(n, 0.001, 0.03)
    return fade(y / len(freqs))


def blip(f, dur=0.06, d=0.02, square=False):
    n = ns(dur)
    t = tt(n)
    y = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 if square else np.sin(2 * np.pi * f * t)
    return fade(lp(y, 6000) * env(n, 0.0008, d))


def glide(f0, f1, dur, d=0.2):
    n = ns(dur)
    f = f0 * (f1 / f0) ** np.linspace(0, 1, n)
    y = np.sin(2 * np.pi * phase(f, n)) + 0.3 * np.sin(2 * np.pi * phase(f * 2, n))
    return fade(y * env(n, 0.004, d))


# ---- picture timings mirrored from src/scenes (beats from each scene start)
SCENE = {'cycle': 0, 'noise': 8, 'brand': 16, 'remarks': 22, 'ranked': 32, 'history': 40, 'map': 48, 'end': 56}
TICK_AT = [0.3 + k * 0.233 for k in range(28)]  # cycle.js


def in_out_cubic(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def out_cubic(t):
    return 1 - (1 - t) ** 3


def seg(u, a, b):
    return min(1.0, max(0.0, (u - a) / (b - a)))


def signal_row_on(row):
    """noise.js: beat at which the scan line passes a pinned signal row"""
    u = 4.2
    while u < 6.0:
        sc = 3600 * out_cubic(seg(u, 0, 4.1)) + 45 * u
        off = sc - np.floor(sc / 31) * 31
        y0 = row * 31 - off + 12
        scan = -40 + (1080 + 80) * in_out_cubic(seg(u, 4.2, 5.8))
        if y0 < scan:
            return u
        u += 0.002
    return 5.9


SIGNAL = [(11, 'act'), (14, 'act'), (17, 'act'), (20, 'act'), (23, 'ifr'), (26, 'fyi')]
REMARK_T0 = [1.6, 2.05, 2.45, 2.85, 3.25, 3.65]  # remarks.js
LEGEND_T0 = [0.25, 1.65, 3.05, 4.45]  # ranked.js
TOWER_T0 = [1.8, 3.8]  # history.js
CYCLE_AT = [1.3 + c * 0.19 for c in range(27)]  # map.js
MORSE_UNIT, MORSE_T0 = 0.075, 0.5  # end.js (seconds)
MORSE = ['.-', '--', '.', '-.', '-..']


def S(scene, beat=0.0):
    return bt(SCENE[scene] + beat)


# ================================================================= SCORE
kicks = []


def K(t, g=1.0, **kw):
    drums.add(kick(**kw), t, 0.7 * g)
    kicks.append((t, g))


def chord_of(beat):
    return ['Bm', 'G', 'D', 'A'][int(beat // 4) % 4]


GROOVE = [(8, 16), (22, 56)]  # the wordmark gets a breakdown in between
grooving = lambda b: any(a <= b < z for a, z in GROOVE)

# ---- drums, bass, pads, arp over the whole 16 bars ----------------------------
for beat in range(64):
    ch = chord_of(beat)
    if grooving(beat):
        K(bt(beat))
        if beat % 4 in (1, 3):
            drums.add(clap(), bt(beat), 0.4)
            verb.add(clap(), bt(beat), 0.12)
        for s16 in range(4):
            acc = [0.5, 0.2, 0.8, 0.25][s16]
            drums.add(hat(), bt(beat + s16 * 0.25), acc * 0.85, pan=0.25)
        drums.add(hat(True), bt(beat + 0.5), 0.3, pan=-0.2)
        r = ROOT[ch]
        for off, mult, g in ((0.5, 1, 1.0), (0.75, 2, 0.6)):
            bass.add(bass_note(r * mult * 2, bt(0.22), g), bt(beat + off), 0.85)
    elif 4 <= beat < 8 or 16 <= beat < 22:  # quiet 8ths in the intro's 2nd bar + breakdown
        for e in (0, 0.5):
            drums.add(hat(), bt(beat + e), 0.35 if e else 0.2, pan=0.25)
    if beat % 4 == 0 and beat < 56:
        music.add(pad(CH[ch], bt(4), 450 if grooving(beat) else 300, 1300, a=0.4, seed=beat), bt(beat), 0.3)
    if 32 <= beat < 56:  # plucked 16th arp from the ranked shot on
        notes = sorted(CH[ch])
        for s16 in range(4):
            k = (beat * 4 + s16) % 8
            f = notes[[0, 2, 4, 3, 1, 3, 2, 4][k]] * 2
            music.add(pluck(f, 0.25, 0.07, 0.6), bt(beat + s16 * 0.25), 0.07 + 0.03 * (s16 == 0))

# ---- cycle dial (beats 0-8) ----------------------------------------------------
for k, u in enumerate(TICK_AT):
    fx.add(tick(1500 + k * 45, 0.04, 0.006), S('cycle', u), 0.22 + 0.2 * k / 27, pan=np.sin(k * 0.9) * 0.4)
    if k % 7 == 0:
        fx.add(blip(note(83 + [0, 3, 7, 10][k // 7]), 0.12, 0.04), S('cycle', u), 0.12)
fx.add(chime([note(83), note(90)], 1.4), S('cycle', TICK_AT[-1]), 0.35)  # cycle complete
verb.add(chime([note(83), note(90)], 1.4), S('cycle', TICK_AT[-1]), 0.35)
fx.add(riser(bt(3.6), 200, 7000), S('cycle', 4.4), 0.28)
fx.add(rev_cymbal(bt(0.9)), S('cycle', 7.1), 0.5)

# ---- the flood + the filter (beats 8-16) ----------------------------------------
drums.add(sub_boom(1.8, 58, 30), S('noise'), 0.55)
fx.add(whoosh(bt(1.2), 9000, 700, 0.9, 0.08, 1.4), S('noise'), 0.7)  # data rush
fx.add(crash(2.0), S('noise'), 0.35)
rr = np.random.default_rng(3)
for k in range(70):  # machine chatter under the wall of rows
    u = float(rr.uniform(0.05, 3.6))
    f = float(rr.choice([1200, 1600, 2000, 2400, 3200]))
    fx.add(blip(f, 0.05, 0.012, square=True), S('noise', u), 0.05 * (1 - u / 4.4), pan=float(rr.uniform(-0.8, 0.8)))
fx.add(whoosh(bt(1.7), 5000, 300, 1.5, 0.6, 1.0), S('noise', 4.2), 0.45)  # the scan pass
for row, kind in SIGNAL:
    u = signal_row_on(row)
    if kind == 'act':
        c = chime([note(83), note(78)], 0.6, 0.6)
    elif kind == 'ifr':
        c = chime([note(86)], 0.6, 0.5)
    else:
        c = blip(note(71), 0.2, 0.05)
    fx.add(c, S('noise', u), 0.3, pan=-0.3 if row % 2 else 0.3)
fx.add(rev_cymbal(bt(0.9)), S('noise', 7.1), 0.55)
fx.add(whoosh(bt(0.9), 300, 3000, 1.2, 0.85, 1.0), S('noise', 7.0), 0.4)  # rows collapse

# ---- the wordmark: breakdown (beats 16-22) ---------------------------------------
drums.add(sub_boom(2.4, 62, 31), S('brand'), 0.6)
for i, m in enumerate([71, 74, 78, 81, 83]):  # letters spring up
    fx.add(marimba(note(m), 0.45), S('brand', 0.03 + i * 0.07 + 0.12), 0.35, pan=-0.5 + i * 0.25)
    verb.add(marimba(note(m), 0.45), S('brand', 0.03 + i * 0.07 + 0.12), 0.18)
fx.add(chime([note(95)], 1.6, 0.8), S('brand', 0.62), 0.45)  # the dot lands
verb.add(chime([note(95)], 1.6, 0.8), S('brand', 0.62), 0.4)
fx.add(bloop(700, 240, 0.2, 0.6), S('brand', 0.62), 0.35)
music.add(pad(CH['G'], bt(5.5), 700, 2600, a=1.2, seed=21), S('brand', 0.5), 0.4)
for s16 in range(8):  # build back into the groove
    drums.add(clap(0.15), S('brand', 4.0 + s16 * 0.25), 0.08 + 0.3 * s16 / 7)
fx.add(riser(bt(2.0), 300, 9000), S('brand', 4.0), 0.3)

# ---- remarks decode (beats 22-32) -----------------------------------------------
drums.add(sub_boom(1.2, 58, 32), S('remarks'), 0.35)
for k in range(20):  # FAA text typing in
    fx.add(tick(3600, 0.03, 0.004), S('remarks', k * 0.06), 0.14, pan=-0.4 + k * 0.04)
for u, m in zip(REMARK_T0, [78, 81, 83, 86, 88, 90]):
    fx.add(glide(note(m) * 0.94, note(m), 0.16, 0.08), S('remarks', u + 0.15), 0.18)
fx.add(whoosh(bt(0.8), 600, 3000, 1.4, 0.6, 1.0), S('remarks', 5.9), 0.35)  # folds into the card
fx.add(tick(900, 0.05, 0.02), S('remarks', 6.5), 0.35)

# ---- the annunciators (beats 32-40) ---------------------------------------------
fx.add(whoosh(bt(0.9), 250, 2500, 1.1, 0.7, 1.0), S('ranked'), 0.3)  # phone rises
fx.add(chime([note(83), note(78)], 1.0, 1.0), S('ranked', LEGEND_T0[0]), 0.5)  # ACT: two-tone caution
fx.add(chime([note(90)], 0.9, 0.7), S('ranked', LEGEND_T0[1]), 0.35)  # IFR: advisory
fx.add(blip(note(71), 0.15, 0.04), S('ranked', LEGEND_T0[2]), 0.3)  # FYI
fx.add(glide(note(78), note(83), 0.3, 0.18), S('ranked', LEGEND_T0[3]), 0.3)  # NO CHG: all good
for u in LEGEND_T0:
    fx.add(tick(2400, 0.03, 0.004), S('ranked', u), 0.25)

# ---- VRB tower hours (beats 40-48) ----------------------------------------------
fx.add(whoosh(bt(0.9), 300, 2200, 1.3, 0.8, 1.0), S('history'), 0.3)  # dial draws
for u, m0, m1 in ((TOWER_T0[0], 74, 78), (TOWER_T0[1], 78, 83)):  # arc extends: that's the change
    fx.add(glide(note(m0), note(m1), bt(0.5), 0.3), S('history', u), 0.32)
    fx.add(chime([note(83), note(78)], 0.7, 0.7), S('history', u + 0.5), 0.25)
fx.add(rev_cymbal(bt(0.7)), S('history', 7.3), 0.45)

# ---- every airport, every cycle (beats 48-56) -----------------------------------
fx.add(whoosh(bt(1.4), 4000, 250, 1.0, 0.25, 1.2), S('map'), 0.55)  # pull out of VRB
for c, u in enumerate(CYCLE_AT):
    f = SCALE[c % len(SCALE)] * (2 if c >= len(SCALE) * 2 else 1)
    fx.add(blip(f, 0.08, 0.025), S('map', u), 0.1 + 0.08 * c / 26, pan=-0.6 + 1.2 * c / 26)
fx.add(chime([note(83), note(86), note(90)], 1.2, 0.6), S('map', 6.4), 0.35)  # airports total
fx.add(riser(bt(1.2), 400, 8000, tone=False), S('map', 6.8), 0.3)

# ---- end card + ident (beats 56-64) ---------------------------------------------
K(S('end'), 1.0, f0=150, ad=0.5)
drums.add(sub_boom(3.2, 62, 30), S('end'), 0.7)
music.add(crash(3.0), S('end'), 0.5)
big = stab(CH['Bm'], 3.6, (5000, 700), 1.2, seed=31)
music.add(big, S('end'), 0.55)
verb.add(big, S('end'), 0.6)
music.add(pad(CH['Bm'], bt(8), 1400, 500, a=0.05, seed=32), S('end'), 0.45)
fx.add(whoosh(bt(0.9), 250, 2400, 1.1, 0.7, 1.0), S('end'), 0.3)  # phone rises
for i, m in enumerate([71, 74, 78, 81, 83]):
    fx.add(marimba(note(m), 0.4), S('end', 0.08 + i * 0.06 + 0.1), 0.22)
fx.add(chime([note(95)], 1.4, 0.8), S('end', 0.6), 0.3)
t = 0
for code in MORSE:  # "AMEND" keyed like a navaid ident, in sync with the dots on screen
    for sym in code:
        n_ = 1 if sym == '.' else 3
        fx.add(ident(n_ * MORSE_UNIT), S('end') + MORSE_T0 + t * MORSE_UNIT, 0.22)
        t += n_ + 1
    t += 2

# ================================================================= MIX
def sidechain(depth, rel):
    g = np.ones(drums.x.shape[1])
    for t0, a in kicks:
        i = int(t0 * SR)
        n = ns(0.45)
        d = 1 - depth * a * np.exp(-tt(n) / rel)
        seg_ = g[i:i + n]
        g[i:i + n] = np.minimum(seg_, d[: len(seg_)])
    return g


sc_b = sidechain(0.75, 0.09)
sc_m = sidechain(0.5, 0.12)
ir_n = ns(1.6)
ir = np.vstack([noise(ir_n), noise(ir_n)]) * np.exp(-tt(ir_n) / 0.3)
ir[:, : ns(0.012)] = 0
ir = np.vstack([lp(ir[0], 5000), lp(ir[1], 5000)])
ir /= np.abs(ir).sum(axis=1, keepdims=True) ** 0.5 * 12
wet = np.vstack([ss.fftconvolve(verb.x[c], ir[c])[: verb.x.shape[1]] for c in range(2)])
wet = hp(wet, 250)

mix = drums.x * 0.9 + bass.x * sc_b * 0.8 + music.x * sc_m * 2.0 + fx.x * 0.95 + wet * 1.0
mix = mix - 0.3 * np.vstack([hp(mix[0], 9000), hp(mix[1], 9000)])
mix = mix[:, :N]
mix = np.vstack([hp(mix[0], 28), hp(mix[1], 28)])
drive = 1.2
mix = np.tanh(mix * drive / max(1e-9, np.percentile(np.abs(mix), 99.97))) / np.tanh(drive)
mix *= 0.84 / np.abs(mix).max()
mix = fade(mix, 0.002, 0.6)

out = sys.argv[1] if len(sys.argv) > 1 else 'soundtrack.wav'
pcm = (np.clip(mix.T, -1, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print('wrote', out, f'{mix.shape[1] / SR:.3f}s')
