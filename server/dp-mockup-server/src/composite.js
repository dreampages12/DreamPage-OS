/**
 * Selve rendringen: coveret samples gjennom uv-kartet og modereres av
 * lyskartene. Ingen nettleser, ingen PSD - bare piksler.
 *
 * Dette er den eneste kodestien som kjører per ordre. Photopea brukes kun til
 * kalibrering (én gang per PSD), aldri i produksjonsveien.
 */
import sharp from "sharp";
import { UV_OUTSIDE } from "./maps.js";
import { log } from "./util/log.js";

/**
 * Skalerer og beskjærer coveret slik at det fyller uv-rommet (cover-fit),
 * altså samme semantikk som "Fill" i Photoshop: behold sideforhold, dekk hele
 * flaten, beskjær det som stikker utenfor.
 */
export async function prepareCover(coverBuf, targetW, targetH, fit = "cover") {
  const { data, info } = await sharp(coverBuf)
    .rotate()
    .resize(targetW, targetH, {
      fit: fit === "contain" ? "contain" : "cover",
      position: "centre",
      background: { r: 255, g: 255, b: 255, alpha: 1 },
    })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return { data, width: info.width, height: info.height };
}

/**
 * Bilineær sampling av coveret. Kantene klemmes, så et uv som treffer
 * ytterkanten aldri leser utenfor bufferet.
 */
function sampleBilinear(src, sw, sh, fx, fy, out) {
  const x = fx <= 0 ? 0 : fx >= sw - 1 ? sw - 1.0001 : fx;
  const y = fy <= 0 ? 0 : fy >= sh - 1 ? sh - 1.0001 : fy;
  const x0 = x | 0;
  const y0 = y | 0;
  const x1 = x0 + 1 < sw ? x0 + 1 : x0;
  const y1 = y0 + 1 < sh ? y0 + 1 : y0;
  const tx = x - x0;
  const ty = y - y0;
  const w00 = (1 - tx) * (1 - ty);
  const w10 = tx * (1 - ty);
  const w01 = (1 - tx) * ty;
  const w11 = tx * ty;
  const i00 = (y0 * sw + x0) * 3;
  const i10 = (y0 * sw + x1) * 3;
  const i01 = (y1 * sw + x0) * 3;
  const i11 = (y1 * sw + x1) * 3;
  out[0] = src[i00] * w00 + src[i10] * w10 + src[i01] * w01 + src[i11] * w11;
  out[1] = src[i00 + 1] * w00 + src[i10 + 1] * w10 + src[i01 + 1] * w01 + src[i11 + 1] * w11;
  out[2] = src[i00 + 2] * w00 + src[i10 + 2] * w10 + src[i01 + 2] * w01 + src[i11 + 2] * w11;
}

/**
 * @param {Buffer} coverBuf  rå bildebytes (png/jpg/webp)
 * @param {MapSet} maps
 * @param {{format?:string, width?:number, quality?:number, fit?:string,
 *          background?:string, supersample?:number}} opts
 */
export async function renderMockup(coverBuf, maps, opts = {}) {
  const started = Date.now();
  const { width: W, height: H, uvx, uvy, white, black, alpha } = maps;

  // Coveret rendres i kartets egen oppløsning. Kartene er laget i full
  // oppløsning, så vi mister ingenting ved å sample her.
  const coverSpace = maps.meta?.coverSpace ?? { width: W, height: H };
  const cover = await prepareCover(coverBuf, coverSpace.width, coverSpace.height, opts.fit);
  const sw = cover.width;
  const sh = cover.height;
  const src = cover.data;

  const out = Buffer.allocUnsafe(W * H * 4);
  const px = new Float64Array(3);

  for (let i = 0, o = 0, j = 0; i < W * H; i += 1, o += 4, j += 3) {
    const a = alpha[i];
    if (a === 0) {
      out[o] = 0; out[o + 1] = 0; out[o + 2] = 0; out[o + 3] = 0;
      continue;
    }

    const bR = black[j];
    const bG = black[j + 1];
    const bB = black[j + 2];
    const dR = white[j] - bR;
    const dG = white[j + 1] - bG;
    const dB = white[j + 2] - bB;

    if (dR === 0 && dG === 0 && dB === 0) {
      // Coveret påvirker ikke denne pikselen (papirblokk, skygge, bakgrunn).
      out[o] = bR; out[o + 1] = bG; out[o + 2] = bB; out[o + 3] = a;
      continue;
    }

    const ux = uvx[i];
    if (ux === UV_OUTSIDE) {
      out[o] = bR; out[o + 1] = bG; out[o + 2] = bB; out[o + 3] = a;
      continue;
    }

    sampleBilinear(src, sw, sh, (ux / 65534) * (sw - 1), (uvy[i] / 65534) * (sh - 1), px);

    const r = bR + (dR * px[0]) / 255;
    const g = bG + (dG * px[1]) / 255;
    const b = bB + (dB * px[2]) / 255;
    out[o] = r < 0 ? 0 : r > 255 ? 255 : r;
    out[o + 1] = g < 0 ? 0 : g > 255 ? 255 : g;
    out[o + 2] = b < 0 ? 0 : b > 255 ? 255 : b;
    out[o + 3] = a;
  }

  let pipeline = sharp(out, { raw: { width: W, height: H, channels: 4 } });

  if (opts.width && opts.width !== W) {
    pipeline = pipeline.resize(Math.round(opts.width), null, { fit: "inside" });
  }

  const format = (opts.format || "png").toLowerCase();
  if (format === "jpeg" || format === "jpg") {
    pipeline = pipeline
      .flatten({ background: opts.background || "#ffffff" })
      .jpeg({ quality: opts.quality ?? 92, chromaSubsampling: "4:4:4" });
  } else if (format === "webp") {
    pipeline = pipeline.webp({ quality: opts.quality ?? 92 });
  } else {
    pipeline = pipeline.png({ compressionLevel: 9 });
  }

  const buf = await pipeline.toBuffer();
  log.debug("render ferdig", { ms: Date.now() - started, w: W, h: H, format });
  return { buffer: buf, width: W, height: H, format, ms: Date.now() - started };
}

/**
 * Brukes av kalibreringen: hvor godt treffer modellen en fasit-render?
 * Returnerer gjennomsnitt, p99 og maks avvik i 0-255.
 */
export function compareRenders(predicted, actual, alpha) {
  const n = alpha.length;
  const errors = [];
  let sum = 0;
  let count = 0;
  let max = 0;
  for (let i = 0, j = 0; i < n; i += 1, j += 3) {
    if (alpha[i] < 250) continue;
    for (let c = 0; c < 3; c += 1) {
      const e = Math.abs(predicted[j + c] - actual[j + c]);
      sum += e;
      count += 1;
      if (e > max) max = e;
      if (errors.length < 2_000_000) errors.push(e);
    }
  }
  errors.sort((a, b) => a - b);
  return {
    mean: count ? sum / count : 0,
    p99: errors.length ? errors[Math.floor(errors.length * 0.99)] : 0,
    max,
    samples: count,
  };
}
