import express from "express";
import multer from "multer";
import fs from "node:fs/promises";
import path from "node:path";
import { config, RENDERER_VERSION } from "./config.js";
import { log } from "./util/log.js";
import { HttpError, Semaphore, badRequest, notFound, withTimeout } from "./util/errors.js";
import { renderMockup } from "./composite.js";
import {
  listTemplates, getTemplate, registerPsd, calibrateTemplate,
  ensureProceduralTemplate, loadMaps, fingerprint, sha256,
} from "./templates.js";
import { createJob, getJob, getJobResult, sweepJobs } from "./jobs.js";
import { closeBrowser } from "./photopea.js";
import { getAsset } from "./assets.js";

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "2mb" }));

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.maxUploadBytes },
});
const renderGate = new Semaphore(config.concurrency);

/* ------------------------------------------------------------ middleware */

app.use((req, res, next) => {
  const started = Date.now();
  res.on("finish", () => {
    const level = res.statusCode >= 500 ? "error" : res.statusCode >= 400 ? "warn" : "info";
    log[level]("http", {
      method: req.method, path: req.path, status: res.statusCode,
      ms: Date.now() - started,
    });
  });
  next();
});

function requireSecret(req, _res, next) {
  if (!config.secret) return next();
  const got = req.get(config.secretHeader);
  if (got !== config.secret) {
    return next(new HttpError(401, "unauthorized", "mangler eller feil X-DreamPage-Secret"));
  }
  next();
}

/* ---------------------------------------------------------------- helse */

app.get("/healthz", (_req, res) => {
  res.json({
    ok: true,
    renderer_version: RENDERER_VERSION,
    queue_depth: renderGate.depth,
    active: renderGate.active,
    uptime_s: Math.round(process.uptime()),
  });
});

/**
 * Kalibreringsfiler som Photopea henter selv. Tokenet er tilfeldig og
 * kortlevd, og ruta serverer bare det kalibreringen selv har lagt inn -
 * aldri en vilkårlig sti fra disk.
 */
app.get("/calib-asset/:token", (req, res) => {
  const asset = getAsset(req.params.token);
  if (!asset) return res.status(404).json({ ok: false, error: { code: "asset_expired" } });
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", asset.contentType);
  res.setHeader("Cache-Control", "no-store");
  res.send(asset.buffer);
});

app.get("/v1/templates", requireSecret, async (_req, res, next) => {
  try {
    res.json({ templates: await listTemplates() });
  } catch (err) { next(err); }
});

app.get("/v1/templates/:id", requireSecret, async (req, res, next) => {
  try {
    const t = await getTemplate(req.params.id);
    res.json({
      id: t.id, kind: t.kind, label: t.label, status: t.status,
      width: t.width, height: t.height, layer_name: t.layerName,
      validation: t.validation, influence_ratio: t.influenceRatio,
      cover_rect: t.coverRect,
      calibrated_at: t.calibratedAt, error: t.error,
    });
  } catch (err) { next(err); }
});

/* ------------------------------------------------------------------ PSD */

app.post("/v1/templates/psd", requireSecret, upload.single("psd"), async (req, res, next) => {
  try {
    let psdBuf = req.file?.buffer;
    if (!psdBuf && req.body?.psd_path) {
      psdBuf = await fs.readFile(req.body.psd_path);
    }
    if (!psdBuf) throw badRequest("psd_required", "last opp feltet 'psd' eller oppgi psd_path");
    const entry = await registerPsd(psdBuf, {
      label: req.body?.label,
      layerName: req.body?.layer_name,
      coverWidth: Number(req.body?.cover_width) || undefined,
      coverHeight: Number(req.body?.cover_height) || undefined,
    });
    res.status(201).json({ id: entry.id, status: entry.status, layer_name: entry.layerName });
  } catch (err) { next(err); }
});

app.post("/v1/templates/:id/calibrate", requireSecret, async (req, res, next) => {
  try {
    const job = await createJob(async () => {
      const t = await calibrateTemplate(req.params.id);
      return {
        buffer: Buffer.from(JSON.stringify(t.validation ?? {}, null, 2)),
        format: "json", width: t.width, height: t.height,
      };
    }, { maxAttempts: 1 });
    res.status(202).json(job);
  } catch (err) { next(err); }
});

/* --------------------------------------------------------------- render */

function parseOptions(src = {}) {
  const opts = {
    format: (src.format || "png").toLowerCase(),
    fit: src.fit === "contain" ? "contain" : "cover",
    background: src.background || "#ffffff",
  };
  if (src.width) {
    const w = Number(src.width);
    if (!Number.isFinite(w) || w < 32 || w > config.maxOutputPx) {
      throw badRequest("bad_width", `width maa vaere mellom 32 og ${config.maxOutputPx}`);
    }
    opts.width = Math.round(w);
  }
  if (src.quality) opts.quality = Math.min(100, Math.max(40, Number(src.quality)));
  if (!["png", "jpeg", "jpg", "webp"].includes(opts.format)) {
    throw badRequest("bad_format", "format maa vaere png, jpeg eller webp");
  }
  return opts;
}

async function resolveCover(req) {
  if (req.file?.buffer) return req.file.buffer;
  const body = req.body || {};
  if (body.cover_base64) return Buffer.from(body.cover_base64, "base64");
  if (body.cover_path) {
    const p = path.resolve(String(body.cover_path));
    return fs.readFile(p);
  }
  throw badRequest("cover_required", "oppgi 'cover' (fil), cover_base64 eller cover_path");
}

async function doRender(templateId, coverBuf, options) {
  const template = await getTemplate(templateId);
  const coverSha = sha256(coverBuf);
  const fp = fingerprint({ templateId, coverSha, template, options });
  const ext = options.format === "jpeg" || options.format === "jpg" ? "jpg" : options.format;
  const cachePath = path.join(config.cacheDir, `${fp}.${ext}`);

  if (config.cacheEnabled) {
    try {
      const buf = await fs.readFile(cachePath);
      return { buffer: buf, format: options.format, fingerprint: fp, cached: true,
               width: template.width, height: template.height, renderMs: 0,
               coverRect: template.coverRect };
    } catch { /* ikke i cache */ }
  }

  const maps = await loadMaps(templateId);
  const result = await renderGate.run(() =>
    withTimeout(renderMockup(coverBuf, maps, options),
      config.renderTimeoutMs, "render_timeout", "rendringen tok for lang tid")
  );

  if (config.cacheEnabled) {
    await fs.mkdir(config.cacheDir, { recursive: true });
    await fs.writeFile(cachePath, result.buffer).catch((err) =>
      log.warn("kunne ikke skrive cache", { err: err.message }));
  }

  return { ...result, fingerprint: fp, cached: false, renderMs: result.ms,
           coverRect: template.coverRect };
}

const CONTENT_TYPE = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp" };

app.post("/v1/mockup", requireSecret, upload.single("cover"), async (req, res, next) => {
  try {
    const templateId = req.body?.template_id || req.query.template_id;
    if (!templateId) throw badRequest("template_required", "template_id maa oppgis");
    const options = parseOptions({ ...req.query, ...req.body });
    const coverBuf = await resolveCover(req);
    const out = await doRender(templateId, coverBuf, options);

    res.setHeader("Content-Type", CONTENT_TYPE[out.format] || "application/octet-stream");
    res.setHeader("X-Mockup-Fingerprint", out.fingerprint);
    res.setHeader("X-Mockup-Cached", String(out.cached));
    res.setHeader("X-Renderer-Version", RENDERER_VERSION);
    if (out.coverRect) res.setHeader("X-Mockup-Cover-Rect", out.coverRect.join(","));
    res.send(out.buffer);
  } catch (err) { next(err); }
});

app.post("/v1/jobs", requireSecret, upload.single("cover"), async (req, res, next) => {
  try {
    const templateId = req.body?.template_id;
    if (!templateId) throw badRequest("template_required", "template_id maa oppgis");
    const options = parseOptions(req.body);
    const coverBuf = await resolveCover(req);
    const job = await createJob(() => doRender(templateId, coverBuf, options));
    res.status(202).json(job);
  } catch (err) { next(err); }
});

app.get("/v1/jobs/:id", requireSecret, async (req, res, next) => {
  try {
    res.json(await getJob(req.params.id));
  } catch (err) { next(err); }
});

app.get("/v1/jobs/:id/result", requireSecret, async (req, res, next) => {
  try {
    const { buffer, format } = await getJobResult(req.params.id);
    res.setHeader("Content-Type", CONTENT_TYPE[format] || "application/json");
    res.send(buffer);
  } catch (err) { next(err); }
});

/* ------------------------------------------------------------ feilhaand */

app.use((_req, _res, next) => next(notFound("no_route", "ukjent endepunkt")));

app.use((err, _req, res, _next) => {
  const status = err.status || 500;
  if (status >= 500) log.error("uventet feil", { err: err.message, stack: err.stack });
  res.status(status).json({
    ok: false,
    error: { code: err.code || "internal_error", message: err.message, details: err.details },
  });
});

/* ------------------------------------------------------------- oppstart */

async function main() {
  for (const dir of [config.dataDir, config.psdDir, config.calibDir, config.cacheDir, config.jobsDir]) {
    await fs.mkdir(dir, { recursive: true });
  }
  // Den prosedyrale malen er alltid tilgjengelig, også før PSD er kalibrert.
  await ensureProceduralTemplate("book-square");

  const server = app.listen(config.port, config.host, () => {
    log.info("dp-mockup-server lytter", {
      url: `http://${config.host}:${config.port}`,
      rendererVersion: RENDERER_VERSION,
      concurrency: config.concurrency,
      auth: config.secret ? "paa" : "AV (ingen MOCKUP_SECRET satt)",
    });
  });

  const sweep = setInterval(() => sweepJobs().catch(() => {}), 30 * 60 * 1000);
  sweep.unref();

  const shutdown = async (sig) => {
    log.info("avslutter", { sig });
    clearInterval(sweep);
    server.close();
    await closeBrowser();
    setTimeout(() => process.exit(0), 500).unref();
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((err) => {
  log.error("oppstart feilet", { err: err.message, stack: err.stack });
  process.exit(1);
});
