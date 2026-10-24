"use strict";
// HumSight front-end: a four-step flow (recording -> setup -> analysis -> diagnosis) on hash routes.
// Two backends behind one UI:
//  * server (local / EC2): POST /api/jobs, live trace over SSE
//  * lambda (public):     POST /jobs returns the finished job; the recorded trace is replayed
const $ = (id) => document.getElementById(id);
const qs = new URLSearchParams(location.search);
const BASE = (qs.get("api") || window.API_BASE || "").replace(/\/$/, "");
const MAX_MB = 25;
const VIDEO_EXT = /\.(mp4|mov|webm|avi|mkv|npz)$/i;
let PREFIX = "/api";       // "/api" for the FastAPI server, "" for Lambda
let MODE = "server";
let chart = null;

// single source of truth for the flow
const S = {
  clip: null,               // {kind: "demo", id, title, fps, params, expect} | {kind: "upload", file}
  job: { status: "idle", trace: [], result: null, error: null, t0: 0, t1: 0, label: "" },
  demos: [],
};

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const abs = (u) => (!u ? u : /^https?:/.test(u) ? u : BASE + u);
const hdrs = () => (window.DEMO_TOKEN ? { "X-Demo-Token": window.DEMO_TOKEN } : {});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v) => (typeof v === "number" ? (Math.abs(v) >= 100 ? +v.toFixed(1) : +v.toPrecision(4)) : v);
const num = (id) => { const v = $(id).value.trim(); return v === "" ? null : Number(v); };

async function api(path, opts = {}) {
  opts.headers = { ...hdrs(), ...(opts.headers || {}) };
  const r = await fetch(BASE + PREFIX + path, opts);
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    let msg = t;
    try { const j = JSON.parse(t); msg = j.detail || j.error || j.message || t; } catch (e) { /* plain text */ }
    if (typeof msg !== "string") msg = JSON.stringify(msg);
    throw new Error(msg || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

// ================================================================== routing
const ROUTES = ["select", "setup", "run", "report"];
function allowed(step) {
  if (step === "select") return true;
  if (step === "setup") return !!S.clip;
  if (step === "run") return S.job.status !== "idle";
  if (step === "report") return !!S.job.result;
  return false;
}
function go(step) { if (location.hash !== "#/" + step) location.hash = "#/" + step; else route(); }
function route() {
  let step = (location.hash.match(/^#\/(\w+)/) || [])[1];
  if (!ROUTES.includes(step)) step = "select";
  if (!allowed(step)) {                       // fall back to the furthest reachable step before it
    const back = ROUTES.slice(0, ROUTES.indexOf(step)).reverse().find(allowed) || "select";
    history.replaceState(null, "", "#/" + back);
    step = back;
  }
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.dataset.view !== step));
  if (step !== "report") pauseVideos();
  if (step === "setup") refreshSetup();
  renderSteps(step);
  window.scrollTo(0, 0);
  const h = document.querySelector(`#view-${step} h1`);
  if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
}
function renderSteps(current) {
  document.querySelectorAll(".steps a").forEach((a) => {
    const s = a.dataset.step;
    const done = (s === "select" && S.clip) || (s === "setup" && S.job.status !== "idle")
      || (s === "run" && S.job.status === "done") || (s === "report" && S.job.result);
    a.classList.toggle("current", s === current);
    a.classList.toggle("done", !!done && s !== current);
    a.classList.toggle("locked", !allowed(s));
    a.setAttribute("aria-current", s === current ? "step" : "false");
    if (!allowed(s)) a.setAttribute("aria-disabled", "true"); else a.removeAttribute("aria-disabled");
  });
  const sum = (k, t) => (document.querySelector(`[data-sum="${k}"]`).textContent = t);
  sum("select", !S.clip ? "Choose a clip" : S.clip.kind === "demo" ? S.clip.title : S.clip.file.name);
  const fps = num("fps");
  sum("setup", S.clip ? `${fps ? fps + " fps, " : ""}${POLICY[policy()].short.toLowerCase()}` : "Machine and method");
  const j = S.job;
  sum("run", j.status === "idle" ? "Not started" : j.status === "running" ? "Running…" : j.status === "error" ? "Failed" : `Done in ${((j.t1 - j.t0) / 1000).toFixed(1)} s`);
  sum("report", j.result ? (VERDICT[j.result.verdict] || VERDICT.REVIEW).short : "No report yet");
}

// ================================================================== init
async function init() {
  wireSelect(); wireSetup(); wireReport(); wireVideoControls();
  window.addEventListener("hashchange", route);
  route();

  let h = null;
  for (const p of ["/api", ""]) {
    try { PREFIX = p; h = await api("/health"); break; } catch (e) { h = null; }
  }
  if (!h) {
    $("demoList").innerHTML = `<p class="alert alert-alarm">Can't reach the analysis service. Start it with <code>uvicorn server.app:app --port 8000</code> and reload.</p>`;
    $("go").disabled = true;
    return;
  }
  MODE = h.mode || "server";
  if (MODE === "lambda") $("replayTag").hidden = false;
  if (h.llm !== "gemini") {
    const r = document.querySelector('input[value="llm"]');
    r.disabled = true; $("llmMethod").classList.add("disabled");
    $("llmMethod").title = "No Gemini key configured on the server";
    $("llmMethod").querySelector(".method-title").insertAdjacentHTML("beforeend", ' <span class="tag">Unavailable</span>');
  }
  try { S.demos = await api("/demo-clips"); } catch (e) { S.demos = []; }
  // headline case first, known failure cases last
  const rank = (d) => (d.id === "pump_shake_fault" ? 0 : { FAULT: 1, NO_FAULT: 2, REVIEW: 3 }[d.expect] ?? 4);
  S.demos.sort((a, b) => rank(a) - rank(b));
  renderDemos();
}

// ================================================================== step 1: recording
const EXPECT = {
  FAULT: ["alarm", "Expected: alarm"], NO_FAULT: ["ok", "Expected: normal"], REVIEW: ["warn", "Expected: inconclusive"],
};
function renderDemos() {
  const box = $("demoList");
  if (!S.demos.length) { box.innerHTML = `<p class="muted">No reference recordings on this server. Generate them with <code>python scripts/make_demo_clips.py</code>, or upload your own below.</p>`; return; }
  box.innerHTML = "";
  for (const d of S.demos) {
    const [cls, txt] = EXPECT[d.expect] || ["", "Known failure case"];
    const title = String(d.title || d.id).replace(/\s*\(should be [^)]*\)\s*$/i, "");
    const el = document.createElement("label");
    el.className = "clip-card";
    el.innerHTML = `<input type="radio" name="clip" value="${esc(d.id)}">
      <span class="clip-body">
        <span class="clip-title">${esc(title)}</span>
        <span class="clip-desc">${esc(d.description || "")}</span>
        <span class="clip-meta"><span class="expect ${cls}">${esc(txt)}</span><span>${+Number(d.fps).toFixed(2)} fps</span><span>${+Number(d.duration).toFixed(2)} s</span></span>
      </span>`;
    el.querySelector("input").onchange = () => pickDemo(d, title);
    box.appendChild(el);
  }
  if (S.clip && S.clip.kind === "demo") {
    const r = box.querySelector(`input[value="${CSS.escape(S.clip.id)}"]`); if (r) r.checked = true;
  }
}
function pickDemo(d, title) {
  S.clip = { kind: "demo", id: d.id, title, fps: d.fps, params: d.params || {}, expect: d.expect };
  $("file").value = ""; showFile(null);
  const p = S.clip.params;
  $("fps").value = d.fps ?? ""; $("expHz").value = p.expected_hz ?? ""; $("rpm").value = p.rpm ?? "";
  $("fmin").value = p.f_min ?? ""; $("fmax").value = p.f_max ?? ""; $("mmpx").value = p.mm_per_px ?? "";
  clipChanged();
}
function pickFile(file) {
  $("fileErr").hidden = true;
  if (!file) return;
  if (!VIDEO_EXT.test(file.name)) return fileError("Unsupported file type. Use MP4, MOV, WebM, AVI or MKV.");
  if (file.size > MAX_MB * 1048576) return fileError(`The file is ${(file.size / 1048576).toFixed(1)} MB; the limit is ${MAX_MB} MB. Trim the clip to a few seconds.`);
  const wasDemo = S.clip && S.clip.kind === "demo";
  S.clip = { kind: "upload", file };
  document.querySelectorAll('input[name="clip"]').forEach((r) => (r.checked = false));
  if (wasDemo) ["fps", "expHz", "rpm", "fmin", "fmax", "mmpx"].forEach((id) => ($(id).value = ""));
  showFile(file);
  clipChanged();
}
function fileError(msg) { $("fileErr").textContent = msg; $("fileErr").hidden = false; $("file").value = ""; }
function showFile(file) {
  $("uploadCard").classList.toggle("selected", !!file);
  $("drop").classList.toggle("has-file", !!file);
  $("fileName").innerHTML = file ? `<b>${esc(file.name)}</b>, ${(file.size / 1048576).toFixed(1)} MB. <u>Change file</u>` : "Drop a file here or <u>browse</u>";
}
function clipChanged() {
  $("toSetup").disabled = !S.clip;
  renderSteps("select");
}
function wireSelect() {
  $("file").onchange = () => pickFile($("file").files[0]);
  const drop = $("drop");
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); pickFile(e.dataTransfer.files[0]); });
  $("toSetup").onclick = () => go("setup");
}

// ================================================================== step 2: setup
const POLICY = {
  rules: { short: "Agent with rules" },
  llm: { short: "Agent with Gemini" },
  fixed: { short: "Fixed pipeline" },
};
const policy = () => (document.querySelector('input[name="policy"]:checked') || { value: "rules" }).value;
function wireSetup() {
  $("form").addEventListener("input", () => { validate(false); renderSteps("setup"); });
  $("form").addEventListener("submit", (e) => { e.preventDefault(); start(); });
  $("go").onclick = start;
  ["fps", "rpm"].forEach((id) => $(id).addEventListener("input", liveHints));
}
function refreshSetup() {
  const running = S.job.status === "running";
  $("go").disabled = running;
  $("go").innerHTML = running ? "Analysis running…" : 'Run analysis <span aria-hidden="true">→</span>';
  liveHints(); validate(false);
}
function liveHints() {
  const fps = num("fps"), rpm = num("rpm");
  const fpsHelp = $("fps").closest(".field").querySelector(".help");
  fpsHelp.dataset.base = fpsHelp.dataset.base || fpsHelp.textContent;
  fpsHelp.textContent = fps > 0 ? `Measurable up to ${fmt(fps / 2)} Hz (${fmt(fps * 30)} CPM). ` + fpsHelp.dataset.base : fpsHelp.dataset.base;
  const rpmHelp = $("rpm").closest(".field").querySelector(".help");
  rpmHelp.dataset.base = rpmHelp.dataset.base || rpmHelp.textContent;
  rpmHelp.textContent = rpm > 0 ? `= ${fmt(rpm / 60)} Hz running speed (1×).` : rpmHelp.dataset.base;
}
function validate(show) {
  const fps = num("fps"), fmin = num("fmin"), fmax = num("fmax");
  const fpsBad = !(fps > 0), bandBad = fmin != null && fmax != null && fmin >= fmax;
  const mark = (id, bad) => $(id).closest(".input-unit").classList.toggle("invalid", bad && show);
  mark("fps", fpsBad); mark("fmin", bandBad); mark("fmax", bandBad);
  if (show || !fpsBad) $("fpsErr").hidden = !fpsBad || !show;
  if (show || !bandBad) $("bandErr").hidden = !bandBad || !show;
  return !fpsBad && !bandBad;
}
function fields() {
  const f = {};
  const put = (k, id) => { const v = $(id).value.trim(); if (v !== "") f[k] = v; };
  put("capture_fps", "fps"); put("expected_hz", "expHz"); put("rpm", "rpm");
  put("f_min", "fmin"); put("f_max", "fmax"); put("mm_per_px", "mmpx");
  f.policy = policy();
  return f;
}

// ================================================================== step 3: run
// pipeline stages, in the order the agent normally reaches them
const STAGES = [
  ["probe", "Check recording"], ["coarse", "Coarse scan"], ["shake", "Camera shake"], ["classify", "Classify peaks"],
  ["fine", "Fine scan"], ["magnify", "Magnify"], ["severity", "Severity"], ["report", "Report"],
];
function stageOf(ev) {
  const t = ev.tool;
  if (t === "probe_clip") return "probe";
  if (t === "scan_motion") return (ev.args && ev.args.grid === "fine") || (ev.result && ev.result.refined) ? "fine" : "coarse";
  if (t === "compensate_shake") return "shake";
  if (t === "classify_peaks") return "classify";
  if (t === "magnify") return "magnify";
  if (t === "assess_severity") return "severity";
  if (t === "file_report" || t === "request_review") return "report";
  return null;
}
const TOOL_NAME = {
  probe_clip: "Check recording", compensate_shake: "Remove camera shake", classify_peaks: "Classify peaks",
  magnify: "Magnify fault region", assess_severity: "Assess severity", request_review: "Request human review",
  file_report: "File work order", fixed_pipeline: "Fixed pipeline",
};
const toolName = (ev) => ev.tool === "scan_motion" ? (stageOf(ev) === "fine" ? "Fine scan of fault region" : "Coarse motion scan") : (TOOL_NAME[ev.tool] || ev.tool);

function renderStages() {
  const fixed = S.job.label.policy === "fixed";
  const list = fixed ? [["fixed", "Fixed pipeline"]] : STAGES;
  const seen = new Set(S.job.trace.filter((e) => e.kind === "tool").map((e) => (fixed ? "fixed" : stageOf(e))));
  // events arrive after a tool finishes, so a seen stage is done; unseen ones are skipped once the job ends
  const running = S.job.status === "running";
  $("stages").innerHTML = list.map(([k, label]) =>
    `<li class="${seen.has(k) ? "done" : running ? "" : "skipped"}">${esc(label)}</li>`).join("");
}

let ticker = null;
async function start() {
  if (S.job.status === "running") return go("run");
  if (!S.clip) return go("select");
  if (!validate(true)) { const bad = document.querySelector(".input-unit.invalid input"); if (bad) bad.focus(); return; }
  const f = fields();
  S.job = { status: "running", trace: [], result: null, error: null, t0: Date.now(), t1: 0,
    label: { policy: f.policy, clip: S.clip.kind === "demo" ? S.clip.title : S.clip.file.name } };
  $("trace").innerHTML = `<li class="empty">Waiting for the first measurement…</li>`;
  $("trace2").innerHTML = "";
  $("err").hidden = true; $("toReport").hidden = true; $("runBack").innerHTML = '<span aria-hidden="true">←</span> Setup';
  $("runTitle").textContent = "Analyzing recording";
  $("spinner").className = "spinner";
  $("runState").textContent = MODE === "lambda" ? "Running on AWS Lambda…" : "Starting…";
  renderStages();
  clearInterval(ticker);
  ticker = setInterval(() => { $("elapsed").textContent = ((Date.now() - S.job.t0) / 1000).toFixed(1) + " s"; }, 100);
  go("run");
  try {
    const res = MODE === "lambda" ? await runLambda(S.clip, f) : await runServer(S.clip, f);
    finish(res, null);
  } catch (e) {
    finish(null, String(e.message || e));
  }
}
function finish(result, error) {
  clearInterval(ticker);
  S.job.t1 = Date.now();
  $("elapsed").textContent = ((S.job.t1 - S.job.t0) / 1000).toFixed(1) + " s";
  S.job.status = error ? "error" : "done";
  S.job.result = result; S.job.error = error;
  renderStages();
  const onRun = !$("view-run").hidden;
  if (error) {
    $("spinner").className = "spinner bad";
    $("runTitle").textContent = "Analysis failed";
    $("runState").textContent = "The job stopped before a diagnosis was made.";
    const empty = $("trace").querySelector(".empty"); if (empty) empty.textContent = "No measurements were made.";
    $("err").innerHTML = `<b>${esc(friendly(error))}</b><details><summary>Technical details</summary><code>${esc(error)}</code></details>`;
    $("err").hidden = false;
    $("runBack").innerHTML = '<span aria-hidden="true">←</span> Fix setup';
  } else {
    $("spinner").className = "spinner ok";
    $("runTitle").textContent = "Analysis complete";
    $("runState").textContent = `${(VERDICT[result.verdict] || VERDICT.REVIEW).short} after ${S.job.trace.filter((e) => e.kind === "tool").length} measurements`;
    $("toReport").hidden = false;
    showResult(result);
    if (onRun) setTimeout(() => { if (!$("view-run").hidden && S.job.result === result) go("report"); }, 1200);
  }
  renderSteps(currentStep());
}
// plain-language message for the errors a field user actually hits; the raw text stays under "Technical details"
function friendly(e) {
  if (/cannot open video|could not read|no frames/i.test(e)) return "The video couldn't be decoded. Re-export it as an H.264 MP4 (or WebM) and upload it again.";
  if (/exceeds \d+ MB|413/i.test(e)) return `The file is larger than ${MAX_MB} MB. Trim it to a few seconds and try again.`;
  if (/capture_fps/i.test(e)) return "Enter the capture frame rate in Setup.";
  if (/unsupported file type/i.test(e)) return "That file type isn't supported. Use MP4, MOV, WebM, AVI or MKV.";
  if (/lost connection|failed to fetch|networkerror/i.test(e)) return "Lost contact with the analysis service. Check that it is running, then try again.";
  return e.replace(/^\w+Error:\s*/, "").replace(/[A-Z]:\\[^\s:]+|\/(?:home|tmp|var|opt)\/[^\s:]+/g, "(file)");
}
const currentStep = () => (document.querySelector(".view:not([hidden])") || { dataset: { view: "select" } }).dataset.view;

async function runServer(clip, f) {
  const fd = new FormData();
  for (const k in f) fd.append(k, f[k]);
  if (clip.kind === "demo") fd.append("demo_id", clip.id); else fd.append("file", clip.file);
  if (clip.kind === "upload") $("runState").textContent = "Uploading video…";
  const { job_id } = await api("/jobs", { method: "POST", body: fd });
  $("runState").textContent = "Measuring…";
  return new Promise((resolve, reject) => {
    const es = new EventSource(BASE + PREFIX + `/jobs/${job_id}/events`);
    es.addEventListener("trace", (m) => addTrace(JSON.parse(m.data)));
    es.addEventListener("done", async (m) => {
      es.close();
      const d = JSON.parse(m.data);
      if (d.status === "error") return reject(new Error(d.error || "job failed"));
      try { resolve((await api(`/jobs/${job_id}`)).result); } catch (e) { reject(e); }
    });
    es.onerror = () => { es.close(); reject(new Error("Lost connection to the analysis service while the job was running.")); };
  });
}

async function runLambda(clip, f) {
  const body = { ...f };
  if (clip.kind === "demo") body.demo_id = clip.id;
  else {
    $("runState").textContent = "Uploading video…";
    const file = clip.file;
    const up = await api("/upload-url", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ filename: file.name, content_type: file.type || "video/mp4" }) });
    const put = await fetch(up.put_url, { method: "PUT", body: file, headers: { "content-type": file.type || "video/mp4" } });
    if (!put.ok) throw new Error("Upload to storage failed.");
    body.key = up.key;
  }
  $("runState").textContent = "Running on AWS Lambda… (the activity log is replayed when the job finishes)";
  const res = await api("/jobs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  $("runState").textContent = "Replaying activity log…";
  for (const ev of res.trace || []) { addTrace(ev); await sleep(350); }
  return res;
}

// ---- activity log ---------------------------------------------------------------------------
function keyNums(tool, r) {
  if (!r) return [];
  const pick = {
    probe_clip: [["fps", "fps"], ["f_nyquist", "max Hz"], ["delta_f", "resolution Hz"], ["texture_coverage", "texture"]],
    scan_motion: [["grid", "grid"], ["noise_floor_px", "noise floor px"]],
    compensate_shake: [["method", "method"], ["bg_peak_hz", "shake Hz"], ["bg_amp_px", "shake px"], ["residual_at_shake_px", "residual px"], ["inlier_ratio", "inliers"]],
    classify_peaks: [["noise_floor_px", "noise floor px"], ["min_detectable_px", "min detectable px"]],
    magnify: [["alpha_effective", "α"], ["slowdown", "slowdown ×"], ["artifact_ratio", "artifact ratio"]],
    assess_severity: [["amp_mm", "amp mm"], ["v_rms_mm_s", "v RMS mm/s"], ["zone", "zone"]],
  }[tool] || [];
  const out = pick.filter(([k]) => r[k] !== undefined && r[k] !== null).map(([k, l]) => [`${l} ${fmt(r[k])}`, false]);
  if (r.alias_risk) out.push(["aliasing risk", true]);
  if (r.lighting_flicker) out.push(["lighting flicker", true]);
  if (r.top_peaks && r.top_peaks[0]) { const p = r.top_peaks[0]; out.push([`top peak ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px, SNR ${fmt(p.snr)}`, false]); }
  if (r.background_peaks && r.background_peaks[0]) { const p = r.background_peaks[0]; out.push([`background ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px`, false]); }
  if (r.faults && r.faults[0]) { const p = r.faults[0]; out.push([`fault ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px, SNR ${fmt(p.snr)}`, true]); }
  else if (tool === "classify_peaks") out.push(["no fault peak", false]);
  if (r.shake && r.shake[0]) out.push([`shake rejected ${fmt(r.shake[0].f_hz)} Hz`, false]);
  if (r.refined) out.push([`refined ${fmt(r.refined.f_hz)} Hz, ${fmt(r.refined.amp_px)} px`, true]);
  if (r.findings && r.findings[0] && tool === "fixed_pipeline") { const p = r.findings[0]; out.push([`strongest peak ${fmt(p.f_hz)} Hz, ${fmt(p.amp_px)} px`, true]); }
  if (r.verdict) out.push([`verdict ${r.verdict.replace("_", " ")}`, true]);
  if (r.state) out.push([`${r.state}: ${r.reason}`, true]);
  if (r.error) out.push([`error: ${r.error}`, true]);
  return out;
}
function traceItem(ev) {
  const li = document.createElement("li");
  if (ev.kind === "note") { li.className = "note"; li.textContent = ev.rationale || (ev.result && ev.result.message) || ""; return li; }
  const src = (ev.source || "").startsWith("llm") ? ["Gemini", ""] : (ev.source || "").startsWith("fixed") ? ["Fixed", "tag-warn"] : ["Rules", ""];
  const chips = keyNums(ev.tool, ev.result).map(([t, hit]) => `<span class="${hit ? "hit" : ""}">${esc(t)}</span>`).join("");
  li.innerHTML = `<span class="n">${ev.step}</span>
    <div class="hd"><span class="tool">${esc(toolName(ev))}</span><span class="code">${esc(ev.tool)}</span><span class="tag ${src[1]}">${src[0]}</span><span class="ms">${fmt(ev.runtime_ms || 0)} ms</span></div>
    ${ev.rationale ? `<p class="why">${esc(ev.rationale)}</p>` : "<span></span>"}
    ${chips ? `<p class="nums">${chips}</p>` : ""}`;
  return li;
}
function addTrace(ev) {
  S.job.trace.push(ev);
  const empty = $("trace").querySelector(".empty"); if (empty) empty.remove();
  $("trace").appendChild(traceItem(ev));
  if (ev.kind === "tool" && S.job.status === "running") $("runState").textContent = `${toolName(ev)} done, measuring next…`;
  renderStages();
}

// ================================================================== step 4: diagnosis
const VERDICT = {
  FAULT: { short: "Alarm", label: "Localized vibration detected" },
  NO_FAULT: { short: "Normal", label: "No fault vibration detected" },
  REVIEW: { short: "Inconclusive", label: "Needs a human review" },
};
function actionFor(r, fixed) {
  if (fixed) return "Don't act on this result alone: the baseline does not reject camera shake. Re-run the same recording with the agent.";
  if (r.verdict === "FAULT") return "Inspect the highlighted region (bearing, mounting, fasteners) at the next planned stop and confirm with a contact accelerometer before any shutdown decision.";
  if (r.verdict === "NO_FAULT") return "No action needed. Keep the asset on its routine monitoring route.";
  const s = r.suggestion ? r.suggestion.charAt(0).toUpperCase() + r.suggestion.slice(1).replace(/\.?$/, ".") : "";
  return s ? `${s} Then run the analysis again.` : "Re-record the machine following the notes in the activity log, then run the analysis again.";
}
function lastResult(tool) { const e = [...S.job.trace].reverse().find((x) => x.tool === tool); return e ? e.result || {} : null; }

function showResult(r) {
  if ((r.trace || []).length > S.job.trace.length) S.job.trace = r.trace.slice();   // the job's own record wins
  const fixed = r.policy === "fixed";
  const v = VERDICT[r.verdict] ? r.verdict : "REVIEW";
  const V = VERDICT[v];
  $("banner").className = "status-banner " + v;
  $("statusWord").textContent = V.short;
  $("statusLabel").textContent = fixed ? V.label + ", from the baseline (unverified)" : V.label;
  const sm = r.summary || r.reason || "";
  $("summary").textContent = sm.charAt(0).toUpperCase() + sm.slice(1);
  $("action").textContent = actionFor(r, fixed);
  $("baselineNote").hidden = !fixed;
  const when = new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  $("repMeta").innerHTML = [["Recording", S.job.label.clip], ["Method", POLICY[r.policy] ? POLICY[r.policy].short : r.policy], ["Run", when]]
    .map(([k, v]) => `<li><span>${k}</span>${esc(v)}</li>`).join("");

  renderKpis(r, fixed);

  // video evidence
  const u = r.urls || {};
  // presigned S3 URLs end in a query string, so test the path only
  const vid = (x) => (x && /\.(webm|mp4|mov)$/i.test(x.split("?")[0]) ? abs(x) : null);
  const orig = vid(u.original) || vid(u.source), mag = vid(u.magnified);
  setVideo($("vOrig"), orig); setVideo($("vMag"), mag);
  $("magCap").textContent = fixed ? "Magnified (strongest peak, may be camera shake)" : "Magnified fault region (slowed, motion amplified)";
  $("vids").classList.toggle("single", !(orig && mag));
  $("vids").hidden = !orig && !mag; $("vidCtl").hidden = !orig && !mag;
  $("noVideo").hidden = !!mag;
  $("noVideo").textContent = v === "REVIEW" ? "No magnified video: the evidence was too weak to isolate a fault region." : "No magnified video: no fault region was isolated, so there is nothing to amplify.";
  $("play").textContent = "Play"; $("seek").value = 0;

  // spectrum: drawn when its tab is first shown (Chart.js can't size inside a hidden panel)
  if (chart) { chart.destroy(); chart = null; }
  $("chart").parentElement.hidden = !u.spectrum; $("chartTools").hidden = !u.spectrum; $("noChart").hidden = !!u.spectrum; $("chartHint").textContent = "";
  pendingSpectrum = u.spectrum ? abs(u.spectrum) : null;

  // heatmap
  $("heat").hidden = !u.heatmap; $("heatHint").hidden = !u.heatmap; $("noHeat").hidden = !!u.heatmap;
  if (u.heatmap) $("heat").src = abs(u.heatmap); else $("heat").removeAttribute("src");

  // findings
  const tb = $("findings").querySelector("tbody"); tb.innerHTML = "";
  (r.findings || []).forEach((f, i) => {
    const roi = Array.isArray(f.roi) ? `x ${f.roi[0]}, y ${f.roi[1]}, ${f.roi[2]} × ${f.roi[3]}` : "—";
    tb.insertAdjacentHTML("beforeend", `<tr><td>${i + 1}</td><td>${fmt(f.f_hz)} Hz</td><td>${fmt(f.f_hz * 60)} CPM</td><td>${fmt(f.amp_px)} px</td><td>${fmt(f.snr)}</td><td>${esc(roi)}</td></tr>`);
  });
  if (!(r.findings || []).length) {
    tb.innerHTML = `<tr><td colspan="6" class="msg">${v === "REVIEW" ? "No findings: " + esc(r.reason || "review needed") + "." : "No fault peak above the detection threshold."}</td></tr>`;
  }
  const s = r.severity;
  $("sev").textContent = s ? `Severity (indicative): ${s.v_rms_mm_s != null ? fmt(s.v_rms_mm_s) + " mm/s RMS. " : ""}${s.note}` : "Displacement is zero-to-peak, in image pixels. Add an image scale in setup to get millimetres and velocity.";
  $("warn").innerHTML = (r.warnings || []).map((w) => `<p class="alert alert-warn">${esc(w)}</p>`).join("");
  const nf = (r.findings || []).length;
  document.querySelector('[data-tab="findings"]').innerHTML = `Findings <span class="count">${nf}</span>`;

  // activity log copy + work order
  $("trace2").innerHTML = ""; S.job.trace.forEach((ev) => $("trace2").appendChild(traceItem(ev)));
  const hasWo = !!(u.work_order_md || u.work_order_json);
  $("dlRow").hidden = !hasWo; $("noWo").hidden = hasWo;
  if (u.work_order_md) $("dlMd").href = abs(u.work_order_md);
  if (u.work_order_json) $("dlJson").href = abs(u.work_order_json);

  const empty = { video: !orig && !mag, spectrum: !u.spectrum, heat: !u.heatmap, findings: !nf, wo: !hasWo };
  document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.classList.toggle("empty-tab", !!empty[b.dataset.tab]));
  selectTab(mag ? "video" : u.spectrum ? "spectrum" : "log");
}

function renderKpis(r, fixed) {
  const f = (r.findings || [])[0];
  const s = r.severity || {};
  const shake = lastResult("compensate_shake");
  const cls = lastResult("classify_peaks");
  const k = [];
  const tile = (label, value, unit, sub, na) => k.push(`<div class="kpi${na ? " na" : ""}"><p class="kpi-label">${label}</p><p class="kpi-value">${value}${unit ? `<small>${unit}</small>` : ""}</p>${sub ? `<p class="kpi-sub">${sub}</p>` : ""}</div>`);
  if (f) {
    tile("Dominant frequency", fmt(f.f_hz), "Hz", `${fmt(f.f_hz * 60)} CPM`);
    tile("Displacement", s.amp_mm != null ? fmt(s.amp_mm) : fmt(f.amp_px), s.amp_mm != null ? "mm" : "px", s.amp_mm != null ? `${fmt(f.amp_px)} px, zero-to-peak` : "zero-to-peak, image pixels");
    tile("Velocity RMS", s.v_rms_mm_s != null ? fmt(s.v_rms_mm_s) : "n/a", s.v_rms_mm_s != null ? "mm/s" : "", s.v_rms_mm_s != null ? (s.zone ? `zone ${esc(s.zone)}` : "indicative") : "needs an image scale", s.v_rms_mm_s == null);
    tile("Signal / noise", fmt(f.snr), "×", f.snr >= 6 ? "clear peak" : "weak peak");
  } else if (!cls) {
    tile("Dominant frequency", "Not measured", "", "the analysis stopped before scanning", true);
  } else {
    tile("Dominant frequency", "—", "", "no fault peak found", true);
    if (cls && cls.min_detectable_px != null) tile("Detection limit", fmt(cls.min_detectable_px), "px", "smallest motion this clip can resolve");
    if (cls && cls.noise_floor_px != null) tile("Noise floor", fmt(cls.noise_floor_px), "px");
  }
  if (fixed) tile("Camera shake", "Not checked", "", "baseline has no shake step", true);
  else if (shake && shake.bg_peak_hz != null) tile("Camera shake", "Removed", "", `${fmt(shake.bg_peak_hz)} Hz, ${fmt(shake.bg_amp_px)} px`);
  else if (cls) tile("Camera shake", "None", "", "steady camera");
  else tile("Camera shake", "Not measured", "", "the analysis stopped early", true);
  const cap = r.capture || {};
  if (cap.fps) tile("Recording", fmt(cap.fps), "fps", `${cap.duration_s ? fmt(cap.duration_s) + " s" : ""}${cap.width ? `, ${cap.width} × ${cap.height}` : ""}`);
  $("kpis").innerHTML = k.join("");
}

let pendingSpectrum = null;
function selectTab(name) {
  document.querySelectorAll(".tabs [role=tab]").forEach((b) => {
    const on = b.dataset.tab === name;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll(".tabpanel").forEach((p) => (p.hidden = p.dataset.panel !== name));
  if (name !== "video") pauseVideos();
  if (name === "spectrum" && pendingSpectrum) {
    const url = pendingSpectrum; pendingSpectrum = null;
    fetch(url).then((x) => x.json()).then(drawChart).catch(() => { $("chart").parentElement.hidden = true; $("noChart").hidden = false; });
  }
}
function wireReport() {
  const tabs = [...document.querySelectorAll(".tabs [role=tab]")];
  $("rerunAgent").onclick = () => { document.querySelector('input[name="policy"][value="rules"]').checked = true; start(); };
  $("logY").onchange = () => {
    if (!chart) return;
    const y = chart.options.scales.y;
    y.type = $("logY").checked ? "logarithmic" : "linear"; y.beginAtZero = !$("logY").checked;
    chart.update();
  };
  tabs.forEach((b, i) => {
    b.onclick = () => selectTab(b.dataset.tab);
    b.onkeydown = (e) => {
      const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      const n = tabs[(i + d + tabs.length) % tabs.length]; n.focus(); selectTab(n.dataset.tab);
    };
  });
  $("newRun").onclick = () => {
    pauseVideos();
    S.clip = null; S.job = { status: "idle", trace: [], result: null, error: null, t0: 0, t1: 0, label: "" };
    document.querySelectorAll('input[name="clip"]').forEach((r) => (r.checked = false));
    $("file").value = ""; showFile(null); $("toSetup").disabled = true;
    ["fps", "expHz", "rpm", "fmin", "fmax", "mmpx"].forEach((id) => ($(id).value = ""));
    go("select");
  };
}

function drawChart(sp) {
  if (chart) chart.destroy();
  const c1 = css("--series-1"), c2 = css("--series-2"), band = css("--band"), mute = css("--mute");
  Chart.defaults.font.family = css("--sans"); Chart.defaults.color = mute;
  const ds = [];
  if (sp.roi) ds.push({ label: "Fault region (median)", data: sp.f.map((x, i) => ({ x, y: sp.roi[i] })), borderColor: c1, backgroundColor: c1, pointRadius: 0, borderWidth: 1.6 });
  if (sp.bg) ds.push({ label: "Background", data: sp.f.map((x, i) => ({ x, y: sp.bg[i] })), borderColor: c2, backgroundColor: c2, pointRadius: 0, borderWidth: 1.2 });
  const marks = {
    id: "marks",
    afterDatasetsDraw(c) {
      const { ctx, chartArea: a, scales: { x } } = c; ctx.save();
      if (sp.band_hz) { const x0 = x.getPixelForValue(sp.band_hz[0]), x1 = x.getPixelForValue(sp.band_hz[1]);
        ctx.globalAlpha = 0.15; ctx.fillStyle = band; ctx.fillRect(x0, a.top, Math.max(2, x1 - x0), a.bottom - a.top); ctx.globalAlpha = 1; }
      const xn = x.getPixelForValue(sp.f_nyquist);
      if (xn >= a.left && xn <= a.right) { ctx.strokeStyle = mute; ctx.setLineDash([5, 4]); ctx.beginPath(); ctx.moveTo(xn, a.top); ctx.lineTo(xn, a.bottom); ctx.stroke(); }
      ctx.restore();
    },
  };
  const grid = { color: css("--line") };
  chart = new Chart($("chart"), {
    type: "line", data: { datasets: ds }, plugins: [marks],
    options: { animation: false, parsing: false, maintainAspectRatio: false, interaction: { mode: "nearest", axis: "x", intersect: false },
      scales: {
        x: { type: "linear", title: { display: true, text: "Frequency (Hz)" }, max: sp.f_nyquist, grid },
        y: { type: $("logY").checked ? "logarithmic" : "linear", title: { display: true, text: "Displacement (px, zero-to-peak)" }, beginAtZero: !$("logY").checked, grid } },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 12, boxHeight: 2 } },
        tooltip: { callbacks: { title: (it) => `${fmt(it[0].parsed.x)} Hz`, label: (it) => `${it.dataset.label}: ${fmt(it.parsed.y)} px` } } } },
  });
  $("chartHint").textContent = sp.band_hz
    ? `Shaded: the band that was magnified (${fmt(sp.band_hz[0])}–${fmt(sp.band_hz[1])} Hz). Dashed line: highest measurable frequency (${fmt(sp.f_nyquist)} Hz).`
    : `Dashed line: highest measurable frequency (${fmt(sp.f_nyquist)} Hz).`;
}

// ---- synchronised video controls -----------------------------------------------------------------
const hasSrc = (v) => !!v.getAttribute("src");
function setVideo(el, url) {
  el.pause();
  if (url) el.src = url; else el.removeAttribute("src");
  el.parentElement.hidden = !url;
  el.load();
}
function pauseVideos() { [$("vOrig"), $("vMag")].forEach((v) => hasSrc(v) && v.pause()); $("play").textContent = "Play"; }
function wireVideoControls() {
  const a = $("vOrig"), b = $("vMag"), seek = $("seek"), play = $("play");
  const both = (fn) => [a, b].forEach((v) => hasSrc(v) && fn(v));
  const rate = () => parseFloat($("rate").value) || 1;
  play.onclick = () => {
    const m = master();
    if (!m) return;
    if (m.paused) { both((v) => { v.playbackRate = rate(); v.play().catch(() => {}); }); play.textContent = "Pause"; }
    else { both((v) => v.pause()); play.textContent = "Play"; }
  };
  $("rate").onchange = () => both((v) => (v.playbackRate = rate()));
  seek.oninput = () => both((v) => (v.currentTime = (seek.value / 1000) * (v.duration || 0)));
  const master = () => (hasSrc(a) ? a : hasSrc(b) ? b : null);
  [a, b].forEach((v) => {
    v.onloadedmetadata = () => (v.playbackRate = rate());
    v.ontimeupdate = () => {
      const m = master();
      if (v !== m || !m.duration) return;
      seek.value = Math.round((m.currentTime / m.duration) * 1000);
      const o = v === a ? b : a;
      if (hasSrc(o) && Math.abs(o.currentTime - m.currentTime) > 0.15) o.currentTime = m.currentTime;
    };
  });
}
init();
