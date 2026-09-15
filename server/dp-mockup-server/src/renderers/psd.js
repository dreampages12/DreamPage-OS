/**
 * PSD-vei: kalibrer én gang, render tusen ganger uten nettleser.
 *
 * Kalibreringen kjører fire render gjennom Photopea:
 *   WHITE  smart object fylt helhvitt   -> hvordan mockupen ser ut ved cover=255
 *   BLACK  smart object fylt helsvart   -> ved cover=0
 *   UVX    horisontal 16-bits rampe     -> hvilken kilde-x havner i hver piksel
 *   UVY    vertikal 16-bits rampe       -> tilsvarende for y
 *
 * UV-rendene er det preview-serveren ikke har. De koster to ekstra render én
 * gang, og til gjengjeld tåler modellen vilkårlig warp: perspektiv, buet papir,
 * rotasjon. Er smart-objektet akse-alignert (som i den kvadratiske bok-PSD-en)
 * degenererer uv til et rektangel, og modellen er identisk med den lineære.
 *
 * Etterpå valideres modellen mot to fasit-render (grå og rød). Treffer den
 * ikke innenfor terskelen, avvises kalibreringen framfor å trykke feil farger.
 */
import sharp from "sharp";
import { MapSet, UV_OUTSIDE } from "../maps.js";
import { compareRenders } from "../composite.js";
import { withPhotopea, buildReplaceScript } from "../photopea.js";
import { putAsset, dropAsset } from "../assets.js";
import { config } from "../config.js";
import { log } from "../util/log.js";
import { internal } from "../util/errors.js";

export const CALIBRATION_VERSION = 2;

/** Flatt RGB-bilde i PNG. */
async function solid(width, height, r, g, b) {
  return sharp({
    create: { width, height, channels: 3, background: { r, g, b } },
  }).png().toBuffer();
}

/**
 * 16-bits rampe langs én akse, kodet som R = høybyte, G = lavbyte.
 * Gir 65536 nivåer, altså subpiksel-presisjon for cover opp til 65k px.
 */
async function ramp(width, height, axis) {
  const data = Buffer.alloc(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const t = axis === "x"
        ? (width === 1 ? 0 : x / (width - 1))
        : (height === 1 ? 0 : y / (height - 1));
      const v = Math.round(t * 65535);
      const i = (y * width + x) * 3;
      data[i] = v >> 8;
      data[i + 1] = v & 255;
      data[i + 2] = 0;
    }
  }
  return sharp(data, { raw: { width, height, channels: 3 } }).png().toBuffer();
}

async function toRaw(pngBuf) {
  const { data, info } = await sharp(pngBuf)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  return { data, width: info.width, height: info.height };
}

/**
 * Kjør ett render gjennom Photopea: bytt smart object, eksporter, rydd.
 * PSD-en åpnes én gang per session og gjenbrukes mellom rendene - derfor
 * lukkes smart-objektet med DONOTSAVE etterpå, slik at neste render starter
 * fra samme utgangspunkt.
 */
async function renderFrame(session, ctx, contentPng, label) {
  const token = putAsset(contentPng, "image/png");
  try {
    const coverName = await session.loadFromUrl(`${config.publicBaseUrl}/calib-asset/${token}`);
    await session.runScript(buildReplaceScript(ctx.psdName, coverName, ctx.layerName));
    const msgs = await session.drainText();
    const err = msgs.find((m) => typeof m === "string" && m.startsWith("ERR:"));
    if (err) {
      throw internal("photopea_replace_failed",
        `Photopea klarte ikke aa bytte smart object (${label}): ${err.slice(4)}`);
    }
    const png = await session.exportPng();
    // Lukk cover-dokumentet igjen.
    await session.runScript(
      `(function(){for(var i=0;i<app.documents.length;i++){` +
      `if(app.documents[i].name===${JSON.stringify(coverName)}){` +
      `app.activeDocument=app.documents[i];` +
      `app.activeDocument.close(SaveOptions.DONOTSAVECHANGES);return;}}})();`
    );
    return png;
  } finally {
    dropAsset(token);
  }
}

/**
 * @param {Buffer} psdBuf
 * @param {{layerName:string, coverWidth:number, coverHeight:number}} spec
 */
export async function calibratePsd(psdBuf, spec) {
  const { layerName, coverWidth = 2048, coverHeight = 2048 } = spec;
  const started = Date.now();
  const l = log.child({ layer: layerName });
  l.info("kalibrering starter");

  const psdToken = putAsset(psdBuf, "image/vnd.adobe.photoshop");
  const frames = await withPhotopea(async (session) => {
    const psdName = await session.loadFromUrl(
      `${config.publicBaseUrl}/calib-asset/${psdToken}`);
    l.info("PSD apnet i Photopea", { psdName });
    const ctx = { psdName, layerName };
    const out = {};
    const plan = [
      ["white", () => solid(coverWidth, coverHeight, 255, 255, 255)],
      ["black", () => solid(coverWidth, coverHeight, 0, 0, 0)],
      ["uvx", () => ramp(coverWidth, coverHeight, "x")],
      ["uvy", () => ramp(coverWidth, coverHeight, "y")],
      ["gray", () => solid(coverWidth, coverHeight, 128, 128, 128)],
      ["red", () => solid(coverWidth, coverHeight, 217, 38, 76)],
    ];
    for (const [name, make] of plan) {
      out[name] = await renderFrame(session, ctx, await make(), name);
      l.info("kalibreringsrender ferdig", { frame: name, bytes: out[name].length });
    }
    return out;
  }).finally(() => dropAsset(psdToken));

  const W = await toRaw(frames.white);
  const B = await toRaw(frames.black);
  const X = await toRaw(frames.uvx);
  const Y = await toRaw(frames.uvy);
  if (W.width !== B.width || W.height !== B.height) {
    throw internal("calib_size_mismatch", "kalibreringsrendene har ulik stoerrelse");
  }

  const width = W.width;
  const height = W.height;
  const n = width * height;
  const uvxArr = new Uint16Array(n).fill(UV_OUTSIDE);
  const uvyArr = new Uint16Array(n).fill(UV_OUTSIDE);
  const whiteArr = new Uint8Array(n * 3);
  const blackArr = new Uint8Array(n * 3);
  const alphaArr = new Uint8Array(n);

  let influenced = 0;
  for (let i = 0, s = 0, d = 0; i < n; i += 1, s += 4, d += 3) {
    whiteArr[d] = W.data[s];
    whiteArr[d + 1] = W.data[s + 1];
    whiteArr[d + 2] = W.data[s + 2];
    blackArr[d] = B.data[s];
    blackArr[d + 1] = B.data[s + 1];
    blackArr[d + 2] = B.data[s + 2];
    alphaArr[i] = W.data[s + 3];

    const infl = Math.max(
      Math.abs(W.data[s] - B.data[s]),
      Math.abs(W.data[s + 1] - B.data[s + 1]),
      Math.abs(W.data[s + 2] - B.data[s + 2])
    );
    if (infl > 6) {
      influenced += 1;
      uvxArr[i] = Math.min(65534, (X.data[s] << 8) | X.data[s + 1]);
      uvyArr[i] = Math.min(65534, (Y.data[s] << 8) | Y.data[s + 1]);
    }
  }

  const maps = new MapSet({
    width, height,
    uvx: uvxArr, uvy: uvyArr,
    white: whiteArr, black: blackArr, alpha: alphaArr,
    meta: {
      source: "psd",
      calibrationVersion: CALIBRATION_VERSION,
      layerName,
      coverSpace: { width: coverWidth, height: coverHeight },
      influenceRatio: influenced / n,
    },
  });

  const validation = await validate(maps, frames);
  maps.meta.validation = validation;

  const ok =
    validation.gray.mean <= config.calibMaxMeanError &&
    validation.red.mean <= config.calibMaxMeanError &&
    validation.gray.p99 <= config.calibMaxP99Error &&
    validation.red.p99 <= config.calibMaxP99Error;
  maps.meta.accepted = ok;

  l.info("kalibrering ferdig", {
    ms: Date.now() - started, width, height,
    influenceRatio: Number((influenced / n).toFixed(4)),
    grayMean: Number(validation.gray.mean.toFixed(2)),
    redMean: Number(validation.red.mean.toFixed(2)),
    accepted: ok,
  });

  if (!ok) {
    throw internal("calib_rejected",
      "kalibreringen traff ikke fasitrendene - PSD-en har trolig et ikke-lineaert " +
      "lag over smart-objektet (f.eks. fargejustering eller gradient map). " +
      `gray.mean=${validation.gray.mean.toFixed(2)} red.mean=${validation.red.mean.toFixed(2)}`,
      validation);
  }

  return maps;
}

/** Sammenlign modellens prediksjon mot ekte Photopea-render av grå og rød. */
async function validate(maps, frames) {
  const out = {};
  for (const [name, rgb] of [["gray", [128, 128, 128]], ["red", [217, 38, 76]]]) {
    const actual = await toRaw(frames[name]);
    const n = maps.width * maps.height;
    const predicted = new Uint8Array(n * 3);
    for (let i = 0, d = 0; i < n; i += 1, d += 3) {
      for (let c = 0; c < 3; c += 1) {
        const b = maps.black[d + c];
        const w = maps.white[d + c];
        predicted[d + c] = Math.round(b + ((w - b) * rgb[c]) / 255);
      }
    }
    const actualRgb = new Uint8Array(n * 3);
    for (let i = 0, s = 0, d = 0; i < n; i += 1, s += 4, d += 3) {
      actualRgb[d] = actual.data[s];
      actualRgb[d + 1] = actual.data[s + 1];
      actualRgb[d + 2] = actual.data[s + 2];
    }
    out[name] = compareRenders(predicted, actualRgb, maps.alpha);
  }
  return out;
}
