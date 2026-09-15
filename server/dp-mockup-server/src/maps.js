/**
 * Et MapSet beskriver hvordan ETT bilde forvandles til en ferdig mockup.
 *
 *   out(x,y) = black(x,y) + (white(x,y) - black(x,y)) * cover[ uv(x,y) ]
 *
 * `white` er hvordan mockupen ser ut med et helhvitt cover, `black` med et
 * helsvart. Differansen er hvor mye coveret får påvirke pikselen — den fanger
 * lys, skygge, gjennomsiktighet og blandingsmoduser i ett. Der differansen er
 * null (papirblokk, bakgrunn, slagskygge) er pikselen konstant.
 *
 * `uv` er displacement-kartet: hvilken piksel i coveret som havner her. Det er
 * dette leddet preview-serverens lineære modell mangler, og det er grunnen til
 * at den ikke kan brukes på en warpet bokmockup.
 *
 * uv lagres som Uint16 i normaliserte koordinater (0..65535 -> 0..1), altså
 * subpiksel-presist for cover opp til 65k px. 65535 i uvx betyr "utenfor".
 */
import fs from "node:fs/promises";
import path from "node:path";
import { log } from "./util/log.js";

export const MAP_FORMAT_VERSION = 2;
export const UV_OUTSIDE = 65535;

const FILES = {
  uvx: "uvx.u16",
  uvy: "uvy.u16",
  white: "white.rgb",
  black: "black.rgb",
  alpha: "alpha.u8",
};

export class MapSet {
  constructor({ width, height, uvx, uvy, white, black, alpha, meta }) {
    this.width = width;
    this.height = height;
    this.uvx = uvx;
    this.uvy = uvy;
    this.white = white;
    this.black = black;
    this.alpha = alpha;
    this.meta = meta ?? {};
  }

  get byteLength() {
    return (
      this.uvx.byteLength + this.uvy.byteLength +
      this.white.byteLength + this.black.byteLength + this.alpha.byteLength
    );
  }

  /** Andel piksler der coveret faktisk påvirker resultatet. */
  influenceRatio() {
    let n = 0;
    for (let i = 0; i < this.alpha.length; i += 1) {
      const j = i * 3;
      if (
        Math.abs(this.white[j] - this.black[j]) > 4 ||
        Math.abs(this.white[j + 1] - this.black[j + 1]) > 4 ||
        Math.abs(this.white[j + 2] - this.black[j + 2]) > 4
      ) n += 1;
    }
    return n / this.alpha.length;
  }

  async save(dir) {
    await fs.mkdir(dir, { recursive: true });
    const meta = {
      formatVersion: MAP_FORMAT_VERSION,
      width: this.width,
      height: this.height,
      ...this.meta,
    };
    await fs.writeFile(path.join(dir, "meta.json"), JSON.stringify(meta, null, 2));
    await Promise.all([
      fs.writeFile(path.join(dir, FILES.uvx), Buffer.from(this.uvx.buffer, this.uvx.byteOffset, this.uvx.byteLength)),
      fs.writeFile(path.join(dir, FILES.uvy), Buffer.from(this.uvy.buffer, this.uvy.byteOffset, this.uvy.byteLength)),
      fs.writeFile(path.join(dir, FILES.white), Buffer.from(this.white)),
      fs.writeFile(path.join(dir, FILES.black), Buffer.from(this.black)),
      fs.writeFile(path.join(dir, FILES.alpha), Buffer.from(this.alpha)),
    ]);
    log.debug("mapset lagret", { dir, width: this.width, height: this.height });
  }

  static async load(dir) {
    const meta = JSON.parse(await fs.readFile(path.join(dir, "meta.json"), "utf8"));
    if (meta.formatVersion !== MAP_FORMAT_VERSION) {
      throw new Error(
        `kartformat ${meta.formatVersion} stemmer ikke med ${MAP_FORMAT_VERSION} (kalibrer paa nytt)`
      );
    }
    const { width, height } = meta;
    const n = width * height;
    const read = async (f) => fs.readFile(path.join(dir, f));
    const [uvxB, uvyB, whiteB, blackB, alphaB] = await Promise.all([
      read(FILES.uvx), read(FILES.uvy), read(FILES.white), read(FILES.black), read(FILES.alpha),
    ]);
    const asU16 = (b) => new Uint16Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
    const set = new MapSet({
      width, height,
      uvx: asU16(uvxB),
      uvy: asU16(uvyB),
      white: new Uint8Array(whiteB),
      black: new Uint8Array(blackB),
      alpha: new Uint8Array(alphaB),
      meta,
    });
    if (set.uvx.length !== n || set.alpha.length !== n || set.white.length !== n * 3) {
      throw new Error("kartfilene har feil stoerrelse i forhold til meta.json");
    }
    return set;
  }
}

/** Enkel LRU så vi slipper å lese kart fra disk for hver render. */
export class MapCache {
  constructor(maxBytes) {
    this.maxBytes = maxBytes;
    this.bytes = 0;
    this.entries = new Map();
  }

  get(key) {
    const hit = this.entries.get(key);
    if (!hit) return undefined;
    this.entries.delete(key);
    this.entries.set(key, hit);
    return hit;
  }

  set(key, mapSet) {
    if (this.entries.has(key)) {
      this.bytes -= this.entries.get(key).byteLength;
      this.entries.delete(key);
    }
    this.entries.set(key, mapSet);
    this.bytes += mapSet.byteLength;
    while (this.bytes > this.maxBytes && this.entries.size > 1) {
      const [oldestKey, oldest] = this.entries.entries().next().value;
      this.entries.delete(oldestKey);
      this.bytes -= oldest.byteLength;
      log.debug("mapset kastet ut av cache", { key: oldestKey });
    }
  }
}
