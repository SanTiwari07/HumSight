"use strict";
// HumSight front-end. Two backends behind one UI:
//  * server (local / EC2): POST /api/jobs, live trace over SSE
//  * lambda (public):     POST /jobs returns the finished job; the recorded trace is replayed
const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const BASE = (qs.get("api") || window.API_BASE || "").replace(/\/$/, "");
let PREFIX = "/api";       // "/api" for the FastAPI server, "" for Lambda
let MODE = "server";
let chart = null;

const abs = (u) => (!u ? u : /^https?:/.test(u) ? u : BASE + u);
const hdrs = () => (window.DEMO_TOKEN ? { "X-Demo-Token": window.DEMO_TOKEN } : {});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, opts = {}) {
  opts.headers = { ...hdrs(), ...(opts.headers || {}) };
  const r = await fetch(BASE + PREFIX + path, opts);
  if (!r.ok) throw new Error((await r.text().catch(() => "")) || r.statusText);
  return r.json();
}

async function init() {
  if (window.REPO_URL) $("repoLink").href = window.REPO_URL;
  if (window.VIDEO_URL) { $("videoLink").href = window.VIDEO_URL; $("videoLink").hidden = false; }
  let h = null;
  for (const p of ["/api", ""]) {
    try { PREFIX = p; h = await api("/health"); break; } catch (e) { h = null; }
  }
  if (!h) { $("envBadge").textContent = "API unreachable"; $("go").disabled = true; return; }
  MODE = h.mode || "server";
  const tag = h.cool ? "COOL OpenCV" : "OpenCV " + h.cv2_version;
  $("envBadge").textContent = `${tag} · ${h.machine || ""} · LLM: ${h.llm}`;
  $("envBadge").className = "badge " + (h.cool ? "ok" : "muted");
  $("envBadge").title = h.cv2_path || "";
  if (MODE === "lambda") $("replayTag").hidden = false;
  if (h.llm !== "gemini") {
    const r = document.querySelector('input[value="llm"]');
    r.disabled = true; r.parentElement.title = "No Gemini key configured: falls back to rules";
  }
  try {
    const demos = await api("/demo-clips");
    for (const d of demos) {
      const o = document.createElement("option");
      o.value = d.id; o.textContent = d.title; o.dataset.fps = d.fps; o.dataset.params = JSON.stringify(d.params || {});
      $("demo").appendChild(o);
    }
  } catch (e) { /* no demos */ }
  $("demo").onchange = onDemo;
  $("form").onsubmit = submit;
  wireVideoControls();
}

function onDemo() {
  const o = $("demo").selectedOptions[0];
  const isDemo = !!o.value;
  $("uploadRow").style.display = isDemo ? "none" : "";
  if (isDemo) {
    $("fps").value = o.dataset.fps || "";
    const p = JSON.parse(o.dataset.params || "{}");
    $("expHz").value = p.expected_hz ?? ""; $("rpm").value = p.rpm ?? "";
    $("fmin").value = p.f_min ?? ""; $("fmax").value = p.f_max ?? ""; $("mmpx").value = p.mm_per_px ?? "";
  }
}

function fields() {
  const f = {};
  const put = (k, id) => { const v = $(id).value; if (v !== "") f[k] = v; };
  put("capture_fps", "fps"); put("expected_hz", "expHz"); put("rpm", "rpm");
  put("f_min", "fmin"); put("f_max", "fmax"); put("mm_per_px", "mmpx");
  f.policy = document.querySelector('input[name="policy"]:checked').value;
  return f;
}

async function submit(ev) {
  ev.preventDefault();
  $("err").hidden = true; $("go").disabled = true; $("results").hidden = true;
  $("trace").innerHTML = "";
  try {
    const demo = $("demo").value, file = $("file").files[0];
    if (!demo && !file) throw new Error("Choose a demo clip or a file.");
    if (MODE === "lambda") await runLambda(demo, file); else await runServer(demo, file);
  } catch (e) {
    $("err").textContent = String(e.message || e); $("err").hidden = false;
  } finally { $("go").disabled = false; }
}

// ---- server mode: live SSE trace ------------------------------------------------------
async function runServer(demo, file) {
  const fd = new FormData();
  const f = fields();
  for (const k in f) fd.append(k, f[k]);
  if (demo) fd.append("demo_id", demo); else fd.append("file", file);
  const { job_id } = await api("/jobs", { method: "POST", body: fd });
  await new Promise((resolve, reject) => {
    const es = new EventSource(BASE + PREFIX + `/jobs/${job_id}/events`);
    es.addEventListener("trace", (m) => addTrace(JSON.parse(m.data)));
    es.addEventListener("done", async (m) => {
      es.close();
      const d = JSON.parse(m.data);
      if (d.status === "error") return reject(new Error(d.error || "job failed"));
      const r = await api(`/jobs/${job_id}`);
      showResult(r.result); resolve();
    });
    es.onerror = () => { es.close(); reject(new Error("event stream lost")); };
  });
}

// ---- lambda mode: synchronous job, then replay the recorded trace -----------------------
async function runLambda(demo, file) {
  const body = { ...fields() };
  if (demo) body.demo_id = demo;
  else {
    const up = await api("/upload-url", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ filename: file.name, content_type: file.type || "video/mp4" }) });
    const put = await fetch(up.put_url, { method: "PUT", body: file, headers: { "content-type": file.type || "video/mp4" } });
    if (!put.ok) throw new Error("upload failed");
    body.key = up.key;
  }
  addNote("Running on AWS Lambda… (the trace is replayed after the job finishes)");
  const res = await api("/jobs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  $("trace").innerHTML = "";
  for (const ev of res.trace || []) { addTrace(ev); await sleep(400); }
  showResult(res);
}

// ---- trace rendering ----------------------------------------------------------------------
const fmt = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(1) : +v.toPrecision(4)) : v);
function keyNums(tool, r) {
  if (!r) return "";
  const pick = {
    probe_clip: ["fps", "f_nyquist", "delta_f", "texture_coverage"],
    scan_motion: ["noise_floor_px", "runtime_ms"],
    compensate_shake: ["method", "bg_peak_hz", "bg_amp_px", "residual_at_shake_px", "inlier_ratio"],
    classify_peaks: ["noise_floor_px", "min_detectable_px", "alias_risk", "lighting_flicker"],
    magnify: ["artifact_ratio", "alpha_effective", "slowdown"],
    assess_severity: ["amp_mm", "v_rms_mm_s", "zone"],
    fixed_pipeline: ["verdict"],
  }[tool] || [];
  let parts = pick.filter((k) => r[k] !== undefined && r[k] !== null).map((k) => `${k}=${fmt(r[k])}`);
  if (r.top_peaks && r.top_peaks[0]) { const p = r.top_peaks[0]; parts.push(`top: ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px, SNR ${fmt(p.snr)}`); }
  if (r.background_peaks && r.background_peaks[0]) { const p = r.background_peaks[0]; parts.push(`background: ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px`); }
  if (r.faults && r.faults[0]) { const p = r.faults[0]; parts.push(`fault: ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px, SNR ${fmt(p.snr)}`); }
  else if (tool === "classify_peaks") parts.push("faults: none");
  if (r.shake && r.shake[0]) parts.push(`shake rejected: ${fmt(r.shake[0].f_hz)} Hz`);
  if (r.refined) parts.push(`refined: ${fmt(r.refined.f_hz)} Hz, ${fmt(r.refined.amp_px)} px`);
  if (r.verdict) parts.push(`verdict=${r.verdict}`);
  if (r.state) parts.push(`state=${r.state}: ${r.reason}`);
  if (r.error) parts.push(`error: ${r.error}`);
  return parts.join(" · ");
}
function addTrace(ev) {
  if (ev.kind === "note") return addNote(ev.rationale || ev.result.message);
  const li = document.createElement("li");
  const src = (ev.source || "").startsWith("llm") ? "LLM" : (ev.source || "").startsWith("fixed") ? "FIXED" : "RULES";
  li.innerHTML = `<div class="hd"><span class="n">#${ev.step}</span><span class="tool">${esc(ev.tool)}</span>
    <span class="src ${src.toLowerCase()}">${src}</span><span class="n">${fmt(ev.runtime_ms || 0)} ms</span></div>
    ${ev.rationale ? `<p class="why">${esc(ev.rationale)}</p>` : ""}
    <p class="nums">${esc(keyNums(ev.tool, ev.result))}</p>`;
  $("trace").appendChild(li);
}
function addNote(msg) {
  const li = document.createElement("li"); li.className = "note"; li.textContent = msg; $("trace").appendChild(li);
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- results ----------------------------------------------------------------------------------
async function showResult(r) {
  $("results").hidden = false;
  const v = r.verdict || "REVIEW";
  $("verdict").textContent = v.replace("_", " "); $("verdict").className = "verdict " + v;
  $("summary").textContent = r.summary || r.reason || "";
  const u = r.urls || {};
  setVideo($("vOrig"), abs(u.original || u.source));
  setVideo($("vMag"), abs(u.magnified));
  $("magCap").textContent = "Magnified" + (u.magnified ? " (ROI only, slowed, motion amplified)" : " (none: no fault isolated)");
  $("heat").src = abs(u.heatmap) || ""; $("heat").hidden = !u.heatmap;
  const tb = $("findings").querySelector("tbody"); tb.innerHTML = "";
  for (const f of r.findings || []) {
    tb.insertAdjacentHTML("beforeend", `<tr><td>${fmt(f.f_hz)}</td><td>${fmt(f.amp_px)}</td><td>${fmt(f.snr)}</td><td>${esc(JSON.stringify(f.roi))}</td></tr>`);
  }
  if (!(r.findings || []).length) tb.innerHTML = `<tr><td colspan="4">${v === "REVIEW" ? esc(r.reason || "review needed") + (r.suggestion ? " — " + esc(r.suggestion) : "") : "No fault found."}</td></tr>`;
  const s = r.severity;
  $("sev").textContent = s ? `Severity (indicative): ${s.v_rms_mm_s != null ? fmt(s.v_rms_mm_s) + " mm/s RMS · " : ""}${s.note}` : "";
  $("warn").textContent = (r.warnings || []).length ? "Warnings: " + r.warnings.join("; ") : "";
  $("dlMd").href = abs(u.work_order_md) || "#"; $("dlJson").href = abs(u.work_order_json) || "#";
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  if (u.spectrum) {
    try { drawChart(await (await fetch(abs(u.spectrum))).json()); } catch (e) { /* chart is optional */ }
  } else if (chart) { chart.destroy(); chart = null; }
}

function setVideo(el, url) { el.src = url || ""; el.parentElement.hidden = !url; el.load(); }

function drawChart(sp) {
  if (chart) chart.destroy();
  const ds = [];
  if (sp.roi) ds.push({ label: "fault ROI (median)", data: sp.f.map((x, i) => ({ x, y: sp.roi[i] })), borderColor: "#0b7a6b", pointRadius: 0, borderWidth: 1.5 });
  if (sp.bg) ds.push({ label: "background", data: sp.f.map((x, i) => ({ x, y: sp.bg[i] })), borderColor: "#b4531c", pointRadius: 0, borderWidth: 1.2 });
  const marks = {
    id: "marks",
    afterDatasetsDraw(c) {
      const { ctx, chartArea: a, scales: { x } } = c; ctx.save();
      if (sp.band_hz) { const x0 = x.getPixelForValue(sp.band_hz[0]), x1 = x.getPixelForValue(sp.band_hz[1]);
        ctx.fillStyle = "rgba(11,122,107,0.15)"; ctx.fillRect(x0, a.top, Math.max(2, x1 - x0), a.bottom - a.top); }
      const xn = x.getPixelForValue(sp.f_nyquist);
      if (xn >= a.left && xn <= a.right) { ctx.strokeStyle = "#b3261e"; ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(xn, a.top); ctx.lineTo(xn, a.bottom); ctx.stroke(); }
      ctx.restore();
    },
  };
  chart = new Chart($("chart"), {
    type: "line", data: { datasets: ds }, plugins: [marks],
    options: { animation: false, parsing: false, scales: { x: { type: "linear", title: { display: true, text: "Hz" }, max: sp.f_nyquist },
      y: { title: { display: true, text: "amplitude (px, zero-to-peak)" }, beginAtZero: true } }, plugins: { legend: { position: "bottom" } } },
  });
  $("chartHint").textContent = `Shaded: magnified band. Dashed red: Nyquist limit (${fmt(sp.f_nyquist)} Hz).`;
}

// ---- synchronised video controls -----------------------------------------------------------------
function wireVideoControls() {
  const a = $("vOrig"), b = $("vMag"), seek = $("seek"), play = $("play");
  const both = (fn) => [a, b].forEach((v) => v.src && fn(v));
  play.onclick = () => {
    if (a.paused) { both((v) => v.play()); play.textContent = "Pause"; } else { both((v) => v.pause()); play.textContent = "Play"; }
  };
  $("rate").onchange = () => both((v) => (v.playbackRate = parseFloat($("rate").value)));
  seek.oninput = () => both((v) => (v.currentTime = (seek.value / 1000) * (v.duration || 0)));
  const master = () => (a.src ? a : b);
  [a, b].forEach((v) => {
    v.ontimeupdate = () => {
      const m = master();
      if (v === m && m.duration) seek.value = Math.round((m.currentTime / m.duration) * 1000);
      const o = v === a ? b : a;
      if (v === m && o.src && Math.abs(o.currentTime - m.currentTime) > 0.15) o.currentTime = m.currentTime;
    };
  });
}
init();
