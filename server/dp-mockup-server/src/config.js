import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

const num = (v, d) => (v === undefined || v === "" ? d : Number(v));
const bool = (v, d) => (v === undefined || v === "" ? d : /^(1|true|yes|on)$/i.test(v));

export const config = {
  port: num(process.env.MOCKUP_PORT, 8790),
  host: process.env.MOCKUP_HOST || "127.0.0.1",

  // Delt hemmelighet, samme mønster som order-progress og continue-callback.
  // Tom verdi = auth av (kun for lokal utvikling).
  secret: process.env.MOCKUP_SECRET || "",
  secretHeader: "x-dreampage-secret",

  dataDir: process.env.MOCKUP_DATA_DIR || path.join(ROOT, "data"),
  get psdDir() { return path.join(this.dataDir, "psd"); },
  get calibDir() { return path.join(this.dataDir, "calib"); },
  get cacheDir() { return path.join(this.dataDir, "cache"); },
  get jobsDir() { return path.join(this.dataDir, "jobs"); },

  // Hvor mange renders som kjører samtidig. Boksen deler CPU med ComfyUI,
  // så standarden er bevisst lav.
  concurrency: num(process.env.MOCKUP_CONCURRENCY, 2),
  // Photopea kjører i en nettleser og tåler ikke parallellitet.
  photopeaConcurrency: 1,

  renderTimeoutMs: num(process.env.MOCKUP_RENDER_TIMEOUT_MS, 60_000),
  photopeaTimeoutMs: num(process.env.MOCKUP_PHOTOPEA_TIMEOUT_MS, 180_000),
  photopeaUrl: process.env.MOCKUP_PHOTOPEA_URL || "https://www.photopea.com",
  chromePath: process.env.MOCKUP_CHROME_PATH || "",

  maxUploadBytes: num(process.env.MOCKUP_MAX_UPLOAD_BYTES, 64 * 1024 * 1024),
  maxOutputPx: num(process.env.MOCKUP_MAX_OUTPUT_PX, 4096),

  cacheEnabled: bool(process.env.MOCKUP_CACHE, true),
  cacheMaxEntries: num(process.env.MOCKUP_CACHE_MAX_ENTRIES, 500),
  mapCacheMaxBytes: num(process.env.MOCKUP_MAP_CACHE_BYTES, 512 * 1024 * 1024),

  jobTtlMs: num(process.env.MOCKUP_JOB_TTL_MS, 6 * 60 * 60 * 1000),

  // Kalibrering godtas bare hvis modellen treffer validerings-rendene.
  calibMaxMeanError: num(process.env.MOCKUP_CALIB_MAX_MEAN_ERROR, 2.5),
  calibMaxP99Error: num(process.env.MOCKUP_CALIB_MAX_P99_ERROR, 12),

  logLevel: process.env.MOCKUP_LOG_LEVEL || "info",
};

/** URL Photopea bruker for å hente kalibreringsfiler fra oss. */
config.publicBaseUrl =
  process.env.MOCKUP_PUBLIC_BASE_URL || `http://127.0.0.1:${config.port}`;

/**
 * Bump denne når renderlogikken endrer seg på en måte som gir et annet bilde.
 * Den inngår i fingeravtrykket, så alle cachede renders blir ugyldige og
 * kallere som lagrer rendererVersion vet at de må rendre på nytt.
 */
export const RENDERER_VERSION = "2026.08.07-1";

export { ROOT };
