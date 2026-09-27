// Timing + design tokens. 8 bars at 128 BPM is exactly 15.000 s.
// Colours are the app's own EFB palette (ios/Amend/Theme.swift).
export const W = 1920;
export const H = 1080;
export const FPS = 60;
export const BPM = 128;
export const BEAT = 60 / BPM; // 0.46875 s
export const BAR = BEAT * 4; // 1.875 s
export const DURATION = BAR * 8; // 15 s
export const FRAMES = Math.round(DURATION * FPS); // 900

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

export const SCENES = [
  { id: 'cycle', label: '', start: 0 * BAR, end: 1 * BAR },
  { id: 'noise', label: '', start: 1 * BAR, end: 2 * BAR },
  { id: 'brand', label: '', start: 2 * BAR, end: 3 * BAR },
  { id: 'remarks', label: 'PLAIN-ENGLISH REMARKS', start: 3 * BAR, end: 4 * BAR },
  { id: 'ranked', label: 'RANKED BY HOW YOU FLY', start: 4 * BAR, end: 5 * BAR },
  { id: 'history', label: 'HISTORY BACK TO AUG 2024', start: 5 * BAR, end: 6 * BAR },
  { id: 'map', label: 'EVERY US AIRPORT, EVERY CYCLE', start: 6 * BAR, end: 7 * BAR },
  { id: 'end', label: '', start: 7 * BAR, end: 8 * BAR },
];
