/**
 * Diagnose: svarer Photopea "done" når vi laster en fil, eller bare på scripts?
 * Kjør: node test/photopea-probe.js
 */
import puppeteer from "puppeteer";
import sharp from "sharp";
import http from "node:http";

const png = await sharp({ create: { width: 64, height: 64, channels: 3, background: "#ff0000" } })
  .png().toBuffer();

const srv = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Content-Type", "image/png");
  res.end(png);
}).listen(8791);

const browser = await puppeteer.launch({
  headless: "new",
  protocolTimeout: 300000,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
const page = await browser.newPage();
page.on("console", (m) => console.log("  [console]", m.text().slice(0, 200)));
page.on("pageerror", (e) => console.log("  [pageerror]", e.message.slice(0, 200)));

await page.evaluateOnNewDocument(() => {
  window.__pp = { msgs: [] };
  window.addEventListener("message", (e) => {
    window.__pp.msgs.push(
      typeof e.data === "string" ? e.data
        : e.data instanceof ArrayBuffer ? `<ArrayBuffer ${e.data.byteLength}>`
        : `<${typeof e.data}>`
    );
  });
});

console.log("1) laster photopea ...");
await page.goto("https://www.photopea.com", { waitUntil: "networkidle2", timeout: 120000 });
await page.waitForFunction(() => window.app !== undefined, { timeout: 120000 });
console.log("   app finnes:", await page.evaluate(() => typeof window.app));

console.log("2) kjorer et trivielt script ...");
await page.evaluate(() => window.postMessage("app.echoToOE('hei');", "*"));
await new Promise((r) => setTimeout(r, 3000));
console.log("   meldinger:", await page.evaluate(() => window.__pp.msgs.slice()));

console.log("3) laster en 64x64 PNG via fetch+postMessage ...");
await page.evaluate(async () => {
  const r = await fetch("http://127.0.0.1:8791/x.png");
  window.postMessage(await r.arrayBuffer(), "*");
});
await new Promise((r) => setTimeout(r, 6000));
console.log("   meldinger:", await page.evaluate(() => window.__pp.msgs.slice()));
console.log("   dokumenter:", await page.evaluate(() =>
  window.app ? window.app.documents.length : -1));
console.log("   aktivt dok:", await page.evaluate(() =>
  window.app && window.app.documents.length ? window.app.activeDocument.name : "(ingen)"));

await browser.close();
srv.close();
