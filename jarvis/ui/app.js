/* JARVIS — hologram overlay + chat + fleet command center */
(() => {
"use strict";
const $ = (s) => document.querySelector(s);
const ring = $("#ring"), ctx = ring.getContext("2d");
const statusEl = $("#status"), userLine = $("#user-line"), replyLine = $("#reply-line");
const chipMode = $("#chip-mode"), chipBrain = $("#chip-brain"), chipFleet = $("#chip-fleet");
const factsEl = $("#facts"), habitsEl = $("#habits"), fleetEl = $("#fleet");
const activityEl = $("#activity"), prepsEl = $("#preps"), calendarEl = $("#calendar");

let ws = null, state = "idle", recording = null, analyser = null, levelBuf = null;
let currentLevel = 0, typeTimer = null;

const STATE_WORDS = { idle: "STANDBY", listening: "LISTENING", thinking: "PROCESSING", speaking: "RESPONDING" };
const STATE_COLORS = { idle: "#3b82f6", listening: "#38bdf8", thinking: "#818cf8", speaking: "#34d399" };

/* ---------------- ring animation ---------------- */
const cur = { segs: 3, speed: 0.25, alpha: 0.45, pulse: 0.15, barAmp: 0 };
const target = { ...cur };

function setState(s) {
  state = s;
  statusEl.textContent = STATE_WORDS[s] || s.toUpperCase();
  statusEl.className = "status " + s;
  document.documentElement.style.setProperty("--accent", STATE_COLORS[s] || STATE_COLORS.idle);
  if (s === "idle")       Object.assign(target, { segs: 3, speed: 0.25, alpha: 0.45, pulse: 0.15, barAmp: 0 });
  if (s === "listening")  Object.assign(target, { segs: 6, speed: 0.9,  alpha: 0.95, pulse: 0,    barAmp: 1 });
  if (s === "thinking")   Object.assign(target, { segs: 8, speed: 1.8,  alpha: 0.85, pulse: 0.35, barAmp: 0 });
  if (s === "speaking")   Object.assign(target, { segs: 4, speed: 0.5,  alpha: 0.9,  pulse: 1,    barAmp: 0.4 });
}

let t = 0, angle = 0;
function frame() {
  t += 0.016;
  const k = 0.08;
  for (const key of ["segs", "speed", "alpha", "pulse", "barAmp"]) cur[key] += (target[key] - cur[key]) * k;
  angle += cur.speed * 0.016;

  const W = ring.width, H = ring.height, cx = W / 2, cy = H / 2;
  const R = 150 + Math.sin(t * (2 + cur.pulse * 5)) * 9 * cur.pulse;
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent") || "#38bdf8";
  ctx.clearRect(0, 0, W, H);

  // outer orbit + ticks
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(148,163,184,0.10)";
  ctx.beginPath(); ctx.arc(cx, cy, R + 58, 0, Math.PI * 2); ctx.stroke();
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2 + (state === "thinking" ? -t * 0.3 : t * 0.05);
    const r1 = R + 44, r2 = R + (i % 6 === 0 ? 54 : 49);
    ctx.strokeStyle = i % 6 === 0 ? "rgba(148,163,184,0.28)" : "rgba(148,163,184,0.10)";
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
    ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
    ctx.stroke();
  }

  // main arc segments
  const n = Math.max(1, Math.round(cur.segs));
  const gap = 0.14, seg = (Math.PI * 2 / n) * (1 - gap);
  ctx.shadowColor = accent; ctx.shadowBlur = 24; ctx.lineCap = "round";
  for (let i = 0; i < n; i++) {
    const start = angle + (i * Math.PI * 2) / n + gap / 2;
    ctx.strokeStyle = accent;
    ctx.globalAlpha = cur.alpha * (0.75 + 0.25 * Math.sin(t * 2 + i));
    ctx.lineWidth = 3.5;
    ctx.beginPath(); ctx.arc(cx, cy, R, start, start + seg); ctx.stroke();
  }
  ctx.globalAlpha = 1;

  // waveform bars
  if (cur.barAmp > 0.02) {
    const bars = 40;
    if (state === "listening" && analyser) analyser.getByteFrequencyData(levelBuf);
    for (let i = 0; i < bars; i++) {
      const a = (i / bars) * Math.PI * 2 - Math.PI / 2;
      let amp;
      if (state === "listening" && analyser) {
        amp = levelBuf[Math.floor((i / bars) * levelBuf.length * 0.7)] / 255;
      } else {
        amp = (Math.sin(i * 0.55 + t * 6) * 0.5 + 0.5) * (0.4 + 0.6 * Math.abs(Math.sin(t * 3 + i * 0.2)));
      }
      const len = 4 + amp * 34 * cur.barAmp;
      ctx.globalAlpha = 0.5 * cur.barAmp;
      ctx.strokeStyle = accent; ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * (R + 14), cy + Math.sin(a) * (R + 14));
      ctx.lineTo(cx + Math.cos(a) * (R + 14 + len), cy + Math.sin(a) * (R + 14 + len));
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // core dot
  ctx.shadowBlur = 30;
  ctx.fillStyle = accent;
  ctx.globalAlpha = 0.5 + 0.5 * Math.abs(Math.sin(t * (1.2 + cur.pulse * 4)));
  ctx.beginPath(); ctx.arc(cx, cy, 5 + cur.pulse * 3, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 1; ctx.shadowBlur = 0;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

/* ---------------- transcript / toast ---------------- */
function toast(msg, ms = 4000) {
  const el = $("#toast");
  el.textContent = msg; el.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.remove("show"), ms);
}
function typeReply(text) {
  clearInterval(typeTimer);
  replyLine.textContent = "";
  let i = 0;
  typeTimer = setInterval(() => {
    replyLine.textContent = text.slice(0, ++i);
    if (i >= text.length) clearInterval(typeTimer);
  }, 14);
}
function replyThenIdle(text) {
  typeReply(text);
  setState("speaking");
  setTimeout(() => setState("idle"), Math.min(9000, 400 + text.length * 30));
}

/* ---------------- command center panels ---------------- */
const DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function renderLearned(facts, habits) {
  factsEl.innerHTML = "";
  if (!facts.length) factsEl.innerHTML = '<li class="empty">Nothing filed yet.</li>';
  facts.forEach((f) => { const li = document.createElement("li"); li.textContent = f; factsEl.appendChild(li); });
  habitsEl.innerHTML = "";
  if (!habits.length) habitsEl.innerHTML = '<li class="empty">No patterns yet — use me a few times.</li>';
  habits.slice(0, 8).forEach((h) => {
    const li = document.createElement("li");
    const what = h.tool === "open_app" || h.tool === "active"
      ? (h.tool === "active" ? `in ${h.detail}` : `open ${h.detail}`)
      : h.tool + (h.detail ? ` (${h.detail})` : "");
    li.textContent = `${what} — ${DAY[h.weekday]} ~${String(h.hour).padStart(2, "0")}:00  ×${h.count}`;
    habitsEl.appendChild(li);
  });
}
function renderHome(st) {
  const el = $("#home"), chip = $("#home-src");
  if (!st || !st.ok) {
    el.innerHTML = '<li class="empty">No home bridge.</li>';
    return;
  }
  chip.classList.remove("hidden");
  chip.textContent = st.simulated ? "SIM HOME" : "HOME ASSISTANT";
  chip.className = "chip tiny" + (st.simulated ? " amber" : " green");
  el.innerHTML = "";
  Object.entries(st.lights || {}).forEach(([n, l]) => {
    const li = document.createElement("li");
    li.className = "mkt";
    li.innerHTML = `<span class="sym">${l.on ? "💡" : "·"} ${n}</span>`
      + `<span class="px">${l.on ? (l.brightness ? l.brightness + "%" : "on") : "off"}</span>`;
    el.appendChild(li);
  });
  const tv = document.createElement("li");
  tv.className = "mkt";
  tv.innerHTML = `<span class="sym">📺 tv</span><span class="px">${st.tv.on ? "on" : "off"}</span>`;
  el.appendChild(tv);
  const cl = document.createElement("li");
  cl.className = "mkt";
  cl.innerHTML = `<span class="sym">🌡 climate</span><span class="px">${st.climate.target}°C</span>`;
  el.appendChild(cl);
}
function renderScenes(scenes) {
  const box = $("#scenes");
  box.innerHTML = "";
  (scenes || []).forEach((s) => {
    const b = document.createElement("button");
    b.className = "ghost small scene-btn";
    b.textContent = s.replace(/-/g, " ").toUpperCase();
    b.onclick = () => sendChat(s.replace(/-/g, " "));
    box.appendChild(b);
  });
}
function renderMusic(m) {
  const el = $("#music");
  if (!m || !m.ok || !m.playing) {
    el.className = "empty";
    el.textContent = "Nothing playing.";
    return;
  }
  el.className = "";
  el.textContent = `▶ ${m.track || "music"}  ·  vol ${m.volume}%`
    + (m.simulated ? "  (sim)" : "");
}
function renderSelf(st) {
  const el = $("#selfstats"), rl = $("#selfrules");
  if (!st) { el.innerHTML = '<li class="empty">Self-engine off.</li>'; return; }
  const landed = Math.round(100 - (st.fallback_pct || 0) - (st.error_pct || 0));
  el.innerHTML = "";
  [
    ["turns journaled", st.turns],
    ["landed first try", landed + "%"],
    ["praise / corrections", `${st.praise} / ${st.corrections}`],
    ["avg latency", (st.avg_latency_ms || 0) + " ms"],
    ["top intents", (st.top_intents || []).map(([i, c]) => `${i}×${c}`).join(", ") || "—"],
  ].forEach(([k, v]) => {
    const li = document.createElement("li");
    li.className = "mkt";
    li.innerHTML = `<span class="sym">${k}</span><span class="px">${v}</span>`;
    el.appendChild(li);
  });
  rl.innerHTML = "";
  (st.self_rules || []).forEach((r) => {
    const li = document.createElement("li");
    li.className = "mkt";
    li.innerHTML = `<span class="sym">🧬 '${r.pattern}'</span>`
      + `<span class="px">→ '${r.canon}' (${r.uses}×)</span>`;
    rl.appendChild(li);
  });
}
function renderMarkets(snap) {
  const el = $("#markets"), chip = $("#mkt-src");
  if (!snap || !snap.ok) {
    el.innerHTML = '<li class="empty">Markets unreachable from here.</li>';
    chip.classList.add("hidden");
    return;
  }
  chip.classList.remove("hidden");
  chip.textContent = snap.simulated ? "SIM FEED" : (snap.source || "live");
  chip.className = "chip tiny" + (snap.simulated ? " amber" : " green");
  el.innerHTML = "";
  const rows = [];
  Object.entries(snap.pairs || {}).forEach(([s, r]) =>
    rows.push([s, r.price < 50 ? r.price.toFixed(4) : r.price.toLocaleString(), r.chg_pct]));
  Object.entries(snap.crypto || {}).forEach(([s, r]) =>
    rows.push([s, "$" + r.price.toLocaleString(), r.chg_pct]));
  Object.entries(snap.indices || {}).forEach(([s, r]) =>
    rows.push([s, r.price.toLocaleString(), r.chg_pct]));
  rows.forEach(([sym, px, chg]) => {
    const li = document.createElement("li");
    li.className = "mkt";
    const cls = chg > 0 ? "up" : chg < 0 ? "down" : "";
    li.innerHTML = `<span class="sym">${sym}</span><span class="px">${px}</span>`
      + `<span class="chg ${cls}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span>`;
    el.appendChild(li);
  });
}
function refreshMarkets() {
  fetch("/api/markets").then((r) => r.json()).then(renderMarkets).catch(() => {});
}

function renderCalendar(events) {
  calendarEl.innerHTML = "";
  if (!events || !events.length) {
    calendarEl.innerHTML = '<li class="empty">Calendar is clear.</li>';
    return;
  }
  const now = Date.now() / 1000;
  let marked = false;
  events.forEach((e) => {
    const li = document.createElement("li");
    const when = new Date(e.start_ts * 1000);
    const t = `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`;
    const mins = Math.round(e.start_ts - now);
    let state = "later";
    if (e.start_ts < now) state = "past";
    else if (mins <= 60 && !marked) { state = "next"; marked = true; }
    li.className = state;
    li.textContent = `${t} ${e.title}${e.location ? ` · ${e.location}` : ""}`
      + (state === "next" ? "  ◀ next" : "");
    calendarEl.appendChild(li);
  });
}
function refreshCalendar() {
  fetch("/api/calendar").then((r) => r.json()).then(renderCalendar).catch(() => {});
}
function renderActivity(list) {
  activityEl.innerHTML = "";
  if (!list.length) activityEl.innerHTML = '<li class="empty">No sessions yet.</li>';
  list.slice(0, 6).forEach((a) => {
    const li = document.createElement("li");
    const mins = Math.max(1, Math.round(a.seconds / 60));
    li.textContent = `${a.app} — ${mins} min · ${a.sessions} session${a.sessions === 1 ? "" : "s"}`;
    activityEl.appendChild(li);
  });
}
function renderFleet(devs) {
  fleetEl.innerHTML = "";
  chipFleet.classList.toggle("hidden", !devs.length);
  chipFleet.textContent = `FLEET ${devs.filter((d) => d.online).length}/${devs.length}`;
  if (!devs.length) fleetEl.innerHTML = '<li class="empty">No devices connected.</li>';
  devs.forEach((d) => {
    const li = document.createElement("li");
    const dot = document.createElement("span");
    dot.className = "dot " + (d.online ? "on" : "off");
    li.appendChild(dot);
    const t = d.telemetry || {};
    const bits = [d.name, d.os];
    ["cpu_pct", "ram_pct", "disk_pct", "battery_pct"].forEach((k) => {
      if (t[k] != null) bits.push(`${k.replace("_pct", "")} ${t[k]}%`);
    });
    if (!d.online) bits.push(`offline ${d.seen_ago}s`);
    if (d.activity && d.activity.app) bits.push(`last: ${d.activity.app}`);
    li.appendChild(document.createTextNode(bits.join(" · ")));
    fleetEl.appendChild(li);
  });
}
function renderPreps(preps) {
  prepsEl.innerHTML = "";
  if (!preps.length) prepsEl.innerHTML = '<li class="empty">I\'ll get ahead of things as I learn your rhythm.</li>';
  preps.forEach((p) => {
    const li = document.createElement("li");
    li.textContent = `${p.when} — ${p.label}`;
    prepsEl.appendChild(li);
  });
}
async function refreshLearned() {
  try {
    const d = await (await fetch("/api/learned")).json();
    renderLearned(d.facts, d.habits);
    renderActivity(d.activity || []);
  } catch { /* ignore */ }
}
$("#toggle-panel").onclick = () => $("#panel").classList.toggle("hidden");
$("#clear-facts").onclick = async () => {
  await fetch("/api/facts/clear", { method: "POST" });
  refreshLearned(); toast("Memories cleared.");
};

/* ---------------- proactive + prep banners ---------------- */
let pendingAction = null;
function showSuggestion(text, action) {
  pendingAction = action || null;
  $("#suggestion-text").textContent = text;
  $("#suggestion").classList.remove("hidden");
  clearTimeout(showSuggestion._t);
  showSuggestion._t = setTimeout(() => $("#suggestion").classList.add("hidden"), 25000);
}
$("#suggestion-do").onclick = () => {
  $("#suggestion").classList.add("hidden");
  if (pendingAction) sendChat(pendingAction);
  pendingAction = null;
};
$("#suggestion-no").onclick = () => $("#suggestion").classList.add("hidden");

let pendingPrep = null;
function showPrep(prep) {
  pendingPrep = prep;
  $("#prep-text").textContent = prep.label;
  $("#prep-do").style.display = prep.action ? "" : "none";
  $("#prep-banner").classList.remove("hidden");
  clearTimeout(showPrep._t);
  showPrep._t = setTimeout(() => $("#prep-banner").classList.add("hidden"), 30000);
}
$("#prep-do").onclick = () => {
  $("#prep-banner").classList.add("hidden");
  if (pendingPrep && pendingPrep.action) sendChat(pendingPrep.action);
  pendingPrep = null;
};

/* ---------------- screenshot overlay ---------------- */
function showShot(m) {
  $("#shot-img").src = m.url + (m.url.includes("?") ? "&" : "?") + "t=" + Date.now();
  $("#shot-caption").textContent = m.device || "screen capture";
  $("#shot-overlay").classList.remove("hidden");
}
$("#shot-close").onclick = () => $("#shot-overlay").classList.add("hidden");
$("#shot-overlay").onclick = (e) => {
  if (e.target.id === "shot-overlay") $("#shot-overlay").classList.add("hidden");
};
$("#prep-later").onclick = () => {
  $("#prep-banner").classList.add("hidden");
  if (pendingPrep && ws && ws.readyState === 1)
    ws.send(JSON.stringify({ type: "prep_later", key: pendingPrep.key }));
  pendingPrep = null;
};

let pendingAlert = null;
function showAlert(m) {
  pendingAlert = m.action || null;
  $("#alert-text").textContent = m.text;
  $("#alert-banner").classList.remove("hidden");
  clearTimeout(showAlert._t);
  showAlert._t = setTimeout(() => $("#alert-banner").classList.add("hidden"), 45000);
}
$("#alert-check").onclick = () => {
  $("#alert-banner").classList.add("hidden");
  if (pendingAlert) sendChat(pendingAlert);
  pendingAlert = null;
};
$("#alert-dismiss").onclick = () => $("#alert-banner").classList.add("hidden");

let pendingOffer = null;
function showOffer(m) {
  pendingOffer = m;
  $("#offer-text").textContent = m.text;
  $("#offer-banner").classList.remove("hidden");
  clearTimeout(showOffer._t);
  showOffer._t = setTimeout(() => $("#offer-banner").classList.add("hidden"), 60000);
}
$("#offer-save").onclick = () => {
  $("#offer-banner").classList.add("hidden");
  if (pendingOffer && ws && ws.readyState === 1)
    ws.send(JSON.stringify({ type: "routine_save", name: pendingOffer.name,
                             actions: pendingOffer.actions }));
  pendingOffer = null;
};
$("#offer-nope").onclick = () => {
  $("#offer-banner").classList.add("hidden");
  pendingOffer = null;
};

/* ---------------- websocket ---------------- */
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => setState("idle");
  ws.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch { /* ignore */ } };
  ws.onclose = () => setTimeout(connect, 1500);
}
function handle(m) {
  switch (m.type) {
    case "hello":
      chipMode.textContent = m.voice ? "VOICE MODE" : "CHAT MODE";
      chipBrain.textContent = (m.llm ? m.brain_label : "RULE BRAIN").toUpperCase();
      renderLearned(m.facts, m.habits);
      renderFleet(m.fleet || []);
      renderCalendar(m.calendar || []);
      renderActivity(m.activity || []);
      renderPreps(m.preps || []);
      renderMarkets(m.markets);
      renderHome(m.home);
      renderMusic(m.music);
      renderScenes(m.scenes || []);
      renderSelf(m.self);
      break;
    case "markets": renderMarkets(m); break;
    case "home": renderHome(m); break;
    case "music": renderMusic(m); break;
    case "self": renderSelf(m); break;
    case "state": setState(m.state); break;
    case "level": currentLevel = m.value; break;
    case "user": userLine.textContent = m.text; break;
    case "reply": replyThenIdle(m.reply); refreshCalendar(); break;
    case "screenshot": showShot(m); break;
    case "suggestion": showSuggestion(m.text, m.action); break;
    case "prep": showPrep(m); renderPreps([m]); break;
    case "alert": showAlert(m); break;
    case "routine_offer": showOffer(m); break;
    case "status": toast(m.text, 6000); break;
    case "announce": toast(m.text, 8000); break;
    case "learned":
      renderLearned(m.facts, m.habits);
      if (m.activity) renderActivity(m.activity);
      break;
    case "fleet": renderFleet(m.devices); break;
    case "fleet_event":
      if (m.kind === "service") toast(`${m.device} · ${m.data.name || "service"}: ${m.data.state || "event"}`);
      break;
  }
}

/* ---------------- chat input ---------------- */
function sendChat(text) {
  text = (text || "").trim();
  if (!text || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: "chat", text }));
}
$("#chat-form").onsubmit = (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  sendChat(input.value);
  input.value = "";
};
$("#brief").onclick = () => sendChat("brief me");

/* ---------------- browser push-to-talk ---------------- */
$("#mic").onclick = async () => {
  if (recording) { recording.stop(); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast("This browser can't access a mic."); return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const src = ac.createMediaStreamSource(stream);
    analyser = ac.createAnalyser(); analyser.fftSize = 256;
    levelBuf = new Uint8Array(analyser.frequencyBinCount);
    src.connect(analyser);
    const rec = new MediaRecorder(stream);
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop());
      recording = null; setState("thinking");
      const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      try {
        const res = await fetch("/api/transcribe", { method: "POST", body: blob });
        const data = await res.json();
        if (data.ok) {
          userLine.textContent = data.heard;
          replyThenIdle(data.reply);
          refreshLearned();
        } else {
          toast(data.message || "Transcription failed."); setState("idle");
        }
      } catch {
        toast("Transcription failed."); setState("idle");
      }
    };
    rec.start();
    recording = rec;
    setState("listening");
  } catch {
    toast("Microphone access denied.");
  }
};

refreshCalendar();
refreshMarkets();
connect();
})();
