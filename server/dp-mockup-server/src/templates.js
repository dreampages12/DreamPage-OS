/**
 * Malregister: hver mal er ett kartsett + metadata.
 *
 * En mal er enten
 *   kind="psd"         kalibrert fra en opplastet PSD
 *   kind="procedural"  analytisk generert geometri (ingen PSD)
 *
 * Compositoren bryr seg ikke om hvilken - den ser bare kartene.
 */
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { config, RENDERER_VERSION } from "./config.js";
import { MapSet, MapCache } from "./maps.js";
import { buildProceduralMaps, PROCEDURAL_VERSION } from "./renderers/procedural.js";
import { calibratePsd, CALIBRATION_VERSION } from "./renderers/psd.js";
import { log } from "./util/log.js";
import { notFound, badRequest, conflict } from "./util/errors.js";

const mapCache = new MapCache(config.mapCacheMaxBytes);
const inFlight = new Map();

export const sha256 = (buf) => crypto.createHash("sha256").update(buf).digest("hex");

const registryPath = () => path.join(config.dataDir, "templates.json");

async function readRegistry() {
  try {
    return JSON.parse(await fs.readFile(registryPath(), "utf8"));
  } catch (err) {
    if (err.code === "ENOENT") return {};
    throw err;
  }
}

async function writeRegistry(reg) {
  await fs.mkdir(config.dataDir, { recursive: true });
  const tmp = registryPath() + ".tmp";
  await fs.writeFile(tmp, JSON.stringify(reg, null, 2));
  await fs.rename(tmp, registryPath());
}

export async function listTemplates() {
  const reg = await readRegistry();
  return Object.values(reg).map((t) => ({
    id: t.id,
    kind: t.kind,
    label: t.label,
    status: t.status,
    width: t.width,
    height: t.height,
    layerName: t.layerName,
    validation: t.validation,
    createdAt: t.createdAt,
    calibratedAt: t.calibratedAt,
    error: t.error,
  }));
}

export async function getTemplate(id) {
  const reg = await readRegistry();
  const t = reg[id];
  if (!t) throw notFound("template_not_found", `ukjent mal: ${id}`);
  return t;
}

async function upsert(entry) {
  const reg = await readRegistry();
  reg[entry.id] = { ...(reg[entry.id] || {}), ...entry };
  await writeRegistry(reg);
  return reg[entry.id];
}

/* ------------------------------------------------------------------ PSD */

export async function registerPsd(psdBuf, { label, layerName, coverWidth, coverHeight }) {
  if (!layerName) throw badRequest("layer_required", "layerName maa oppgis");
  const digest = sha256(psdBuf).slice(0, 16);
  const id = `psd_${digest}_${layerName.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;

  const psdPath = path.join(config.psdDir, `${digest}.psd`);
  await fs.mkdir(config.psdDir, { recursive: true });
  await fs.writeFile(psdPath, psdBuf);

  const entry = await upsert({
    id,
    kind: "psd",
    label: label || `PSD ${digest}`,
    layerName,
    psdPath,
    psdSha256: sha256(psdBuf),
    coverWidth: coverWidth || 2048,
    coverHeight: coverHeight || 2048,
    status: "uncalibrated",
    calibrationVersion: CALIBRATION_VERSION,
    createdAt: new Date().toISOString(),
    error: null,
  });
  log.info("PSD registrert", { id, bytes: psdBuf.length, layerName });
  return entry;
}

export async function calibrateTemplate(id) {
  const t = await getTemplate(id);
  if (t.kind !== "psd") throw badRequest("not_psd", "bare PSD-maler kan kalibreres");
  if (t.status === "calibrating") throw conflict("already_calibrating", "kalibrering paagaar");

  await upsert({ id, status: "calibrating", error: null });
  try {
    const psdBuf = await fs.readFile(t.psdPath);
    const maps = await calibratePsd(psdBuf, {
      layerName: t.layerName,
      coverWidth: t.coverWidth,
      coverHeight: t.coverHeight,
    });
    const dir = path.join(config.calibDir, id);
    await maps.save(dir);
    mapCache.set(id, maps);
    return await upsert({
      id,
      status: "ready",
      width: maps.width,
      height: maps.height,
      mapsDir: dir,
      validation: maps.meta.validation,
      influenceRatio: maps.meta.influenceRatio,
      coverRect: maps.meta.coverRect,
      calibratedAt: new Date().toISOString(),
      calibrationVersion: CALIBRATION_VERSION,
      error: null,
    });
  } catch (err) {
    await upsert({
      id,
      status: "failed",
      error: { code: err.code || "calibration_failed", message: err.message },
    });
    throw err;
  }
}

/* ----------------------------------------------------------- procedural */

export async function ensureProceduralTemplate(id = "book-square", opts = {}) {
  const reg = await readRegistry();
  const existing = reg[id];
  if (existing?.status === "ready" && existing.proceduralVersion === PROCEDURAL_VERSION) {
    return existing;
  }
  const maps = buildProceduralMaps(opts);
  const dir = path.join(config.calibDir, id);
  await maps.save(dir);
  mapCache.set(id, maps);
  log.info("prosedyral mal bygget", { id, width: maps.width, height: maps.height });
  return upsert({
    id,
    kind: "procedural",
    label: opts.label || "Kvadratisk bok (generert)",
    status: "ready",
    width: maps.width,
    height: maps.height,
    mapsDir: dir,
    proceduralVersion: PROCEDURAL_VERSION,
    createdAt: existing?.createdAt || new Date().toISOString(),
    calibratedAt: new Date().toISOString(),
    error: null,
  });
}

/* ---------------------------------------------------------------- kart */

export async function loadMaps(id) {
  const cached = mapCache.get(id);
  if (cached) return cached;
  if (inFlight.has(id)) return inFlight.get(id);

  const promise = (async () => {
    const t = await getTemplate(id);
    if (t.status !== "ready") {
      throw conflict("template_not_ready",
        `malen ${id} har status "${t.status}" - kalibrer den forst`);
    }
    const maps = await MapSet.load(t.mapsDir);
    mapCache.set(id, maps);
    return maps;
  })().finally(() => inFlight.delete(id));

  inFlight.set(id, promise);
  return promise;
}

/** Alt som påvirker pikslene i resultatet inngår i fingeravtrykket. */
export function fingerprint({ templateId, coverSha, template, options }) {
  const parts = [
    RENDERER_VERSION,
    templateId,
    template.kind === "psd"
      ? `calib${template.calibrationVersion}:${template.psdSha256}:${template.layerName}`
      : `proc${template.proceduralVersion}`,
    coverSha,
    options.format || "png",
    String(options.width || ""),
    String(options.quality || ""),
    options.fit || "cover",
    options.background || "",
  ];
  return crypto.createHash("sha256").update(parts.join("|")).digest("hex").slice(0, 32);
}
