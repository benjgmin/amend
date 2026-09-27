// 05 FLUID — glossy black ink on orange. One droplet lands, then divides on
// every beat (1 -> 2 -> 4 -> 8, with area conserved so the goo bridges stretch
// and snap), the eight orbit, collapse back into one and flood the frame.
// Rendered as a metaball field in a WebGL fragment shader: analytic AA,
// height-from-field normals, Blinn specular, fresnel rim + contact shadow.
import { W, H, C, BEAT, RGB } from '../config.js';
import { seg, outBack, outElastic, inOutCubic, inCubic, lerp, smoothstep } from '../lib/ease.js';

const MAXB = 12;
let gl, cv, prog, U = {};

const VS = `#version 300 es
in vec2 a;
void main(){ gl_Position = vec4(a, 0., 1.); }`;

const SUB = 6; // shutter sub-samples, integrated inside the shader
const FS = `#version 300 es
precision highp float;
uniform vec2 uRes;
uniform vec3 uB[${MAXB * 6}];
uniform int uN;
uniform vec3 uBg;
uniform vec3 uInk;
uniform float uFlood[6];
uniform float uZoom[6];
uniform vec4 uRip[6];
out vec4 o;

float field(vec2 p, int base, out vec2 g) {
  float f = 0.; g = vec2(0.);
  for (int i = 0; i < ${MAXB}; i++) {
    if (i >= uN) break;
    vec3 b = uB[base + i];
    vec2 d = p - b.xy;
    float d2 = dot(d, d) + 1.;
    float inv = b.z * b.z / d2;
    f += inv;
    g += (-2. * inv / d2) * d;
  }
  return f;
}

vec3 bgAt(vec2 p, int s, float sh) {
  float rd = length(p - uRes * 0.5);
  float rip = 0.;
  for (int i = 0; i < 4; i++) {
    float age = uRip[s][i];
    if (age <= 0. || age > 1.6) continue;
    float front = age * 900.;
    float x = (rd - front) / 170.;
    if (abs(x) > 3.) continue;
    rip += sin((rd - front) * 0.045) * exp(-x * x) * exp(-age * 3.2) * smoothstep(0., 0.05, age);
  }
  float vig = 1. - 0.10 * length((p - uRes * 0.5) / uRes.y);
  return uBg * vig * (1. - sh) * (1. + rip * 0.07);
}

vec3 inkAt(vec2 p0, int s, vec3 bg) {
  vec2 p = uRes * 0.5 + (p0 - uRes * 0.5) / uZoom[s];
  vec2 g; float f = field(p, s * ${MAXB}, g);
  if (f < 0.6) return bg;
  float gm = max(length(g), 1e-5);
  float cov = clamp((f - 1.) / gm * uZoom[s] + 0.5, 0., 1.);
  vec2 gh = g / (f * f);
  vec3 n = normalize(vec3(-gh * 110., 1.));
  vec3 L = normalize(vec3(-0.55, -0.7, 0.75));
  vec3 Hh = normalize(L + vec3(0., 0., 1.));
  float nh = max(dot(n, Hh), 0.);
  float nh2 = nh * nh, nh4 = nh2 * nh2, nh8 = nh4 * nh4;
  float spec = pow(nh, 90.) * 1.15;
  float broad = nh8 * nh * 0.10;
  float oz = 1. - clamp(n.z, 0., 1.);
  float fres = oz * oz * sqrt(sqrt(oz));
  vec3 ink = uInk + uBg * fres * 0.85 + vec3(broad);
  vec3 L2 = normalize(vec3(0.6, 0.8, 0.35));
  float l2 = max(dot(n, L2), 0.);
  float l22 = l2 * l2;
  ink += vec3(0.35, 0.38, 0.9) * (l22 * l22 * l22) * 0.25;
  ink += vec3(spec);
  ink = mix(ink, uInk, uFlood[s]);
  return mix(bg, ink, cov);
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y);
  // background (ripples + contact shadow) once, at mid-shutter
  vec2 pm = uRes * 0.5 + (p - uRes * 0.5) / uZoom[3];
  vec2 g; float fm = field(pm, ${3 * MAXB}, g);
  vec2 gs; float fs = field(pm - vec2(16., 26.), ${3 * MAXB}, gs);
  vec3 bg = bgAt(pm, 3, smoothstep(0.35, 1.05, fs) * 0.28);
  if (fm < 0.25) { o = vec4(bg, 1.); return; }
  // blob surface: integrate the shutter
  vec3 acc = vec3(0.);
  for (int s = 0; s < 6; s++) acc += inkAt(p, s, bg);
  o = vec4(acc / 6., 1.);
}`;

function compile(type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s;
}

function init() {
  cv = document.createElement('canvas');
  cv.width = W;
  cv.height = H;
  gl = cv.getContext('webgl2', { preserveDrawingBuffer: true, antialias: false });
  if (!gl) throw new Error('no webgl2');
  prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  for (const k of ['uRes', 'uB', 'uN', 'uBg', 'uInk', 'uFlood', 'uZoom', 'uRip']) U[k] = gl.getUniformLocation(prog, k);
  gl.viewport(0, 0, W, H);
}

const R0 = 205;
const RL = R0 / Math.sqrt(8); // leaf radius: 8 coincident leaves == one R0 blob

// split progress: slow stretch (the goo bridge) then a snap apart with overshoot
function split(u, t0) {
  const p = seg(u, t0, t0 + 0.62);
  if (p < 0.5) return 0.36 * inOutCubic(p / 0.5);
  return 0.36 + 0.64 * outBack((p - 0.5) / 0.5, 1.6);
}

export function blobsAt(u) {
  const grow = u < 0.5 ? outElastic(seg(u, 0.0, 0.5), 0.45) : 1;
  const s1 = split(u, 0.72);
  const s2 = split(u, 1.72);
  const s3 = split(u, 2.72);
  const merge = inOutCubic(seg(u, 3.38, 3.78));
  const flood = inCubic(seg(u, 3.7, 4.0));
  const spin = 0.3 * seg(u, 2.9, 3.4) + inCubic(seg(u, 3.2, 3.78)) * 1.6;
  const beatPulse = u > 0.9 ? Math.exp(-(u % 1) * 9) * 0.06 : 0;
  const out = [];
  for (let k = 0; k < 8; k++) {
    const sx = k & 1 ? 1 : -1, sy = k & 2 ? 1 : -1, sz = k & 4 ? 1 : -1;
    let x = sx * 250 * s1;
    let y = sy * 175 * s2;
    // level 3: each pair splits tangentially onto a ring of eight
    const ga = Math.atan2(sy, sx);
    const a = ga + sz * (Math.PI / 8);
    x = lerp(x, Math.cos(a) * 340, s3);
    y = lerp(y, Math.sin(a) * 340, s3);
    const c = Math.cos(spin), s = Math.sin(spin);
    let X = x * c - y * s, Y = x * s + y * c;
    X *= 1 - merge;
    Y *= 1 - merge;
    const wob = 1 + 0.035 * Math.sin(u * 7.1 + k * 1.7);
    const r = RL * grow * wob * (1 + beatPulse) * (1 + flood * 11);
    out.push([960 + X, 540 + Y, r]);
  }
  return out;
}

export default {
  init,
  samples: () => 1, // motion blur is integrated in the shader (see SUB)
  vignette: 0.15,
  hud: (lt) => (lt / BEAT > 3.9 ? C.paper : C.ink),
  render(ctx, lt) {
    const arr = new Float32Array(MAXB * 3 * SUB);
    const flood = new Float32Array(SUB), zoom = new Float32Array(SUB), rip = new Float32Array(SUB * 4);
    let nb = 0;
    for (let k = 0; k < SUB; k++) {
      const tk = Math.min(BEAT * 4 - 1e-6, Math.max(0, lt + ((k + 0.5) / SUB - 0.5) * (0.5 / 60)));
      const u = tk / BEAT;
      const bl = blobsAt(u);
      nb = Math.min(MAXB, bl.length);
      bl.slice(0, MAXB).forEach((b, i) => arr.set(b, (k * MAXB + i) * 3));
      flood[k] = smoothstep(3.75, 3.98, u);
      zoom[k] = 1 + 0.07 * inOutCubic(seg(u, 0, 3.4));
      const age = (b) => (u > b ? (u - b) * BEAT : 0);
      rip.set([age(0.02), age(1.05), age(2.05), age(3.05)], k * 4);
    }
    gl.uniform2f(U.uRes, W, H);
    gl.uniform3fv(U.uB, arr);
    gl.uniform1i(U.uN, nb);
    gl.uniform3f(U.uBg, RGB.signal[0] / 255, RGB.signal[1] / 255, RGB.signal[2] / 255);
    gl.uniform3f(U.uInk, RGB.ink[0] / 255, RGB.ink[1] / 255, RGB.ink[2] / 255);
    gl.uniform1fv(U.uFlood, flood);
    gl.uniform1fv(U.uZoom, zoom);
    gl.uniform4fv(U.uRip, rip);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    ctx.drawImage(cv, 0, 0);
  },
};
