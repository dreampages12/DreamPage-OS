/**
 * Kortlevde assets som Photopea henter selv over HTTP.
 *
 * Alternativet - å sende bytes gjennom postMessage - krever at bufferet
 * marshalles som et JS-array gjennom CDP. For en 122 MB PSD er det titalls
 * millioner tall og flere GB minne. Å la nettleseren fetche fra oss i stedet
 * er både raskere og flatt i minnebruk.
 */
import crypto from "node:crypto";
import { log } from "./util/log.js";

const assets = new Map();
const TTL_MS = 30 * 60 * 1000;

export function putAsset(buffer, contentType = "application/octet-stream") {
  const token = crypto.randomBytes(16).toString("hex");
  assets.set(token, { buffer, contentType, expires: Date.now() + TTL_MS });
  return token;
}

export function getAsset(token) {
  const a = assets.get(token);
  if (!a) return null;
  if (a.expires < Date.now()) {
    assets.delete(token);
    return null;
  }
  return a;
}

export function dropAsset(token) {
  assets.delete(token);
}

const sweep = setInterval(() => {
  const now = Date.now();
  let n = 0;
  for (const [k, v] of assets) {
    if (v.expires < now) { assets.delete(k); n += 1; }
  }
  if (n) log.debug("assets ryddet", { removed: n });
}, 5 * 60 * 1000);
sweep.unref();
