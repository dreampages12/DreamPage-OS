/**
 * Photopea-bro: headless Chrome + Live Messaging API.
 *
 * Brukes KUN til kalibrering - én gang per PSD, ikke per ordre. Produksjons-
 * veien er ren sharp (se composite.js). Det er hele poenget med kalibreringen:
 * å få nettleseren ut av den varme stien.
 *
 * Protokoll: window.postMessage med en streng kjører et Photoshop-script i
 * Photopea. En ArrayBuffer laster en fil. Photopea svarer "done" naar en
 * kommando er ferdig, og sender binærdata tilbake for saveToOE().
 */
import { config } from "./config.js";
import { log } from "./util/log.js";
import { HttpError, Semaphore, withTimeout } from "./util/errors.js";

const gate = new Semaphore(config.photopeaConcurrency);

let browserPromise = null;

async function launch() {
  let puppeteer;
  try {
    puppeteer = (await import("puppeteer")).default;
  } catch {
    throw new HttpError(
      503, "photopea_unavailable",
      "puppeteer er ikke installert - kjor `npm install puppeteer` for aa kalibrere PSD"
    );
  }
  const opts = {
    headless: "new",
    // En 122 MB PSD bruker lang tid både på å lastes og eksporteres. Uten
    // dette faller CDP av på 180 s midt i en evaluate.
    protocolTimeout: Math.max(config.photopeaTimeoutMs * 2, 600_000),
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
      "--js-flags=--max-old-space-size=4096",
    ],
  };
  if (config.chromePath) opts.executablePath = config.chromePath;
  const browser = await puppeteer.launch(opts);
  browser.on("disconnected", () => { browserPromise = null; });
  log.info("photopea: nettleser startet");
  return browser;
}

async function getBrowser() {
  if (!browserPromise) browserPromise = launch();
  try {
    return await browserPromise;
  } catch (err) {
    browserPromise = null;
    throw err;
  }
}

export async function closeBrowser() {
  if (!browserPromise) return;
  try {
    const b = await browserPromise;
    await b.close();
  } catch { /* ignorer */ }
  browserPromise = null;
}

/**
 * Åpner en Photopea-session. Kallbacken får et objekt med:
 *   runScript(js)        -> kjører et Photoshop-script, venter på "done"
 *   loadFile(buffer)     -> åpner en fil (PSD, PNG ...) i Photopea
 *   exportPng()          -> flater ut aktivt dokument og returnerer PNG-bytes
 */
export async function withPhotopea(fn) {
  return gate.run(async () => {
    const browser = await getBrowser();
    const page = await browser.newPage();
    try {
      await page.evaluateOnNewDocument(() => {
        window.__pp = { done: 0, blobs: [], text: [] };
        window.addEventListener("message", (e) => {
          if (e.data === "done") window.__pp.done += 1;
          else if (e.data instanceof ArrayBuffer) window.__pp.blobs.push(e.data);
          else if (typeof e.data === "string") window.__pp.text.push(e.data);
        });
      });

      await page.goto(config.photopeaUrl, {
        waitUntil: "networkidle2",
        timeout: config.photopeaTimeoutMs,
      });
      // Photopea er klar når den har svart på et trivielt script.
      await page.waitForFunction(() => window.app !== undefined, {
        timeout: config.photopeaTimeoutMs,
      });

      const session = {
        async runScript(js) {
          const before = await page.evaluate(() => window.__pp.done);
          await page.evaluate((code) => window.postMessage(code, "*"), js);
          await page.waitForFunction(
            (b) => window.__pp.done > b, { timeout: config.photopeaTimeoutMs }, before
          );
        },
        /** Photopea henter fila selv - se assets.js for hvorfor. */
        async loadFromUrl(url) {
          const before = await page.evaluate(() => window.__pp.done);
          await page.evaluate(async (u) => {
            const res = await fetch(u);
            if (!res.ok) throw new Error("fetch " + u + " -> " + res.status);
            window.postMessage(await res.arrayBuffer(), "*");
          }, url);
          await page.waitForFunction(
            (b) => window.__pp.done > b, { timeout: config.photopeaTimeoutMs }, before
          );
          return page.evaluate(() => app.activeDocument.name);
        },
        async exportPng() {
          await page.evaluate(() => { window.__pp.blobs.length = 0; });
          const before = await page.evaluate(() => window.__pp.done);
          await page.evaluate(() =>
            window.postMessage('app.activeDocument.saveToOE("png");', "*"));
          await page.waitForFunction(
            (b) => window.__pp.done > b && window.__pp.blobs.length > 0,
            { timeout: config.photopeaTimeoutMs }, before
          );
          // Overfør via base64 - CDP kan ikke returnere ArrayBuffer direkte.
          const b64 = await page.evaluate(() => {
            const ab = window.__pp.blobs.shift();
            const bytes = new Uint8Array(ab);
            let s = "";
            const CH = 0x8000;
            for (let i = 0; i < bytes.length; i += CH) {
              s += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
            }
            return btoa(s);
          });
          return Buffer.from(b64, "base64");
        },
        async drainText() {
          return page.evaluate(() => window.__pp.text.splice(0));
        },
      };

      return await withTimeout(
        fn(session), config.photopeaTimeoutMs,
        "photopea_timeout", "Photopea svarte ikke"
      );
    } finally {
      await page.close().catch(() => {});
    }
  });
}

/**
 * Bytter innholdet i et smart object og eksporterer flatt PNG.
 *
 * MERK: dette scriptet må verifiseres mot den konkrete PSD-en. Photopea
 * eksponerer ikke placedLayerEditContents likt i alle versjoner, så
 * kalibreringen logger hvilken variant som lyktes.
 */
/**
 * Bytter innholdet i et smart object og lar dokumentet stå klart til eksport.
 *
 * @param {string} psdName    dokumentnavnet til PSD-en
 * @param {string} coverName  dokumentnavnet til innholdet som skal inn
 * @param {string} layerName  smart object-laget som skal fylles
 */
export function buildReplaceScript(psdName, coverName, layerName) {
  const P = JSON.stringify(psdName);
  const C = JSON.stringify(coverName);
  const L = JSON.stringify(layerName);
  return `
(function () {
  function docByName(n) {
    for (var i = 0; i < app.documents.length; i++) {
      if (app.documents[i].name === n) return app.documents[i];
    }
    return null;
  }
  var psd = docByName(${P});
  var cov = docByName(${C});
  if (!psd) { app.echoToOE("ERR:psd-doc-mangler"); return; }
  if (!cov) { app.echoToOE("ERR:cover-doc-mangler"); return; }

  // 1) kopier innholdet
  app.activeDocument = cov;
  cov.selection.selectAll();
  cov.selection.copy();

  // 2) finn smart object-laget (rekursivt gjennom grupper)
  app.activeDocument = psd;
  var target = null;
  function walk(c) {
    for (var i = 0; i < c.layers.length; i++) {
      var l = c.layers[i];
      if (l.name === ${L}) { target = l; return; }
      if (l.layers && l.layers.length) { walk(l); if (target) return; }
    }
  }
  walk(psd);
  if (!target) { app.echoToOE("ERR:fant-ikke-lag"); return; }
  psd.activeLayer = target;

  // 3) åpne smart-objektet, lim inn, lagre tilbake
  try {
    executeAction(stringIDToTypeID("placedLayerEditContents"),
                  new ActionDescriptor(), DialogModes.NO);
  } catch (e) {
    app.echoToOE("ERR:placedLayerEditContents:" + e.message);
    return;
  }
  var so = app.activeDocument;
  if (so === psd) { app.echoToOE("ERR:smartobjekt-apnet-ikke"); return; }
  try {
    so.selection.selectAll();
    so.paste();
    // Skaler det innlimte til å dekke hele smart-objektets flate.
    var lay = so.activeLayer;
    var b = lay.bounds;
    var lw = b[2] - b[0], lh = b[3] - b[1];
    if (lw > 0 && lh > 0) {
      lay.resize((so.width / lw) * 100, (so.height / lh) * 100, AnchorPosition.MIDDLECENTER);
      lay.translate(so.width / 2 - (lay.bounds[0] + (lay.bounds[2] - lay.bounds[0]) / 2),
                    so.height / 2 - (lay.bounds[1] + (lay.bounds[3] - lay.bounds[1]) / 2));
    }
    so.flatten();
    so.close(SaveOptions.SAVECHANGES);
  } catch (e) {
    app.echoToOE("ERR:paste:" + e.message);
    try { so.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
    return;
  }
  app.activeDocument = psd;
  app.echoToOE("OK");
})();
`;
}
