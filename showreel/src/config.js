// Global timing + design tokens. Everything is locked to a 128 BPM grid:
// 8 bars of 4/4 at 128 BPM is exactly 15.000 seconds.
export const W = 1920;
export const H = 1080;
export const FPS = 60;
export const BPM = 128;
export const BEAT = 60 / BPM; // 0.46875 s
export const BAR = BEAT * 4; // 1.875 s
export const DURATION = BAR * 8; // 15 s
export const FRAMES = Math.round(DURATION * FPS); // 900

export const C = {
  ink: '#0C0C0E',
  ink2: '#17171B',
  paper: '#F2EDE4',
  signal: '#FF4B1F',
  volt: '#2E3BFF',
  acid: '#D6FF3B',
  blush: '#FFA8CF',
};

// rgb triplets for per-pixel work
export const RGB = {
  ink: [12, 12, 14],
  paper: [242, 237, 228],
  signal: [255, 75, 31],
  volt: [46, 59, 255],
  acid: [214, 255, 59],
  blush: [255, 168, 207],
};

// beat -> seconds
export const b2s = (b) => b * BEAT;

// Scene table: [start, end) in seconds. `hud` is the HUD ink colour over that scene.
export const SCENES = [
  { id: 'boot', label: 'INTRO', start: 0 * BAR, end: 1 * BAR },
  { id: 'type', label: 'KINETIC TYPE', start: 1 * BAR, end: 2 * BAR },
  { id: 'shape', label: 'SHAPE SYSTEMS', start: 2 * BAR, end: 3 * BAR },
  { id: 'particles', label: 'PARTICLES', start: 3 * BAR, end: 4 * BAR },
  { id: 'dimension', label: 'DIMENSION', start: 4 * BAR, end: 5 * BAR },
  { id: 'fluid', label: 'FLUID', start: 5 * BAR, end: 6 * BAR },
  { id: 'montage', label: 'RHYTHM', start: 6 * BAR, end: 7 * BAR },
  { id: 'end', label: 'CONTACT', start: 7 * BAR, end: 8 * BAR },
];
