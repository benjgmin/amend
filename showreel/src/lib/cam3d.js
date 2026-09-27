// Minimal orbit camera: world is y-down (screen-like), ground plane y = 0.
export function makeCam({ yaw = 0, pitch = 0, dist = 2000, focal = 1500, cx = 960, cy = 540, tx = 0, ty = 0, tz = 0 }) {
  const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return {
    yaw, pitch, dist, focal,
    // returns [sx, sy, depth, scale]
    project(x, y, z, out = [0, 0, 0, 0]) {
      x -= tx; y -= ty; z -= tz;
      const x1 = x * cyw - z * syw;
      const z1 = x * syw + z * cyw;
      const y2 = y * cp - z1 * sp;
      const z2 = y * sp + z1 * cp;
      const d = z2 + dist;
      const s = focal / d;
      out[0] = cx + x1 * s;
      out[1] = cy + y2 * s;
      out[2] = d;
      out[3] = s;
      return out;
    },
  };
}
