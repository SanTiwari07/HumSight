// Runs a demo on the live site and downloads the media the page loads from S3 (original, magnified, heatmap).
// Usage: node fetch_media.js <demo_id> <outDir>
const { chromium } = require("playwright-core");
const fs = require("fs"), path = require("path");
const [demo, OUT] = process.argv.slice(2);
const CHROME = process.env.LOCALAPPDATA + "/ms-playwright/chromium-1243/chrome-win64/chrome.exe";
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await ctx.newPage();
  const urls = new Set();
  page.on("response", (r) => { if (/s3\.amazonaws\.com\/.+\.(webm|mp4|png|json)/.test(r.url())) urls.add(r.url()); });
  await page.goto("https://santiwari07.github.io/HumSight/#/select", { waitUntil: "networkidle" });
  await page.click(`label.clip-card:has(input[value="${demo}"])`);
  await page.click("#toSetup");
  await page.click("#go");
  await page.waitForSelector("#view-report:not([hidden])", { timeout: 170000 });
  for (const t of ["video", "spectrum", "heat"]) { await page.click(`.tabs [data-tab="${t}"]`); await page.waitForTimeout(2500); }
  for (const u of urls) {
    const name = path.basename(new URL(u).pathname);
    const res = await ctx.request.get(u);
    fs.writeFileSync(path.join(OUT, name), await res.body());
    console.log(name, (await res.body()).length);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
