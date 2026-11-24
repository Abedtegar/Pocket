/* Guardian web — vanilla JS, satu halaman dengan tab. */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TYPE_LABEL = {
  panic: "PANIC — tombol darurat", weapon: "Senjata tajam terdeteksi", hr_high: "Detak jantung tinggi",
  hr_low: "Detak jantung rendah", zone_enter: "Masuk zona rawan", glasses_offline: "Kacamata terputus",
  gps_lost: "GPS hilang", battery_low: "Baterai rendah", battery_critical: "Baterai kritis",
};
const ALARM_TYPES = new Set(["panic", "weapon", "hr_high", "hr_low"]);
const LED_LABEL = { red: "merah", green: "hijau", blue: "biru", yellow: "kuning", purple: "ungu", white: "putih", off: "mati", cyan: "cyan" };

let currentTab = "live";
let lastStatus = null;
let alarmEvent = null;

// ---------------- API ----------------
async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts };
  if (o.body && typeof o.body !== "string") {
    o.body = JSON.stringify(o.body);
    o.headers = { "Content-Type": "application/json", ...(o.headers || {}) };
  }
  const r = await fetch(path, o);
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("login diperlukan"); }
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof body === "object" ? JSON.stringify(body.detail ?? body) : body);
  return body;
}

// ---------------- Login ----------------
function showLogin() { $("#login").classList.remove("hidden"); $("#login-pass").focus(); }
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-err").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: { password: $("#login-pass").value } });
    $("#login").classList.add("hidden");
    $("#login-pass").value = "";
    unlockAudio();
    start();
  } catch (err) { $("#login-err").textContent = "Password salah"; }
});
$("#logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); location.reload(); });

// ---------------- Tab ----------------
$$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  currentTab = name;
  $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  // stream hanya dibuka di tab yang terlihat (hemat CPU SBC)
  setStream($("#live-video"), name === "live" ? "/api/stream?view=processed" : null);
  setStream($("#cam-raw"), name === "camera" ? "/api/stream?view=raw" : null);
  setStream($("#cam-proc"), name === "camera" ? "/api/stream?view=processed" : null);
  if (name === "map") initMap();
  if (name === "zones") initZoneMap();
  if (name === "history") loadHistory();
  if (name === "camera") loadCamera();
  if (name === "settings") loadSettings();
}
function setStream(img, url) {
  if (url) { if (!img.dataset.src) { img.src = url + "&t=" + Date.now(); img.dataset.src = url; } }
  else if (img.dataset.src) { img.removeAttribute("src"); delete img.dataset.src; }
}
$("#live-video").addEventListener("load", () => $("#live-overlay").classList.add("hidden"));
$("#live-video").addEventListener("error", () => {
  $("#live-overlay").classList.remove("hidden");
  const img = $("#live-video");
  delete img.dataset.src;
  setTimeout(() => currentTab === "live" && setStream(img, "/api/stream?view=processed"), 3000);
});

// ---------------- WebSocket ----------------
let ws = null;
function connectWs() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => $("#conn").className = "dot on";
  ws.onclose = (e) => {
    $("#conn").className = "dot off";
    if (e.code === 4401) { showLogin(); return; }
    setTimeout(connectWs, 2000);
  };
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.type === "status") renderStatus(msg.data);
    else if (msg.type === "event") onEvent(msg.data);
    else if (msg.type === "event_update" && currentTab === "history") loadHistory();
  };
}

// ---------------- Status (Live) ----------------
function chip(text, cls) { return `<span class="chip ${cls}">${esc(text)}</span>`; }
function renderStatus(s) {
  lastStatus = s;
  const hr = s.hr;
  $("#s-bpm").textContent = hr.finger && hr.bpm ? hr.bpm : "–";
  $("#s-finger").textContent = hr.age_s == null ? "belum ada data" : (hr.finger ? `${hr.age_s}s lalu` : "sensor tidak menempel");
  const g = s.glasses;
  $("#s-glasses").textContent = g.online ? "Online" : "Offline";
  $("#s-glasses").style.color = g.online ? "var(--ok)" : "var(--bad)";
  const gb = g.batt_mv ? `${(g.batt_mv / 1000).toFixed(2)} V` : "baterai ?";
  $("#s-glasses-sub").textContent = `${gb} · RSSI ${g.rssi ?? "?"} dBm · stream ${s.stream.fps} fps` + (g.online ? "" : ` · ${g.offline_reason || ""}`);
  const p = s.power;
  $("#s-pct").textContent = p.pct ?? "–";
  $("#s-pct").style.color = p.level === "critical" ? "var(--bad)" : p.level === "low" ? "var(--warn)" : "";
  $("#s-power").textContent = p.voltage == null ? (p.enabled ? "membaca…" : "INA219 nonaktif")
    : `${p.voltage.toFixed(2)} V · ${p.current_a.toFixed(2)} A · ${p.power_w.toFixed(1)} W` +
      (p.remaining_h != null ? ` · sisa ±${p.remaining_h} jam` : "") + (p.fake ? " · NILAI PALSU" : "");
  const v = s.vision;
  $("#s-vfps").textContent = v.paused ? "jeda" : v.fps;
  $("#s-dets").textContent = !v.model_ok ? (v.error || "model belum ada") :
    (v.detections.length ? v.detections.map((d) => `${d.label} ${(d.conf * 100).toFixed(0)}%`).join(", ") : "tidak ada objek");
  $("#s-chips").innerHTML = [
    chip(g.online ? "kacamata online" : "kacamata offline", g.online ? "ok" : "bad"),
    chip(s.mqtt ? "MQTT ok" : "MQTT putus", s.mqtt ? "ok" : "bad"),
    chip(s.internet ? "internet ok" : "internet putus", s.internet ? "ok" : "warn"),
    s.gps.enabled ? chip(s.gps.fix ? `GPS fix (${s.gps.sats} sat)` : "GPS belum fix", s.gps.fix ? "ok" : "warn") : "",
    chip(`LED ${LED_LABEL[s.led.color] || s.led.color} ${s.led.pattern}`, ""),
    s.alarm.active ? chip("ALARM belum ditangani", "bad") : "",
    s.recorder.active ? chip(`REC ${s.recorder.frames} frame`, "bad") : "",
  ].join("");
  $("#s-gps").textContent = s.gps.lat != null
    ? `Lokasi: ${s.gps.lat.toFixed(5)}, ${s.gps.lon.toFixed(5)} (${s.gps.fix_age_s}s lalu, HDOP ${s.gps.hdop ?? "?"})` : "Lokasi: belum ada fix GPS";
  if (currentTab === "map") updateMapPosition();
  if (currentTab === "camera") {
    const lat = v.latency_ms || {};
    $("#cam-latency").textContent = `Deteksi ${v.fps} fps · ` + Object.entries(lat).map(([k, x]) => `${k} ${x} ms`).join(" · ") +
      ` · preset: ${s.camera_preset}`;
    renderRecStatus(s.recorder);
  }
  // alarm (panic/weapon/hr) di-ack dari perangkat lain -> tutup banner di sini juga
  if (alarmEvent && ALARM_TYPES.has(alarmEvent.type) && !s.alarm.active) hideAlarm();
}

// ---------------- Alarm ----------------
let audioCtx = null;
function unlockAudio() { try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch (e) {} }
document.addEventListener("click", unlockAudio, { once: true });
function beep(severity) {
  if (!audioCtx) return;
  const n = severity >= 3 ? 6 : severity === 2 ? 4 : 1;
  for (let i = 0; i < n; i++) {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = i % 2 ? 660 : 880;
    g.gain.value = 0.2;
    o.connect(g).connect(audioCtx.destination);
    const t = audioCtx.currentTime + i * 0.3;
    o.start(t); o.stop(t + 0.22);
  }
}
function onEvent(ev) {
  beep(ev.severity);
  if (ev.severity >= 2) showAlarm(ev);
  if (navigator.vibrate && ev.severity >= 2) navigator.vibrate([300, 100, 300]);
  if (currentTab === "history") loadHistory();
}
function showAlarm(ev) {
  alarmEvent = ev;
  $("#alarm-title").textContent = TYPE_LABEL[ev.type] || ev.type;
  const d = ev.data || {};
  const parts = [new Date(ev.ts).toLocaleTimeString("id-ID")];
  if (d.label) parts.push(`${d.label} ${(d.conf * 100).toFixed(0)}%`);
  if (d.bpm) parts.push(`${d.bpm} bpm`);
  if (ev.lat != null) parts.push(`${ev.lat.toFixed(5)}, ${ev.lon.toFixed(5)}`);
  $("#alarm-detail").textContent = parts.join(" · ");
  $("#alarm").classList.remove("hidden");
}
function hideAlarm() { alarmEvent = null; $("#alarm").classList.add("hidden"); }
$("#alarm-ack").addEventListener("click", async () => {
  if (alarmEvent) await api(`/api/events/${alarmEvent.id}/ack`, { method: "POST" }).catch(() => {});
  hideAlarm();
  if (currentTab === "history") loadHistory();
});

// ---------------- Peta ----------------
let map, posMarker, trackLine, zoneLayer, zoneMap, zoneMapLayer, zonePick;
const TILE = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_OPT = { maxZoom: 19, attribution: "© OpenStreetMap" };
function defaultCenter() { return lastStatus?.gps?.lat != null ? [lastStatus.gps.lat, lastStatus.gps.lon] : [-7.28, 112.79]; }
function initMap() {
  if (typeof L === "undefined") { $("#map-info").textContent = "Leaflet gagal dimuat (tidak ada internet). Koordinat tetap tampil di tab Live."; return; }
  if (!map) {
    map = L.map("map").setView(defaultCenter(), 16);
    L.tileLayer(TILE, TILE_OPT).addTo(map);
    trackLine = L.polyline([], { color: "#3b82f6" }).addTo(map);
    zoneLayer = L.layerGroup().addTo(map);
  }
  setTimeout(() => map.invalidateSize(), 50);
  loadTrack(); drawZones(zoneLayer);
  updateMapPosition(true);
}
function updateMapPosition(center) {
  if (!map || !lastStatus) return;
  const g = lastStatus.gps;
  if (g.lat == null) { $("#map-info").textContent = "Posisi belum tersedia"; return; }
  const ll = [g.lat, g.lon];
  if (!posMarker) posMarker = L.circleMarker(ll, { radius: 8, color: "#fff", fillColor: "#ef4444", fillOpacity: 1 }).addTo(map);
  posMarker.setLatLng(ll);
  if (center) map.setView(ll);
  $("#map-info").innerHTML = `Posisi: <b>${g.lat.toFixed(6)}, ${g.lon.toFixed(6)}</b> · ${g.fix ? "fix" : "tanpa fix"} · ${g.fix_age_s}s lalu · ` +
    `<a href="https://maps.google.com/?q=${g.lat},${g.lon}" target="_blank" rel="noopener">Google Maps</a>`;
}
async function loadTrack() {
  const pts = await api("/api/track?minutes=60").catch(() => []);
  if (trackLine) trackLine.setLatLngs(pts.map((p) => [p.lat, p.lon]));
}
async function drawZones(layer) {
  if (!layer) return [];
  const zones = await api("/api/zones").catch(() => []);
  layer.clearLayers();
  zones.forEach((z) => L.circle([z.lat, z.lon], { radius: z.radius_m, color: z.active ? "#ef4444" : "#888", weight: 2, fillOpacity: 0.12 })
    .bindTooltip(z.name).addTo(layer));
  return zones;
}

// ---------------- Zona ----------------
function initZoneMap() {
  if (typeof L !== "undefined" && !zoneMap) {
    zoneMap = L.map("zone-map").setView(defaultCenter(), 15);
    L.tileLayer(TILE, TILE_OPT).addTo(zoneMap);
    zoneMapLayer = L.layerGroup().addTo(zoneMap);
    zoneMap.on("click", (e) => {
      $("#zone-lat").value = e.latlng.lat.toFixed(6);
      $("#zone-lon").value = e.latlng.lng.toFixed(6);
      previewZone();
    });
  }
  if (zoneMap) setTimeout(() => zoneMap.invalidateSize(), 50);
  loadZones();
}
function previewZone() {
  if (!zoneMap) return;
  const lat = parseFloat($("#zone-lat").value), lon = parseFloat($("#zone-lon").value), r = parseFloat($("#zone-radius").value);
  if (isNaN(lat) || isNaN(lon)) return;
  if (zonePick) zonePick.remove();
  zonePick = L.circle([lat, lon], { radius: r || 100, color: "#3b82f6", dashArray: "4" }).addTo(zoneMap);
}
$("#zone-radius").addEventListener("input", previewZone);
async function loadZones() {
  const zones = zoneMapLayer ? await drawZones(zoneMapLayer) : await api("/api/zones");
  $("#zone-list").innerHTML = zones.length ? zones.map((z) => `
    <div class="card row-form">
      <b>${esc(z.name)}</b><span class="small muted">${z.lat.toFixed(5)}, ${z.lon.toFixed(5)} · ${z.radius_m} m</span>
      <label class="small"><input type="checkbox" data-zone-toggle="${z.id}" ${z.active ? "checked" : ""}> aktif</label>
      <button class="btn" data-zone-del="${z.id}">Hapus</button>
    </div>`).join("") : `<p class="muted">Belum ada zona.</p>`;
}
$("#zone-list").addEventListener("click", async (e) => {
  const del = e.target.dataset.zoneDel, tog = e.target.dataset.zoneToggle;
  if (del && confirm("Hapus zona ini?")) { await api(`/api/zones/${del}`, { method: "DELETE" }); loadZones(); }
  if (tog) { await api(`/api/zones/${tog}`, { method: "PUT", body: { active: e.target.checked } }); loadZones(); }
});
$("#zone-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/zones", { method: "POST", body: {
    name: $("#zone-name").value, radius_m: parseFloat($("#zone-radius").value),
    lat: parseFloat($("#zone-lat").value), lon: parseFloat($("#zone-lon").value) } });
  $("#zone-name").value = "";
  if (zonePick) { zonePick.remove(); zonePick = null; }
  loadZones();
});

// ---------------- Riwayat ----------------
async function loadHistory() {
  const type = $("#hist-type").value;
  const evs = await api(`/api/events?limit=100${type ? "&type=" + type : ""}`).catch(() => []);
  $("#hist-list").innerHTML = evs.length ? evs.map((ev) => {
    const d = ev.data || {};
    const info = [];
    if (d.label) info.push(`${esc(d.label)} ${(d.conf * 100).toFixed(0)}%`);
    if (d.bpm) info.push(`${d.bpm} bpm`);
    if (d.zone) info.push(`zona ${esc(d.zone)}`);
    if (d.pct != null) info.push(`${d.pct}%`);
    if (d.reason) info.push(esc(d.reason));
    if (d.test) info.push("uji");
    const loc = ev.lat != null ? `<a href="https://maps.google.com/?q=${ev.lat},${ev.lon}" target="_blank" rel="noopener">${ev.lat.toFixed(5)}, ${ev.lon.toFixed(5)}</a> (${esc(ev.loc_src)})` : "lokasi tidak ada";
    return `<div class="card event sev${ev.severity} ${ev.acknowledged ? "acked" : ""}">
      ${ev.snapshot ? `<a href="/${esc(ev.snapshot)}" target="_blank"><img loading="lazy" src="/${esc(ev.snapshot)}" alt="snapshot"></a>` : ""}
      <div class="meta">
        <b>${esc(TYPE_LABEL[ev.type] || ev.type)}</b>
        ${ev.notified ? `<span class="badge">Telegram ✓</span>` : ""}${ev.acknowledged ? `<span class="badge">ditangani</span>` : ""}
        <div class="small muted">${new Date(ev.ts).toLocaleString("id-ID")} · ${info.join(" · ")}</div>
        <div class="small">${loc}</div>
      </div>
      ${ev.acknowledged ? "" : `<button class="btn" data-ack="${ev.id}">Tandai ditangani</button>`}
    </div>`;
  }).join("") : `<p class="muted">Belum ada event.</p>`;
}
$("#hist-type").addEventListener("change", loadHistory);
$("#hist-refresh").addEventListener("click", loadHistory);
$("#hist-ackall").addEventListener("click", async () => { await api("/api/events/ack_all", { method: "POST" }); hideAlarm(); loadHistory(); });
$("#hist-list").addEventListener("click", async (e) => {
  const id = e.target.dataset.ack;
  if (id) { await api(`/api/events/${id}/ack`, { method: "POST" }); if (alarmEvent?.id === id) hideAlarm(); loadHistory(); }
});

// ---------------- Kamera ----------------
const SENSOR_CTRL = [
  ["framesize", "select", ["QQVGA", "QVGA", "CIF", "VGA", "SVGA"]],
  ["quality", "range", 4, 63, 1], ["brightness", "range", -2, 2, 1], ["contrast", "range", -2, 2, 1],
  ["saturation", "range", -2, 2, 1], ["sharpness", "range", -2, 2, 1],
  ["awb", "check"], ["wb_mode", "select", [0, 1, 2, 3, 4], ["auto", "sunny", "cloudy", "office", "home"]],
  ["aec", "check"], ["aec_value", "range", 0, 1200, 10], ["ae_level", "range", -2, 2, 1],
  ["agc", "check"], ["agc_gain", "range", 0, 30, 1], ["gainceiling", "range", 0, 6, 1],
  ["hmirror", "check"], ["vflip", "check"], ["lenc", "check"], ["bpc", "check"], ["wpc", "check"],
  ["raw_gma", "check"], ["dcw", "check"],
];
const PRE_CTRL = [
  ["enabled", "check"], ["rotate", "select", [0, 90, 180, 270]], ["flip", "select", ["none", "h", "v"]],
  ["brightness", "range", -100, 100, 1], ["contrast", "range", 0.5, 2, 0.05], ["saturation", "range", 0, 2, 0.05],
  ["gamma", "range", 0.5, 2.5, 0.05], ["clahe", "check"], ["clahe_clip", "range", 0.5, 8, 0.1],
  ["sharpen", "range", 0, 1, 0.05], ["denoise", "check"], ["roi", "text"],
];

function buildControls(container, defs, values, onChange) {
  container.innerHTML = "";
  defs.forEach(([key, kind, a, b, c]) => {
    const row = document.createElement("div");
    row.className = "ctrl";
    const v = values[key];
    let input;
    if (kind === "range") {
      input = Object.assign(document.createElement("input"), { type: "range", min: a, max: b, step: c, value: v ?? 0 });
    } else if (kind === "check") {
      input = Object.assign(document.createElement("input"), { type: "checkbox", checked: !!v });
    } else if (kind === "select") {
      input = document.createElement("select");
      a.forEach((opt, i) => input.add(new Option(b ? b[i] : opt, opt)));
      input.value = v;
    } else {
      input = Object.assign(document.createElement("input"), { type: "text", placeholder: "x,y,w,h (0-1)", value: Array.isArray(v) ? v.join(",") : "" });
    }
    const out = document.createElement("output");
    out.textContent = kind === "range" ? v : "";
    row.append(Object.assign(document.createElement("span"), { textContent: key }), input, out);
    const ev = kind === "text" ? "change" : "input";
    input.addEventListener(ev, () => {
      let val;
      if (kind === "range") { val = parseFloat(input.value); out.textContent = val; }
      else if (kind === "check") val = input.checked ? (container.id === "sensor-controls" ? 1 : true) : (container.id === "sensor-controls" ? 0 : false);
      else if (kind === "select") val = isNaN(Number(input.value)) ? input.value : Number(input.value);
      else val = input.value.trim() ? input.value.split(",").map(Number) : null;
      onChange(key, val);
    });
    container.append(row);
  });
}
function debounced(sender) {
  let pending = {}, timer = null;
  return (key, val) => {
    pending[key] = val;
    clearTimeout(timer);
    timer = setTimeout(() => { const p = pending; pending = {}; sender(p); }, 300);
  };
}
const sendSensor = debounced(async (p) => {
  try {
    const r = await api("/api/camera/sensor", { method: "PUT", body: p });
    $("#sensor-msg").textContent = Object.keys(r.errors || {}).length ? "Ditolak: " + JSON.stringify(r.errors) : "Terkirim ke kacamata: " + Object.keys(r.applied).join(", ");
  } catch (e) { $("#sensor-msg").textContent = "Gagal: " + e.message; }
});
const sendPre = debounced(async (p) => {
  try { await api("/api/camera/preprocess", { method: "PUT", body: p }); $("#pre-msg").textContent = "Diterapkan"; }
  catch (e) { $("#pre-msg").textContent = "Gagal: " + e.message; }
});
async function loadCamera() {
  const [sensor, pre, presets] = await Promise.all([api("/api/camera/sensor"), api("/api/camera/preprocess"), api("/api/camera/presets")]);
  buildControls($("#sensor-controls"), SENSOR_CTRL, sensor.sensor, sendSensor);
  buildControls($("#pre-controls"), PRE_CTRL, pre, sendPre);
  $("#sensor-msg").textContent = sensor.esp_state ? "State ESP diterima" : "Belum ada glasses/camera/state dari ESP";
  const sel = $("#preset-select");
  sel.innerHTML = "";
  presets.presets.forEach((p) => sel.add(new Option(p.name, p.name)));
  sel.value = presets.active;
  renderRecStatus(lastStatus?.recorder);
}
$("#preset-apply").addEventListener("click", async () => { await api(`/api/camera/presets/${encodeURIComponent($("#preset-select").value)}/apply`, { method: "POST" }); loadCamera(); });
$("#preset-save").addEventListener("click", async () => {
  const name = $("#preset-name").value.trim();
  if (!name) return alert("Isi nama preset");
  await api("/api/camera/presets", { method: "POST", body: { name } });
  $("#preset-name").value = ""; loadCamera();
});
$("#preset-delete").addEventListener("click", async () => {
  const name = $("#preset-select").value;
  if (!confirm(`Hapus preset ${name}?`)) return;
  try { await api(`/api/camera/presets/${encodeURIComponent(name)}`, { method: "DELETE" }); } catch (e) { alert(e.message); }
  loadCamera();
});
$("#preset-reset").addEventListener("click", async () => { if (confirm("Kembalikan ke default config.yaml?")) { await api("/api/camera/reset", { method: "POST" }); loadCamera(); } });

// rekam dataset
function renderRecStatus(r) {
  if (!r) return;
  $("#rec-status").textContent = r.active ? `● Merekam ${r.session} — ${r.frames} frame, ${r.fps} fps` :
    (r.session ? `Terakhir: ${r.session} — ${r.frames} frame, ${r.fps} fps` : "");
  $("#rec-start").disabled = r.active; $("#rec-stop").disabled = !r.active;
}
$("#rec-start").addEventListener("click", async () => {
  const f = new FormData($("#rec-form"));
  const body = Object.fromEntries(f.entries());
  body.pause_detector = $("#rec-form").pause_detector.checked;
  try { renderRecStatus(await api("/api/record/start", { method: "POST", body })); } catch (e) { alert(e.message); }
});
$("#rec-stop").addEventListener("click", async () => {
  try { const r = await api("/api/record/stop", { method: "POST" }); alert(`Selesai: ${r.session}\n${r.frames} frame, ${r.fps} fps, ${r.duration_s} s`); }
  catch (e) { alert(e.message); }
});

// ---------------- Pengaturan ----------------
async function loadSettings() {
  const s = await api("/api/settings");
  $$("#settings-form [name]").forEach((el) => {
    const [sec, key] = el.name.split(".");
    const v = s[sec]?.[key];
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = Array.isArray(v) ? v.join(",") : (v ?? "");
  });
  $("#cooldowns").innerHTML = Object.entries(s.alerts.cooldown_s || {}).map(([k, v]) =>
    `<label>${esc(k)} <input type="number" min="0" max="86400" data-cooldown="${esc(k)}" value="${v}"></label>`).join("");
}
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {};
  $$("#settings-form [name]").forEach((el) => {
    const [sec, key] = el.name.split(".");
    body[sec] = body[sec] || {};
    body[sec][key] = el.type === "checkbox" ? el.checked : el.value;
  });
  body.alerts = { cooldown_s: {} };
  $$("[data-cooldown]").forEach((el) => body.alerts.cooldown_s[el.dataset.cooldown] = Number(el.value));
  try { await api("/api/settings", { method: "PUT", body }); $("#settings-msg").textContent = "Tersimpan ✓"; }
  catch (err) { $("#settings-msg").textContent = "Gagal: " + err.message; }
});
async function test(path, body) {
  try { const r = await api(path, { method: "POST", body: body || {} }); $("#test-msg").textContent = "OK " + (r && r.type ? r.type : ""); }
  catch (e) { $("#test-msg").textContent = "Gagal: " + e.message; }
}
$("#test-speaker").addEventListener("click", () => test("/api/test/speaker", { sound: $("#test-sound").value }));
$("#test-telegram").addEventListener("click", () => test("/api/test/telegram"));
$("#test-led").addEventListener("click", () => test("/api/test/led"));
$("#test-event-btn").addEventListener("click", () => test("/api/test/event", { type: $("#test-event").value }));

// ---------------- Mulai ----------------
let started = false;
function start() {
  if (started) return;
  started = true;
  connectWs();
  showTab(currentTab);
}
(async () => {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  try {
    const a = await api("/api/auth");
    if (a.auth_required && !a.logged_in) showLogin(); else start();
  } catch (e) { showLogin(); }
})();
