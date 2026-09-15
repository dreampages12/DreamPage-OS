/**
 * Analytisk kartgenerator: bygger uv- og lyskart for en 3D-bok ut fra ren
 * geometri, uten PSD.
 *
 * Poenget er at den mater NØYAKTIG samme compositor som PSD-veien. Serveren er
 * derfor i produksjon før PSD-en finnes, og når PSD-en kommer byttes bare
 * kartkilden - ingen endring i renderveien, cachen eller API-et.
 */
import { MapSet, UV_OUTSIDE } from "../maps.js";

export const PROCEDURAL_VERSION = 3;

export const DEFAULT_GEOMETRY = {
  // Betrakteren står litt til høyre: forsidens høyre kant er nærmest, så
  // papirblokken er synlig til høyre og ryggen ligger skjult bak venstre kant.
  tilt: 0.93,        // venstre kant sin høyde relativt til høyre
  depth: 0.88,       // horisontal forkorting av forsiden
  blockWidth: 0.062, // papirblokkens bredde, andel av bokhøyden
  blockTilt: 0.955,  // papirblokkens ytterkant viker bakover
  shadow: 0.55,      // styrke på slagskyggen (0 = av)
  shadowBlur: 0.024,
  shading: 0.30,     // hvor mye mørkere venstre kant blir
  hinge: 0.018,      // bredden på falsen langs ryggkanten
  padX: 0.10,
  padY: 0.05,
  padBottom: 0.09,
};

/** Homografi som mapper enhetskvadratet (0..1)^2 til firkanten q (TL,TR,BR,BL). */
function homographyFromUnitSquare(q) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = q;
  const dx1 = x1 - x2;
  const dx2 = x3 - x2;
  const dy1 = y1 - y2;
  const dy2 = y3 - y2;
  const sx = x0 - x1 + x2 - x3;
  const sy = y0 - y1 + y2 - y3;

  const den = dx1 * dy2 - dx2 * dy1;
  const g = (sx * dy2 - dx2 * sy) / den;
  const h = (dx1 * sy - sx * dy1) / den;

  return [
    x1 - x0 + g * x1, x3 - x0 + h * x3, x0,
    y1 - y0 + g * y1, y3 - y0 + h * y3, y0,
    g, h, 1,
  ];
}

function invert3x3(m) {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!det) throw new Error("singulaer homografi");
  const D = -(b * i - c * h);
  const E = a * i - c * g;
  const F = -(a * h - b * g);
  const G = b * f - c * e;
  const H = -(a * f - c * d);
  const I = a * e - b * d;
  return [A / det, D / det, G / det, B / det, E / det, H / det, C / det, F / det, I / det];
}

const applyH = (m, x, y) => {
  const w = m[6] * x + m[7] * y + m[8];
  return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w];
};

function pointInQuad(q, px, py) {
  let inside = false;
  for (let i = 0, j = 3; i < 4; j = i, i += 1) {
    const [xi, yi] = q[i];
    const [xj, yj] = q[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** Avstand fra punkt til firkantens kant, positiv innenfor (for myke kanter). */
function edgeDistance(q, px, py) {
  let best = Infinity;
  for (let i = 0, j = 3; i < 4; j = i, i += 1) {
    const [x1, y1] = q[j];
    const [x2, y2] = q[i];
    const vx = x2 - x1;
    const vy = y2 - y1;
    const len = Math.hypot(vx, vy) || 1;
    const d = Math.abs(vx * (y1 - py) - (x1 - px) * vy) / len;
    if (d < best) best = d;
  }
  return best;
}

/**
 * Bygg kartsettet for en bokmockup.
 * @param {{size?:number, geometry?:object}} opts
 */
export function buildProceduralMaps(opts = {}) {
  const geo = { ...DEFAULT_GEOMETRY, ...(opts.geometry || {}) };
  const side = Math.max(256, Math.round(opts.size ?? 1500));

  const hR = side;
  const hL = Math.round(side * geo.tilt);
  const cw = Math.round(side * geo.depth);
  const blockW = Math.round(side * geo.blockWidth);
  const d = Math.round((hR - hL) / 2);

  const padX = Math.round(side * geo.padX);
  const padY = Math.round(side * geo.padY);
  const x0 = padX;
  const y0 = padY;

  const W = x0 + cw + blockW + padX;
  const H = y0 + hR + Math.round(side * geo.padBottom);

  const coverQuad = [
    [x0, y0 + d],
    [x0 + cw, y0],
    [x0 + cw, y0 + hR],
    [x0, y0 + d + hL],
  ];
  const hB = Math.round(hR * geo.blockTilt);
  const dB = Math.round((hR - hB) / 2);
  const blockQuad = [
    [x0 + cw, y0],
    [x0 + cw + blockW, y0 + dB],
    [x0 + cw + blockW, y0 + dB + hB],
    [x0 + cw, y0 + hR],
  ];

  const Hinv = invert3x3(homographyFromUnitSquare(coverQuad));

  const n = W * H;
  const uvx = new Uint16Array(n).fill(UV_OUTSIDE);
  const uvy = new Uint16Array(n).fill(UV_OUTSIDE);
  const white = new Uint8Array(n * 3);
  const black = new Uint8Array(n * 3);
  const alpha = new Uint8Array(n);

  // --- slagskygge: myk, forskjøvet ned/venstre ---
  const shOffX = -Math.round(side * 0.012);
  const shOffY = Math.round(side * 0.026);
  const shadowQuad = [
    [coverQuad[0][0] + shOffX, coverQuad[0][1] + shOffY],
    [blockQuad[1][0] + shOffX, blockQuad[1][1] + shOffY],
    [blockQuad[2][0] + shOffX, blockQuad[2][1] + shOffY],
    [coverQuad[3][0] + shOffX, coverQuad[3][1] + shOffY],
  ];
  const blurPx = Math.max(2, Math.round(side * geo.shadowBlur));

  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      const i = y * W + x;
      const j = i * 3;
      const cx = x + 0.5;
      const cy = y + 0.5;

      // 1) skygge (helt under boka, coveret påvirker den ikke)
      if (geo.shadow > 0 && pointInQuad(shadowQuad, cx, cy)) {
        const dist = edgeDistance(shadowQuad, cx, cy);
        const soft = Math.min(1, dist / blurPx);
        const a = Math.round(255 * geo.shadow * soft * 0.62);
        if (a > 0) {
          alpha[i] = a;
          white[j] = 22; white[j + 1] = 20; white[j + 2] = 26;
          black[j] = 22; black[j + 1] = 20; black[j + 2] = 26;
        }
      }

      // 2) papirblokk (konstant, upåvirket av coveret)
      if (pointInQuad(blockQuad, cx, cy)) {
        const t = (cx - blockQuad[0][0]) / Math.max(1, blockW);
        const stripe = 0.5 + 0.5 * Math.cos(t * blockW * 0.9);
        const base = 245 - 26 * t - 10 * stripe;
        const v = Math.max(150, Math.min(255, Math.round(base)));
        alpha[i] = 255;
        white[j] = v; white[j + 1] = v - 4; white[j + 2] = v - 12;
        black[j] = v; black[j + 1] = v - 4; black[j + 2] = v - 12;
      }

      // 3) forsiden: her lever coveret
      if (pointInQuad(coverQuad, cx, cy)) {
        const [u, v] = applyH(Hinv, cx, cy);
        const uu = Math.min(1, Math.max(0, u));
        const vv = Math.min(1, Math.max(0, v));
        uvx[i] = Math.round(uu * 65534);
        uvy[i] = Math.round(vv * 65534);

        // Lys: mørkest mot venstre kant, som viker bakover.
        let shade = 1 - geo.shading * Math.pow(1 - uu, 1.5);
        // Fals langs ryggkanten.
        const hinge = geo.hinge;
        if (uu < hinge) shade *= 0.55 + 0.45 * (uu / hinge);
        // Svak glans øverst til høyre.
        shade *= 1 + 0.05 * Math.max(0, (uu - 0.6) / 0.4) * Math.max(0, (0.4 - vv) / 0.4);

        const s = Math.max(0, Math.min(1.15, shade));
        const amb = Math.round(6 * s);
        const top = Math.min(255, Math.round(amb + 249 * s));
        alpha[i] = 255;
        black[j] = amb; black[j + 1] = amb; black[j + 2] = Math.min(255, amb + 2);
        white[j] = top; white[j + 1] = top; white[j + 2] = Math.min(255, top);
      }
    }
  }

  return new MapSet({
    width: W,
    height: H,
    uvx, uvy, white, black, alpha,
    meta: {
      source: "procedural",
      proceduralVersion: PROCEDURAL_VERSION,
      geometry: geo,
      size: side,
      // Coveret samples i denne oppløsningen. Litt over forsidens flate i
      // piksler, så vi ikke taper detaljer på skrå kanter.
      coverSpace: { width: Math.round(cw * 1.15), height: Math.round(hR * 1.15) },
    },
  });
}
