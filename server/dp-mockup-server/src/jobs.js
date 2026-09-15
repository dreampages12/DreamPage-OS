/**
 * Asynkron jobb-livssyklus: start -> poll -> result.
 *
 * Rendringen tar ~100-300 ms, så det synkrone endepunktet er hovedveien. Den
 * asynkrone finnes for kallere som ikke vil holde en HTTP-forbindelse åpen
 * (n8n, og fremtidige batch-jobber), og for at en render aldri skal gå tapt
 * fordi en klient mistet nettet.
 */
import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { config } from "./config.js";
import { log } from "./util/log.js";
import { notFound } from "./util/errors.js";

const jobs = new Map();

const jobFile = (id) => path.join(config.jobsDir, `${id}.json`);
const resultFile = (id, ext) => path.join(config.jobsDir, `${id}.${ext}`);

function publicView(job) {
  const { id, status, createdAt, startedAt, finishedAt, error, meta, attempts } = job;
  return {
    job_id: id,
    status,
    created_at: createdAt,
    started_at: startedAt,
    finished_at: finishedAt,
    attempts,
    error: error || null,
    ...(status === "done"
      ? {
          result_url: `/v1/jobs/${id}/result`,
          fingerprint: meta?.fingerprint,
          cached: meta?.cached ?? false,
          width: meta?.width,
          height: meta?.height,
          render_ms: meta?.renderMs,
        }
      : {}),
  };
}

export async function createJob(runner, { maxAttempts = 2 } = {}) {
  const id = crypto.randomUUID();
  const job = {
    id,
    status: "queued",
    createdAt: new Date().toISOString(),
    startedAt: null,
    finishedAt: null,
    attempts: 0,
    error: null,
    meta: null,
  };
  jobs.set(id, job);
  await fs.mkdir(config.jobsDir, { recursive: true });
  persist(job);

  // Kjør i bakgrunnen; klienten poller.
  (async () => {
    job.status = "running";
    job.startedAt = new Date().toISOString();
    persist(job);
    let lastError;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      job.attempts = attempt;
      try {
        const { buffer, format, ...meta } = await runner();
        const ext = format === "jpeg" ? "jpg" : format;
        await fs.writeFile(resultFile(id, ext), buffer);
        job.meta = { ...meta, format, ext };
        job.status = "done";
        job.finishedAt = new Date().toISOString();
        persist(job);
        return;
      } catch (err) {
        lastError = err;
        log.warn("jobb feilet", { job: id, attempt, err: err.message });
        if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, 400 * attempt));
      }
    }
    job.status = "failed";
    job.finishedAt = new Date().toISOString();
    job.error = { code: lastError?.code || "render_failed", message: lastError?.message };
    persist(job);
  })();

  return publicView(job);
}

function persist(job) {
  fs.writeFile(jobFile(job.id), JSON.stringify(job, null, 2)).catch((err) =>
    log.warn("kunne ikke lagre jobbstatus", { job: job.id, err: err.message })
  );
}

export async function getJob(id) {
  let job = jobs.get(id);
  if (!job) {
    try {
      job = JSON.parse(await fs.readFile(jobFile(id), "utf8"));
      jobs.set(id, job);
    } catch {
      throw notFound("job_not_found", `ukjent jobb: ${id}`);
    }
  }
  return publicView(job);
}

export async function getJobResult(id) {
  const job = jobs.get(id) || JSON.parse(await fs.readFile(jobFile(id), "utf8").catch(() => "null"));
  if (!job) throw notFound("job_not_found", `ukjent jobb: ${id}`);
  if (job.status !== "done") {
    throw notFound("job_not_done", `jobben har status "${job.status}"`);
  }
  const buf = await fs.readFile(resultFile(id, job.meta.ext));
  return { buffer: buf, format: job.meta.format };
}

/** Rydder jobber og resultatfiler eldre enn TTL. */
export async function sweepJobs() {
  const cutoff = Date.now() - config.jobTtlMs;
  let removed = 0;
  let entries;
  try {
    entries = await fs.readdir(config.jobsDir);
  } catch {
    return 0;
  }
  for (const name of entries) {
    const full = path.join(config.jobsDir, name);
    try {
      const st = await fs.stat(full);
      if (st.mtimeMs < cutoff) {
        await fs.rm(full, { force: true });
        jobs.delete(path.parse(name).name);
        removed += 1;
      }
    } catch { /* ignorer */ }
  }
  if (removed) log.info("gamle jobber ryddet", { removed });
  return removed;
}
