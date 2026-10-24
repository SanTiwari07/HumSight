// Renders film.html deterministically, frame by frame, at 1920x1080.
//   node render.js stills out_dir t1 t2 ...   -> JPEG stills at those times
//   node render.js video out.mp4 [fps]        -> silent H.264 video piped through ffmpeg
const { chromium } = require("playwright-core");
const { spawn } = require("child_process");
const fs = require("fs"), path = require("path");
const CHROME = process.env.LOCALAPPDATA + "/ms-playwright/chromium-1243/chrome-win64/chrome.exe";
const [mode, out, ...rest] = process.argv.slice(2);

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ["--allow-file-access-from-files"] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "warning" || m.type() === "error") console.log("page:", m.text()); });
  page.on("pageerror", (e) => console.log("pageerror:", e.message));
  await page.goto("file:///" + path.join(__dirname, "film.html").replace(/\\/g, "/") + "?render=1");
  await page.waitForFunction(() => window.render);
  const total = await page.evaluate(() => window.TOTAL);
  const shot = async (t) => { await page.evaluate((t) => window.render(t), t); return page.screenshot({ type: "jpeg", quality: 92 }); };

  if (mode === "stills") {
    fs.mkdirSync(out, { recursive: true });
    for (const s of rest) { fs.writeFileSync(path.join(out, `t${(+s).toFixed(1).padStart(6, "0")}.jpg`), await shot(+s)); }
  } else {
    const fps = +(rest[0] || 30), n = Math.ceil(total * fps);
    const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "mjpeg", "-i", "-",
      "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", String(fps), out], { stdio: ["pipe", "inherit", "inherit"] });
    const t0 = Date.now();
    for (let i = 0; i < n; i++) {
      const buf = await shot(i / fps);
      if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
      if (i % 300 === 0) console.log(`frame ${i}/${n}  ${((Date.now() - t0) / 1000).toFixed(0)} s`);
    }
    ff.stdin.end(); await new Promise((r) => ff.on("close", r));
    console.log("done", n, "frames");
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
