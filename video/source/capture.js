// Records real runs on the live HumSight site (GitHub Pages -> AWS Lambda) as CDP screencast frames.
// Usage: node capture.js <outDir>
const { chromium } = require("playwright-core");
const fs = require("fs"), path = require("path");
const OUT = process.argv[2] || "rec";
const SITE = "https://santiwari07.github.io/HumSight/";
const CHROME = process.env.LOCALAPPDATA + "/ms-playwright/chromium-1243/chrome-win64/chrome.exe";

const CURSOR = `
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id='__cur';
    c.style.cssText='position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-3px,-2px);transition:none';
    c.innerHTML='<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    addEventListener('mousemove', e => { c.style.left=e.clientX+'px'; c.style.top=e.clientY+'px'; }, true);
    addEventListener('mousedown', e => {
      const r=document.createElement('div');
      r.style.cssText='position:fixed;left:'+(e.clientX-18)+'px;top:'+(e.clientY-18)+'px;width:36px;height:36px;border-radius:50%;border:3px solid #2f6fed;z-index:2147483646;pointer-events:none;opacity:.9;transition:transform .45s ease-out,opacity .45s ease-out';
      document.body.appendChild(r); requestAnimationFrame(()=>{r.style.transform='scale(1.8)';r.style.opacity='0'}); setTimeout(()=>r.remove(),500);
    }, true);
  };
  if (document.body) add(); else addEventListener('DOMContentLoaded', add);
})();`;

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  let seg = null, n = 0, mouse = { x: 640, y: 360 };
  cdp.on("Page.screencastFrame", async (f) => {
    try { await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch {}
    if (!seg) return;
    const name = String(n++).padStart(6, "0") + ".jpg";
    fs.writeFileSync(path.join(seg.dir, name), Buffer.from(f.data, "base64"));
    seg.frames.push({ name, t: f.metadata.timestamp });
  });
  const mark = (label) => { seg.marks.push({ label, t: Date.now() / 1000 }); console.log(seg.id, label); };
  async function start(id) {
    const dir = path.join(OUT, id); fs.mkdirSync(dir, { recursive: true });
    seg = { id, dir, frames: [], marks: [] }; n = 0;
    await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
    mark("start");
  }
  async function stop() {
    mark("end");
    await cdp.send("Page.stopScreencast");
    fs.writeFileSync(path.join(seg.dir, "index.json"), JSON.stringify(seg, null, 1));
    seg = null;
  }
  const wait = (ms) => page.waitForTimeout(ms);
  async function moveTo(loc) {
    await loc.evaluate((e) => { const r = e.getBoundingClientRect(); if (r.top < 70 || r.bottom > innerHeight - 90) e.scrollIntoView({ block: "center", behavior: "instant" }); });
    await wait(150);
    const b = await loc.boundingBox();
    const x = b.x + Math.min(b.width / 2, 90), y = b.y + b.height / 2;
    await page.mouse.move(x, y, { steps: 28 }); mouse = { x, y };
    await wait(250);
  }
  async function click(loc) { await moveTo(loc); await page.mouse.down(); await page.mouse.up(); await wait(400); }
  // keep frames flowing while nothing changes (screencast only sends on change)
  async function hold(ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) { await page.mouse.move(mouse.x + 0.5, mouse.y); await page.mouse.move(mouse.x, mouse.y); await wait(90); }
  }
  async function pickDemo(id) {
    await page.waitForSelector(`#demoList input[value="${id}"]`, { timeout: 30000 });
    await click(page.locator(`label.clip-card:has(input[value="${id}"])`));
    await hold(700);
    await click(page.locator("#toSetup"));
    await hold(1500);
  }
  async function run(policy) {
    if (policy) { await click(page.locator(`label.method:has(input[value="${policy}"])`)); await hold(600); }
    await click(page.locator("#go")); mark("run_clicked");
    await page.waitForSelector("#view-report:not([hidden])", { timeout: 170000 });
    mark("report_shown");
    await hold(2500);
  }
  async function tab(name, ms) { await click(page.locator(`.tabs [data-tab="${name}"]`)); await hold(ms); }
  async function playVideo(ms) {
    await page.evaluate(() => { const s = document.getElementById("rate"); s.value = "0.25"; s.dispatchEvent(new Event("change", { bubbles: true })); });
    await page.evaluate(() => document.getElementById("vids").scrollIntoView({ block: "start", behavior: "instant" }));
    await page.evaluate(() => scrollBy(0, -70));
    await click(page.locator("#play")); await hold(ms);
  }

  await page.goto(SITE + "#/select", { waitUntil: "networkidle" });
  await page.waitForSelector('#demoList input[value="pump_shake_fault"]', { timeout: 60000 });
  await page.mouse.move(640, 360);

  // 1. pump, agent with rules
  await start("pump_agent");
  await hold(1500);
  await pickDemo("pump_shake_fault");
  await run("rules");
  await page.evaluate(() => scrollTo(0, 0)); await hold(2500);
  await tab("video", 400); await playVideo(7000);
  await tab("spectrum", 3500);
  await tab("heat", 3500);
  await tab("log", 1500);
  await page.mouse.wheel(0, 500); await hold(2500); await page.mouse.wheel(0, 500); await hold(2500);
  await tab("wo", 3000);
  await stop();

  // 2. same clip, fixed pipeline
  await page.evaluate(() => scrollTo(0, 0));
  await start("pump_fixed");
  await click(page.locator('#view-report a[href="#/setup"]').first());
  await hold(1000);
  await run("fixed");
  await page.evaluate(() => scrollTo(0, 0)); await hold(3000);
  await tab("video", 400); await playVideo(6000);
  await tab("spectrum", 3500);
  await stop();

  // 3. aliasing clip
  await page.evaluate(() => scrollTo(0, 0));
  await start("alias");
  await click(page.locator("#newRun"));
  await hold(800);
  await pickDemo("alias_130hz");
  await run("rules");
  await page.evaluate(() => scrollTo(0, 0)); await hold(4000);
  await tab("log", 3000);
  await stop();

  // 4. real washing machine
  await page.evaluate(() => scrollTo(0, 0));
  await start("washer");
  await click(page.locator("#newRun"));
  await hold(800);
  await pickDemo("real_washer");
  await run("rules");
  await page.evaluate(() => scrollTo(0, 0)); await hold(3000);
  await tab("video", 400); await playVideo(7000);
  await tab("spectrum", 3500);
  await stop();

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
