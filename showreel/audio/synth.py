"""Procedural soundtrack for the reel: 128 BPM, 8 bars (exactly 15 s), F minor.

Every sound is synthesised from oscillators + noise (no samples) and placed on
the same beat grid the picture is animated to, so each visual hit has its own
foley: dot pops, line zips, letter snaps, boings, goo bloops, slot-machine
ratchets that follow the rolling digits, and a half-beat of silence before the
logo drop.

    python3 audio/synth.py out.wav
"""
import sys
import wave

import numpy as np
import scipy.signal as ss

SR = 48000
BPM = 128
BEAT = 60 / BPM
DUR = 15.0
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


def snap(f=3200):
    n = ns(0.08)
    t = tt(n)
    y = bp(noise(n), 1800, 7000) * np.exp(-t / 0.006) * 1.4
    y += np.sin(2 * np.pi * f * t) * np.exp(-t / 0.012) * 0.5
    y += np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.03) * 0.8
    return fade(y)


def boing(f0=210, dur=0.45, gain=1.0):
    n = ns(dur)
    t = tt(n)
    f = f0 * (1 + 0.9 * np.exp(-t / 0.018)) * (1 + 0.06 * np.sin(2 * np.pi * 17 * t) * np.exp(-t / 0.2))
    y = np.sin(2 * np.pi * phase(f, n)) * env(n, 0.001, 0.13)
    y += 0.3 * np.sin(2 * np.pi * phase(f * 2.01, n)) * env(n, 0.001, 0.06)
    return fade(y * gain)


def bloop(f0=900, f1=190, dur=0.3, gain=1.0):
    n = ns(dur)
    t = tt(n)
    f = f1 + (f0 - f1) * np.exp(-t / 0.035)
    y = np.sin(2 * np.pi * phase(f, n)) * env(n, 0.002, 0.08)
    y += 0.2 * np.sin(2 * np.pi * phase(f * 1.5, n)) * env(n, 0.002, 0.04)
    return fade(y * gain)


def stretch(dur=0.5):
    n = ns(dur)
    t = tt(n)
    ph = np.linspace(0, 1, n)
    f = 110 * (1 + 2.2 * (1 - np.exp(-ph * 4))) * (1 + 0.04 * np.sin(2 * np.pi * 13 * t))
    x = saw(f, n)
    y = svf(x, 400 + 2600 * ph ** 0.7, 3.0, 'bp')
    return fade(y * np.sin(np.pi * ph) ** 0.6 * 0.9)


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


def stutter(src, slice_sec, reps, crush=True):
    s = src[..., :ns(slice_sec)]
    out = []
    for k in range(reps):
        seg_ = s * (1 - 0.08 * k)
        out.append(fade(seg_, 0.0005, 0.002))
    y = np.concatenate(out, axis=-1)
    if crush:
        y = np.round(y * 12) / 12
        hold = 5
        y = np.repeat(y[..., ::hold], hold, axis=-1)[..., :y.shape[-1]]
    return y


# ---------------------------------------------------------------- harmony
F2, Db2, Ab1, Eb2 = midi(41), midi(37), midi(32), midi(39)
CH = {
    'Fm': [midi(m) for m in (53, 56, 60, 63, 67)],  # F Ab C Eb G  (Fm9)
    'Db': [midi(m) for m in (49, 53, 56, 60, 63)],  # Db F Ab C Eb (Dbmaj9)
    'Ab': [midi(m) for m in (56, 60, 63, 67, 70)],  # Ab C Eb G Bb
    'Eb': [midi(m) for m in (51, 55, 58, 61, 65)],  # Eb G Bb Db F  (Eb9)
}
# bar -> (chord, bass root)
BARS = {1: ('Fm', F2), 2: ('Db', Db2), 3: ('Ab', Ab1 * 2), 4: ('Eb', Eb2), 5: ('Fm', F2), 6: ('Db', Db2)}
PENTA = [midi(m) for m in (77, 80, 82, 84, 87, 89, 92, 94, 96)]  # F minor pentatonic, high


# ================================================================= SCORE
kicks = []


def K(b, g=1.0, **kw):
    drums.add(kick(**kw), bt(b), 0.78 * g)
    kicks.append((bt(b), g))


# ---- bar 0 : intro (beats 0-4)
fx.add(pluck(midi(89), 0.6, 0.09), bt(0), 0.5)  # dot pop
fx.add(np.sin(2 * np.pi * 95 * tt(ns(0.2))) * env(ns(0.2), 0.001, 0.05), bt(0), 0.5)
ping = pluck(1250, 1.0, 0.25, 0.3)
for k, g in enumerate([0.35, 0.18, 0.09, 0.045]):
    fx.add(ping, bt(0.02) + k * bt(0.75), g, pan=[0, -0.5, 0.5, 0][k])
verb.add(ping, bt(0.02), 0.3)
for k in range(8):  # coordinate label typing
    fx.add(tick(3400, 0.03, 0.004), bt(0.4 + k * 0.035), 0.12)
fx.add(bloop(520, 380, 0.12, 0.5), bt(1.0), 0.5)  # squash
fx.add(whoosh(bt(0.62), 500, 9000, 2.5, 0.35, 1.0), bt(1.12), 0.55)  # zip -> line
fx.add(tick(5200, 0.05, 0.01), bt(1.3), 0.25)
# grid unfolds: glassy up-arpeggio
for k, m in enumerate([77, 80, 84, 87, 89, 92, 96, 99]):
    fx.add(pluck(midi(m), 0.5, 0.18, 0.5), bt(2.0 + k * 0.06), 0.16 * (1 - k * 0.05), pan=(k / 7) * 1.2 - 0.6)
    verb.add(pluck(midi(m), 0.5, 0.18, 0.5), bt(2.0 + k * 0.06), 0.12)
# tile pops: sparkle cascade on 32nds
for k in range(16):
    f = PENTA[int(rng.integers(0, len(PENTA)))]
    fx.add(marimba(f, 0.3), bt(2.5 + k * 0.055), 0.12, pan=float(rng.uniform(-0.7, 0.7)))
# closed hats come in quietly
for s in range(8, 16):
    drums.add(hat(), bt(s * 0.25), 0.25 + 0.2 * (s % 2))
music.add(pad(CH['Fm'], bt(4), 250, 1600, a=1.2), 0, 0.55)
fx.add(rev_cymbal(bt(0.72)), bt(3.28), 0.7)
fx.add(riser(bt(1.9), 200, 7000), bt(2.1), 0.35)

# ---- bars 1-6 : groove (beats 4-28)
for b in range(4, 28):
    if b in (12, 16):
        continue
    K(b)
for b in (5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25):
    drums.add(clap(), bt(b), 0.55)
    verb.add(clap(), bt(b), 0.18)
for s in range(16, 110):  # 16th hats beats 4..27.5
    b = s * 0.25
    acc = [0.55, 0.25, 0.85, 0.3][s % 4]
    drums.add(hat(), bt(b), acc * 0.9, pan=0.25)
for b in range(4, 27):
    drums.add(hat(True), bt(b + 0.5), 0.45, pan=-0.2)
# bass: rolling 16ths off the kick, octave jump on the 8th
for bar in range(1, 7):
    ch, root = BARS[bar]
    if bar == 6:
        pass
    for beat in range(4):
        b0 = bar * 4 + beat
        r = root if not (bar == 6 and beat >= 2) else Eb2
        for off, mult, g in ((0.25, 1, 0.8), (0.5, 2, 1.0), (0.75, 1, 0.8)):
            bass.add(bass_note(r * mult, bt(0.22), g), bt(b0 + off), 0.9)
# chord stabs (syncopated), with reverb
for bar in range(1, 7):
    ch, root = BARS[bar]
    for off in (0.5, 1.75, 2.5, 3.25):
        freqs = CH[ch] if not (bar == 6 and off >= 2) else CH['Eb']
        st = stab(freqs, seed=int(off * 4))
        music.add(st, bt(bar * 4 + off), 0.55)
        verb.add(st, bt(bar * 4 + off), 0.35)
    music.add(pad(CH[ch], bt(4), 600, 1400, a=0.3, seed=bar), bt(bar * 4), 0.35)

# ---- bar 1 : kinetic type
music.add(crash(2.4), bt(4), 0.9)
drums.add(sub_boom(1.8), bt(4), 0.7)
for k, o in enumerate([0.14, 0.21, 0.28, 0.35]):  # SNAP letters land
    fx.add(snap(2600 + k * 300), bt(4 + o), 0.75, pan=-0.6 + k * 0.4)
fx.add(whoosh(bt(0.16), 6000, 500, 1.5, 0.8, 1.2), bt(4.84), 0.55)  # panel drops
for k, o in enumerate([0.1, 0.35, 0.49]):  # BOUNCE
    fx.add(boing(200 - k * 12, 0.45, [1, 0.55, 0.3][k]), bt(5 + o), 0.6)
for k in range(6):
    fx.add(tick(900 + k * 90, 0.04, 0.01), bt(5.1 + k * 0.045), 0.25, pan=-0.6 + k * 0.24)
fx.add(whoosh(bt(0.16), 800, 7000, 2.0, 0.8, 1.0), bt(5.84), 0.5)  # sliver opens
fx.add(stretch(bt(0.8)), bt(6.04), 0.7)  # STRETCH
fx.add(whoosh(bt(0.16), 300, 3000, 1.5, 0.85, 1.2), bt(6.84), 0.55)  # iris
fx.add(whoosh(bt(0.75), 400, 5000, 1.8, 0.7, 1.0), bt(7.28), 0.6)  # SHAPE morph
for k in range(5):
    fx.add(marimba(PENTA[k], 0.4), bt(7.05 + k * 0.03), 0.1)

# ---- bar 2 : shape systems
for k, m in enumerate([77, 80, 84, 87, 89]):  # relay moves
    fx.add(marimba(midi(m), 0.5), bt(8.08 + k * 0.12), 0.45, pan=-0.6 + k * 0.3)
    verb.add(marimba(midi(m), 0.5), bt(8.08 + k * 0.12), 0.2)
fx.add(whoosh(bt(0.9), 200, 6000, 1.0, 0.5, 0.8), bt(9.0), 0.4)  # grid builds
for k in range(12):
    fx.add(marimba(PENTA[(k * 3) % len(PENTA)], 0.25), bt(9.05 + k * 0.06), 0.1, pan=float(rng.uniform(-0.8, 0.8)))
for k in range(8):  # rotation wave
    fx.add(pluck(PENTA[k % len(PENTA)], 0.3, 0.07), bt(10.0 + k * 0.045), 0.18, pan=-0.7 + k * 0.2)
fx.add(whoosh(bt(0.5), 900, 3500, 1.6, 0.5, 1.0), bt(10.5), 0.45)  # morph wave
for k in range(9):  # flip wave flutter, sweeping left to right
    fx.add(tick(1800 + k * 120, 0.04, 0.006), bt(3 * 4 - 1 + 0.02 + k * 0.045), 0.3, pan=-0.9 + k * 0.22)
for k in range(8):  # tiles fall away
    fx.add(bloop(1400 - k * 90, 500 - k * 30, 0.12, 0.3), bt(11.45 + k * 0.05), 0.35, pan=float(rng.uniform(-0.6, 0.6)))
fx.add(rev_cymbal(bt(0.5)), bt(11.5), 0.5)

# ---- bar 3 : particles (shatter on 12)
K(12, 1.0, f0=190, ad=0.45)
drums.add(sub_boom(2.0, 70, 32), bt(12), 0.8)
glass = hp(noise(ns(0.6)), 5000) * env(ns(0.6), 0.0005, 0.07)
fx.add(glass, bt(12), 0.8)
verb.add(glass, bt(12), 0.5)
for k in range(28):
    f = float(rng.uniform(2500, 7500))
    fx.add(pluck(f, 0.12, 0.03, 0.2), bt(12) + float(rng.uniform(0, 0.35)), 0.10, pan=float(rng.uniform(-1, 1)))
wind = svf(noise(ns(bt(4))), 700 + 500 * np.sin(np.linspace(0, 5, ns(bt(4)))), 1.5, 'bp')
wind = np.vstack([wind, np.roll(wind, 900)]) * np.sin(np.linspace(0, np.pi, ns(bt(4)))) ** 0.8
fx.add(wind, bt(12), 0.08)
for b in (13, 14, 15):
    fx.add(whoosh(bt(0.45), 3000, 400, 1.2, 0.15, 1.0), bt(b), 0.35)
fx.add(riser(bt(1.4), 400, 6000, tone=True), bt(14.1), 0.3)
for k in range(10):
    fx.add(tick(float(rng.uniform(3000, 6000)), 0.03, 0.006), bt(15.4 + k * 0.06), 0.15, pan=float(rng.uniform(-0.8, 0.8)))

# ---- bar 4 : dimension
K(16, 1.0, f0=150, ad=0.4)
music.add(crash(1.6), bt(16), 0.35)
swell = lp(saw(midi(29), ns(bt(1.2))) + saw(midi(29) * 1.005, ns(bt(1.2))), 400) * np.sin(np.linspace(0, np.pi, ns(bt(1.2))))
fx.add(swell, bt(16), 0.25)
for b in (16, 17, 18, 19):  # pulse rings
    fx.add(pluck(midi(65), 0.5, 0.12, 0.4), bt(b), 0.22)
    fx.add(pluck(midi(72), 0.5, 0.12, 0.4), bt(b), 0.12)
fx.add(whoosh(bt(0.8), 300, 2500, 1.2, 0.55, 1.0), bt(18.85), 0.5)  # crane
fx.add(riser(bt(0.66), 500, 12000, tone=False), bt(19.34), 0.6)  # dive
fx.add(whoosh(bt(0.4), 1500, 9000, 1.6, 0.9, 1.0), bt(19.6), 0.5)

# ---- bar 5 : fluid
fx.add(bloop(1100, 170, 0.45, 1.0), bt(20.0), 0.9)
splash = bp(noise(ns(0.35)), 700, 4000) * env(ns(0.35), 0.001, 0.05)
fx.add(splash, bt(20.0), 0.4)
verb.add(bloop(1100, 170, 0.45, 1.0), bt(20.0), 0.3)
for k, b0 in enumerate((20.72, 21.72, 22.72)):
    fx.add(stretch(bt(0.3)) * 0.5, bt(b0), 0.35)  # goo stretching
    for j in range(2 ** k):
        f0 = 700 + 250 * k + j * 60
        fx.add(bloop(f0, f0 * 0.3, 0.3, 1.0), bt(b0 + 0.31) + j * 0.018, 0.55 / (1 + 0.3 * j),
               pan=(-0.5 + j / max(1, 2 ** k - 1)) if k else 0)
fx.add(whoosh(bt(0.45), 400, 2000, 1.4, 0.7, 1.0), bt(23.35), 0.45)
fx.add(riser(bt(0.35), 300, 8000, tone=False), bt(23.65), 0.6)
fx.add(rev_cymbal(bt(0.35)), bt(23.65), 0.4)

# ---- bar 6 : rhythm montage
cut_stab = stab(CH['Db'], 0.3, (7000, 900), 0.12, seed=9)
music.add(cut_stab, bt(24.0), 0.5)
fx.add(pluck(midi(89), 0.3, 0.06), bt(24.0), 0.3)  # halftone
fx.add(whoosh(bt(0.45), 5000, 300, 1.1, 0.2, 1.0), bt(24.5), 0.55)  # op-art twist
# slot machine ratchet: one click per digit passing, per column
for k, (spins, a, b) in enumerate(((19, 0.02, 0.72), (20, 0.10, 0.78), (30, 0.18, 0.84))):
    for m in range(1, spins):
        y = m / spins
        x = -np.log2(1 - y) / 10
        if x > 1:
            break
        p = a + x * (b - a)
        fx.add(tick(1500 + 400 * k, 0.03, 0.004), bt(25.0 + p * 0.5), 0.22, pan=-0.5 + 0.5 * k)
fx.add(pluck(midi(84), 0.4, 0.1), bt(25.0 + 0.84 * 0.5), 0.3)
ping2 = pluck(1000, 0.8, 0.2, 0.2)  # radar
for k, g in enumerate([0.5, 0.25, 0.12]):
    fx.add(ping2, bt(25.5) + k * bt(0.1875), g, pan=[0, 0.5, -0.5][k])
st = stab(CH['Eb'], 0.2, (8000, 1500), 0.08, seed=5)  # glitch
fx.add(stutter(st, bt(1 / 16), 6), bt(26.0), 0.8)
fx.add(hp(noise(ns(0.12)), 2000) * env(ns(0.12), 0, 0.02), bt(26.0), 0.3)
fx.add(boing(260, 0.3, 0.6), bt(26.5), 0.35)  # ball bounces
for bb, g in ((26.5 + 0.219, 0.8), (26.5 + 0.381, 0.5), (26.5 + 0.476, 0.3)):
    fx.add(kick(0.15, 220, 90, 0.02, 0.05, 0.3), bt(bb), 0.5 * g)
music.add(crash(0.6), bt(27.0), 0.5)  # sunburst
fx.add(lp(saw(midi(41), ns(0.2)), 800) * env(ns(0.2), 0.001, 0.06), bt(27.25), 0.6)  # ridges
for s in range(16):  # snare roll build
    b = 26.0 + s * 0.09375
    if b >= 27.5:
        break
    drums.add(clap(0.15), bt(b), 0.12 + 0.35 * s / 16)
fx.add(riser(bt(1.5), 200, 10000), bt(26.0), 0.45)

# ---- bar 7 : the drop + end card
K(28, 1.0, f0=200, ad=0.6, drive=2.4)
drums.add(sub_boom(3.0, 66, 30), bt(28), 1.0)
music.add(crash(3.0), bt(28), 1.0)
big = stab(CH['Fm'], 2.6, (6000, 500), 0.9, seed=11)
music.add(big, bt(28), 0.8)
verb.add(big, bt(28), 0.8)
music.add(pad(CH['Fm'], bt(3.6), 900, 500, a=0.05, seed=12), bt(28), 0.8)
bass.add(bass_note(F2, bt(2.5), 1.0) * np.linspace(1, 0.3, ns(bt(2.5))), bt(28), 0.9)
for k in range(4):  # mark pieces clack together
    c = snap(1800 + 250 * k) * 0.7 + marimba(midi(77 + [0, 3, 7, 10][k]), 0.08)[: ns(0.08)] * 0.3
    fx.add(c, bt(28.12 + k * 0.07), 0.55, pan=[-0.4, 0.4, -0.3, 0.3][k])
fx.add(whoosh(bt(0.6), 600, 5000, 1.6, 0.6, 1.0), bt(28.12), 0.35)  # wordmark rises
for k in range(12):  # credits typing
    fx.add(tick(3800, 0.03, 0.004), bt(28.95 + k * 0.05), 0.12, pan=-0.3 + k * 0.05)
for k, m in enumerate([77, 84, 80, 89]):  # mark idles on the beat
    fx.add(marimba(midi(m), 0.6), bt(29.0 + k * 0.5), 0.3, pan=[-0.3, 0.3, -0.2, 0.2][k])
    verb.add(marimba(midi(m), 0.6), bt(29.0 + k * 0.5), 0.25)
K(30, 0.45)
for s in range(116, 126):
    drums.add(hat(), bt(s * 0.25), 0.3 if s % 2 else 0.15, pan=0.2)
fx.add(rev_cymbal(bt(0.34)), bt(31.58), 0.6)
fx.add(riser(bt(0.34), 800, 12000, tone=False), bt(31.58), 0.4)

# ================================================================= MIX
def sidechain(depth, rel):
    g = np.ones(drums.x.shape[1])
    for t0, a in kicks:
        i = int(t0 * SR)
        n = ns(0.45)
        tt_ = tt(n)
        d = 1 - depth * a * np.exp(-tt_ / rel)
        seg_ = g[i:i + n]
        g[i:i + n] = np.minimum(seg_, d[: len(seg_)])
    return g


sc_b = sidechain(0.75, 0.09)
sc_m = sidechain(0.55, 0.12)

# reverb: stereo decaying noise IR, darker over time
ir_n = ns(1.8)
ph = tt(ir_n)
ir = np.vstack([noise(ir_n), noise(ir_n)]) * np.exp(-ph / 0.32)
ir[:, : ns(0.012)] = 0
ir = np.vstack([lp(ir[0], 5000), lp(ir[1], 5000)])
ir /= np.abs(ir).sum(axis=1, keepdims=True) ** 0.5 * 12
wet = np.vstack([ss.fftconvolve(verb.x[0], ir[0])[: verb.x.shape[1]], ss.fftconvolve(verb.x[1], ir[1])[: verb.x.shape[1]]])
wet = hp(wet, 250)

mix = drums.x * 0.9 + bass.x * sc_b * 0.85 + music.x * sc_m * 2.2 + fx.x * 0.85 + wet * 1.1
# tame the air band a touch (~ -3 dB above 9 kHz)
mix = mix - 0.3 * np.vstack([hp(mix[0], 9000), hp(mix[1], 9000)])

# the breath: hard silence for the last half-beat of the montage
g = np.ones(mix.shape[1])
a, b = int(bt(27.5) * SR), int(bt(28.0) * SR) - ns(0.002)
g[a:b] = 0
g[a - ns(0.004):a] = np.linspace(1, 0, ns(0.004))
mix *= g
# ...except the dot that pops in the dark
mix[:, int(bt(27.56) * SR): int(bt(27.56) * SR) + ns(0.25)] += np.vstack([pluck(midi(89), 0.25, 0.06)] * 2) * 0.3
# duck everything under the final implosion, then the last dot
end_g = np.ones(mix.shape[1])
i0, i1 = int(bt(31.4) * SR), int(bt(31.82) * SR)  # the dot pops back at beat 31.82
end_g[i0:i1] = np.linspace(1, 0.35, i1 - i0)
end_g[i1:] = 0.35
mix = mix * end_g
mix[:, i1: i1 + ns(0.3)] += np.vstack([pluck(midi(89), 0.3, 0.06)] * 2)[:, : mix.shape[1] - i1] * 0.4

mix = mix[:, :N]
mix = np.vstack([hp(mix[0], 28), hp(mix[1], 28)])
drive = 1.2
mix = np.tanh(mix * drive / max(1e-9, np.percentile(np.abs(mix), 99.97))) / np.tanh(drive)
mix *= 0.84 / np.abs(mix).max()
mix = fade(mix, 0.001, 0.012)

out = sys.argv[1] if len(sys.argv) > 1 else 'soundtrack.wav'
pcm = (np.clip(mix.T, -1, 1) * 32767).astype('<i2')
with wave.open(out, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print('wrote', out, f'{mix.shape[1] / SR:.3f}s')
