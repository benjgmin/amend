// Timing + design tokens. 16 bars at 128 BPM is exactly 30.000 s.
// Colours are the app's own EFB palette (ios/Amend/Theme.swift).
export const W = 1920;
export const H = 1080;
export const FPS = 60;
export const BPM = 128;
export const BEAT = 60 / BPM; // 0.46875 s
export const BAR = BEAT * 4; // 1.875 s
export const DURATION = BAR * 16; // 30 s
export const FRAMES = Math.round(DURATION * FPS); // 1800

export const C = {
  bg: '#090C10', // EFB.bg      (0.035, 0.047, 0.063)
  panel: '#13181F', // EFB.panel   (0.075, 0.094, 0.122)
  panelHi: '#1B212A', // EFB.panelHi
  line: 'rgba(255,255,255,0.09)',
  text: '#F0F0F0', // EFB.text  white 0.94
  dim: '#8F8F8F', // EFB.dim   white 0.56
  faint: '#5C5C5C', // EFB.faint white 0.36
  amber: '#FFB500', // caution  -> ACT
  cyan: '#3DD6FF', // advisory -> IFR
  green: '#4DE073', // normal   -> NO CHG
  mark: '#F2F2F2', // wordmark white, from the app icon
};
export const RGB = {
  bg: [9, 12, 16],
  panel: [19, 24, 31],
  text: [240, 240, 240],
  dim: [143, 143, 143],
  faint: [92, 92, 92],
  amber: [255, 181, 0],
  cyan: [61, 214, 255],
  green: [77, 224, 115],
};

export const MONO = '"Geist Mono"'; // stands in for SF Mono
export const SANS = '"Inter"'; // stands in for SF Pro

// scene boundaries in beats: the text-heavy shots get the most time
const SPAN = [
  ['cycle', '', 0, 8],
  ['noise', '', 8, 16],
  ['brand', '', 16, 22],
  ['remarks', 'PLAIN-ENGLISH REMARKS', 22, 32],
  ['ranked', 'RANKED BY HOW YOU FLY', 32, 40],
  ['history', 'HISTORY BACK TO AUG 2024', 40, 48],
  ['map', 'EVERY US AIRPORT, EVERY CYCLE', 48, 56],
  ['end', '', 56, 64],
];
export const SCENES = SPAN.map(([id, label, a, b]) => ({ id, label, start: a * BEAT, end: b * BEAT, beat0: a }));
