/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Glanceboard — Frontend JavaScript
 *
 * Multi-user dashboard with Google Sign-In, Calendar API integration,
 * weather settings, and per-user Firestore scoping.
 */

// ─── Local API Shims ───────────────────────────────────────────

import { DEFAULT_TIMEZONE } from "./config.js";

const app = {};
const auth = { currentUser: { uid: "local" } };
const db = {};
const stg = {};
const functions = {};

function initializeApp() { return app; }
function getAuth() { return auth; }
function signInAnonymously() { return Promise.resolve(); }
function onAuthStateChanged(a, cb) { cb(auth.currentUser); }
function signOut() { return Promise.resolve(); }

function getFirestore() { return db; }
function doc(db, path) { return { path }; }
function collection(db, path) { return { path }; }

let _localConfig = {};

async function _ensureConfig() {
  try {
    const res = await fetch("/api/config");
    _localConfig = await res.json();
  } catch (e) {
    console.warn("Failed to fetch local config", e);
  }
}

async function getDoc(docRef) {
  await _ensureConfig();
  const path = docRef.path || "";
  let data = null;
  
  if (path.includes("status")) {
    data = _localConfig.status || null;
  } else if (path.includes("prompt")) {
    data = _localConfig.prompt_template ? { template: _localConfig.prompt_template } : null;
  } else if (path.includes("subscription")) {
    data = { tier: "self_hosted", status: "active" };
  } else if (path.includes("regen_limit")) {
    data = null;
  } else if (path.includes("characters/")) {
    // Individual character lookup
    const charId = path.split("characters/")[1];
    const chars = _localConfig.characters || [];
    data = chars.find(c => c.id === charId) || null;
  } else if (path.includes("devices/")) {
    // Device doc — return config as device data
    data = {
      name: _localConfig.device_name || "Local Display",
      image_model: _localConfig.image_model || "google/gemini-3-pro-image",
      aesthetic: _localConfig.aesthetic || "whimsical",
      characters_enabled: _localConfig.characters_enabled !== false,
      selected_characters: _localConfig.selected_characters || [],
    };
  } else if (path.includes("account") || path.includes("config") || path.includes("settings")) {
    data = Object.keys(_localConfig).length > 0 ? _localConfig : null;
  } else {
    // Default: return config
    data = Object.keys(_localConfig).length > 0 ? _localConfig : null;
  }
  
  if (data && typeof data === "object" && Object.keys(data).length > 0) {
    return { exists: () => true, data: () => data };
  }
  return { exists: () => false, data: () => null };
}

async function getDocs(collRef) {
  await _ensureConfig();
  if (collRef.path.includes("characters")) {
    const chars = _localConfig.characters || [];
    return {
      size: chars.length,
      empty: chars.length === 0,
      forEach: (cb) => {
        chars.forEach(c => cb({ id: c.id, data: () => c, reference: { delete: async () => {} } }));
      }
    };
  } else if (collRef.path.includes("devices")) {
    return {
      empty: false,
      forEach: (cb) => {
        cb({ id: "default", data: () => ({ name: "Local Display" }), reference: { collection: () => ({ document: () => ({ get: async () => ({ exists: () => false }) }) }) } });
      }
    };
  }
  return { empty: true, forEach: () => {} };
}

async function setDoc(docRef, data, options) {
  const path = docRef.path || "";
  
  if (path.includes("characters/")) {
    // Save character to characters array
    const charId = path.split("characters/")[1];
    if (!_localConfig.characters) _localConfig.characters = [];
    const idx = _localConfig.characters.findIndex(c => c.id === charId);
    const charData = { ...data, id: charId };
    if (idx >= 0) {
      _localConfig.characters[idx] = charData;
    } else {
      _localConfig.characters.push(charData);
    }
  } else if (path.includes("prompt")) {
    _localConfig.prompt_template = data.template || "";
  } else {
    // Merge into config
    if (options?.merge) {
      Object.assign(_localConfig, data);
    } else {
      Object.assign(_localConfig, data);
    }
  }
  
  // Persist to server
  await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(_localConfig)
  });
}

async function updateDoc(docRef, data) {
  await setDoc(docRef, data);
}

async function deleteDoc(docRef) {
  const path = docRef.path || "";
  if (path.includes("characters/")) {
    const charId = path.split("characters/")[1];
    if (_localConfig.characters) {
      _localConfig.characters = _localConfig.characters.filter(c => c.id !== charId);
    }
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_localConfig)
    });
  }
}

function onSnapshot(docRef, cb) {
  // trigger initial
  getDoc(docRef).then(cb);
  const interval = setInterval(async () => {
    const d = await getDoc(docRef);
    cb(d);
  }, 5000);
  return () => clearInterval(interval);
}

function getFunctions() { return functions; }
function httpsCallable(funcs, name) {
  return async (data) => {
    if (name === "preview_prompt") {
      const res = await fetch("/api/preview");
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Preview failed");
      }
      return { data: await res.json() };
    } else if (name === "generate_display") {
      const res = await fetch("/api/generate?force=true", { method: "POST" });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Generation failed");
      }
      return { data: await res.json() };
    }
    return { data: {} };
  };
}

function getStorage() { return stg; }
function storageRef(storage, path) { return { path, _uploadedUrl: null }; }
async function uploadBytes(ref, file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: formData });
  const data = await res.json();
  ref._uploadedUrl = data.url;
}
async function getDownloadURL(ref) { return ref._uploadedUrl || ""; }


// ─── State ─────────────────────────────────────────────────────
let currentUser = null;
let isSignUp = false;
let calendarConnected = false;
let currentDeviceId = "default";
let devices = []; // Array of {id, name, aesthetic, ...}
let onboardingData = {
  latitude: null,
  longitude: null,
  location_name: "",
  temp_unit: "celsius",
  calendar_id: "primary",
};

// ─── Layout Builder State ──────────────────────────────────────
const WIDGETS = {
  calendar:  { icon: "📅", name: "Calendar",   preview: "9am Meeting\n12pm Lunch\n3pm Workshop", needsConfig: true, configType: "calendar" },
  upcoming:  { icon: "🔮", name: "Coming Up",  preview: "🎂 Mum's Birthday (3 days)\n🏖️ Beach Trip (Sat)", needsConfig: false },
  weather:   { icon: "🌤️", name: "Weather",    preview: "☀️ 24°C Sunny\nH:28° L:18°", needsConfig: true, configType: "location" },
  sports:    { icon: "⚽", name: "Sports",     preview: "Arsenal\nWon 3-1 ✨", needsConfig: true, configType: "sports" },
  quote:     { icon: "💬", name: "Quote",      preview: "\"The only way to do\ngreat work is to love\nwhat you do.\"", needsConfig: false },
  news:      { icon: "📰", name: "News",       preview: "Top Stories Today\n📌 Breaking: ...", needsConfig: false },
  history:   { icon: "📜", name: "History",    preview: "On this day in 1969\nApollo 11 landed 🌙", needsConfig: false },
  countdown: { icon: "⏳", name: "Countdown",  preview: "12 days until\nHoliday! 🏖️", needsConfig: true, configType: "countdown" },
  stocks:    { icon: "📊", name: "Stocks",     preview: "GOOG ▲ $182.45\n+1.2% today", needsConfig: true, configType: "stocks" },
  email:     { icon: "📧", name: "Email",      preview: "3 unread\n📬 School newsletter\n📦 Amazon delivery", needsConfig: true, configType: "email" },
};

const GRID_COLS = 12;
const GRID_ROWS = 8;
const DEFAULT_WIDGET_SIZE = { cols: 2, rows: 2 };
const MIN_WIDGET_SIZE = { cols: 2, rows: 2 };

let placements = {};    // widgetKey -> { col, row, cols, rows }
let widgetConfigs = {}; // widgetKey -> config object
let layoutInitialized = false;

// ─── QR Code Device Detection ──────────────────────────────────
// When a user scans the QR code on their Glanceboard, the URL contains
// ?device_id=<MAC_ADDRESS>. We store this and auto-register after auth.
const _qrParams = new URLSearchParams(window.location.search);
const pendingDeviceId = _qrParams.get("device_id") || null;
if (pendingDeviceId) {
  console.log(`QR code device detected: ${pendingDeviceId}`);
}

// ─── Helpers ───────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function userPath(sub) {
  return `users/${currentUser.uid}/${sub}`;
}

function devicePath(sub) {
  return `users/${currentUser.uid}/devices/${currentDeviceId}/${sub}`;
}

function showScreen(id) {
  $$(".screen").forEach((s) => s.classList.remove("active"));
  $(`#${id}`).classList.add("active");
}

function showPage(name) {
  $$(".page").forEach((p) => p.classList.remove("active"));
  $(`#page-${name}`).classList.add("active");
  $$(".nav-link").forEach((l) => l.classList.remove("active"));
  $(`.nav-link[data-page="${name}"]`)?.classList.add("active");
}

function toast(msg, type = "info") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast ${type}`;
  t.classList.remove("hidden");
  setTimeout(() => t.classList.add("hidden"), 3500);
}

// No auth needed for self-hosted — just init immediately
currentUser = { uid: "local" };

// Init the app (modules are deferred, so DOM is already ready)
(async () => {
  try {
    const res = await fetch("/api/config");
    _localConfig = await res.json();
  } catch (e) {
    _localConfig = {};
  }

  devices = [{ id: "default", name: "Local Display" }];
  currentDeviceId = "default";

  if (!_localConfig.ical_url && !_localConfig.openrouter_api_key && !_localConfig.api_key) {
    showScreen("onboarding-screen");
  } else {
    showScreen("main-screen");
    loadDashboard();
  }
})();

$("#sign-out-btn")?.addEventListener("click", () => signOut(auth));

// ─── Aesthetic radio toggle ────────────────────────────────────
document.querySelectorAll('input[name="aesthetic"]').forEach(radio => {
  radio.addEventListener("change", () => {
    const customGroup = $("#custom-aesthetic-group");
    if (customGroup) {
      customGroup.classList.toggle("hidden", radio.value !== "custom");
    }
    if (radio.value === "custom") {
      $("#custom-aesthetic-input")?.focus();
    }
  });
});

// ─── Calendar (iCal URL — self-hosted) ─────────────────────────
// Calendar is configured via iCal URL in settings/onboarding.
// No OAuth needed for self-hosted.

// ─── Geocoding (Open-Meteo) ────────────────────────────────────

async function geocodeLocation(query) {
  try {
    const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=1&language=en&format=json`;
    const response = await fetch(url);
    const data = await response.json();

    if (!data.results || data.results.length === 0) {
      return null;
    }

    const result = data.results[0];
    return {
      name: result.name,
      country: result.country || "",
      admin1: result.admin1 || "",
      latitude: result.latitude,
      longitude: result.longitude,
    };
  } catch (err) {
    console.error("Geocoding error:", err);
    return null;
  }
}

// ─── Onboarding ────────────────────────────────────────────────

function showOnboardStep(step) {
  $$(".onboard-step").forEach((s) => s.classList.remove("active"));
  $(`#onboard-step-${step}`)?.classList.add("active");
}

// Provider dropdown — update help text
function updateApiHelp(providerSelect, helpEl, inputEl) {
  const provider = providerSelect.value;
  if (provider === "google") {
    helpEl.innerHTML = 'Get one at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio → Create API Key</a>';
    inputEl.placeholder = "AIza...";
  } else {
    helpEl.innerHTML = 'Get one at <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener">openrouter.ai/settings/keys</a>';
    inputEl.placeholder = "sk-or-v1-...";
  }
  // Filter model dropdown to match provider
  filterModelsByProvider(provider);
}

/**
 * Show/hide model optgroups based on selected API provider.
 * Google AI Studio → only Google models.
 * OpenRouter → all models (it proxies multiple providers).
 */
function filterModelsByProvider(provider) {
  const modelSelect = $("#setting-model");
  if (!modelSelect) return;

  const optgroups = modelSelect.querySelectorAll("optgroup");
  optgroups.forEach((group) => {
    const label = (group.label || "").toLowerCase();
    if (provider === "google") {
      // Only show Google models for AI Studio users
      group.style.display = label.includes("google") || label.includes("gemini") ? "" : "none";
      // Also disable hidden options so they can't be submitted
      group.querySelectorAll("option").forEach((opt) => {
        opt.disabled = group.style.display === "none";
      });
    } else {
      // OpenRouter: show all
      group.style.display = "";
      group.querySelectorAll("option").forEach((opt) => {
        opt.disabled = false;
      });
    }
  });

  // If the currently selected model is now hidden/disabled, reset to first visible option
  const selectedOption = modelSelect.options[modelSelect.selectedIndex];
  if (selectedOption && selectedOption.disabled) {
    const firstVisible = modelSelect.querySelector("option:not([disabled])");
    if (firstVisible) modelSelect.value = firstVisible.value;
  }
}

// Onboarding provider switch
$("#onboard-api-provider")?.addEventListener("change", () => {
  updateApiHelp($("#onboard-api-provider"), $("#onboard-api-help"), $("#onboard-api-key"));
});

// Settings provider switch
$("#setting-api-provider")?.addEventListener("change", () => {
  updateApiHelp($("#setting-api-provider"), $("#setting-api-help"), $("#setting-api-key"));
});

// Step 1: API Key → Next
$("#onboard-next-1").addEventListener("click", () => {
  const apiKey = $("#onboard-api-key").value.trim();
  if (!apiKey) {
    toast("Please enter an API key.", "error");
    return;
  }
  showOnboardStep(2);
});

// Step 1: Skip
$("#onboard-skip")?.addEventListener("click", async () => {
  await setDoc(doc(db, userPath("settings/config")), {
    setup_complete: true,
    timezone: DEFAULT_TIMEZONE,
  });
  showScreen("main-screen");
  loadDashboard();
});

// Step 2: Calendar/iCal → Next
$("#onboard-next-2").addEventListener("click", () => {
  showOnboardStep(3);
});

// Step 2: Back
$("#onboard-back-2").addEventListener("click", () => showOnboardStep(1));

// Step 4: Geocode location
$("#onboard-geocode-btn").addEventListener("click", async () => {
  const query = $("#onboard-location").value.trim();
  if (!query) {
    toast("Enter a city or suburb name.", "error");
    return;
  }

  $("#onboard-geocode-btn").disabled = true;
  $("#onboard-geocode-btn").textContent = "...";

  const result = await geocodeLocation(query);

  $("#onboard-geocode-btn").disabled = false;
  $("#onboard-geocode-btn").textContent = "Find";

  if (result) {
    onboardingData.latitude = result.latitude;
    onboardingData.longitude = result.longitude;
    onboardingData.location_name = result.name;
    const loc = [result.name, result.admin1, result.country]
      .filter(Boolean)
      .join(", ");
    $("#onboard-location-result").textContent = `✅ Found: ${loc} (${result.latitude.toFixed(2)}, ${result.longitude.toFixed(2)})`;
    $("#onboard-location-result").className = "help-text success";
  } else {
    $("#onboard-location-result").textContent =
      "❌ Location not found. Try a different name.";
    $("#onboard-location-result").className = "help-text error";
  }
});

// Step 3: Next → Summary
$("#onboard-next-3")?.addEventListener("click", () => {
  onboardingData.temp_unit =
    document.querySelector('input[name="onboard-temp-unit"]:checked')?.value ||
    "celsius";
  showOnboardStep(4);

  // Update summary
  $("#summary-tier").textContent = "Self-Hosted ✓";
  $("#summary-api").textContent = "API key configured ✓";
  const icalUrl = $("#onboard-ical")?.value?.trim();
  $("#summary-cal").textContent = icalUrl
    ? "iCal URL configured ✓"
    : "Calendar not configured (you can add it in Settings)";
  $("#summary-weather").textContent = onboardingData.latitude
    ? `Weather for ${onboardingData.location_name} ✓`
    : "Weather not configured (you can add it in Settings)";

  // Show/hide device info
  if (pendingDeviceId) {
    $("#onboard-device-info").style.display = "";
    $("#onboard-no-device-info").style.display = "none";
  }
});

// Step 3: Back
$("#onboard-back-3")?.addEventListener("click", () => showOnboardStep(2));

// Step 5: Finish
$("#onboard-finish").addEventListener("click", async () => {
  const apiKey = $("#onboard-api-key")?.value?.trim() || "";
  const icalUrl = $("#onboard-ical")?.value?.trim() || "";
  const timezone = $("#onboard-timezone").value;

  const provider = $("#onboard-api-provider")?.value || "google";

  const config = {
    api_provider: provider,
    openrouter_api_key: apiKey,
    ical_url: icalUrl,
    timezone: timezone,
    image_model: "google/gemini-3-pro-image",
    characters_enabled: true,
    setup_complete: true,
  };

  if (onboardingData.latitude && onboardingData.longitude) {
    config.latitude = onboardingData.latitude;
    config.longitude = onboardingData.longitude;
    config.location_name = onboardingData.location_name;
    config.temp_unit = onboardingData.temp_unit;
  }

  await setDoc(doc(db, userPath("settings/config")), config);

  showScreen("main-screen");
  loadDashboard();
  toast("Setup complete! Generate your first image.", "success");
});


// ─── Dashboard ─────────────────────────────────────────────────

async function loadDashboard() {
  // Load status (try device-scoped first, then legacy)
  try {
    let statusDoc = await getDoc(doc(db, devicePath("status/status")));
    if (!statusDoc.exists()) {
      // Legacy fallback
      statusDoc = await getDoc(doc(db, userPath("settings/status")));
    }
    if (statusDoc.exists()) {
      const s = statusDoc.data();
      if (s.image_url) {
        // Use local image path with cache buster
        const freshUrl = `${s.image_url}?t=${Date.now()}`;
        $("#latest-image-container").innerHTML = `<img src="${freshUrl}" alt="Latest display" class="display-image">`;
      }
      if (s.last_generated) {
        const d = new Date(s.last_generated);
        $("#stat-last-gen").textContent = d.toLocaleString();
      }
      if (s.last_mode) {
        const modeText = s.last_banner || (s.last_mode === "tomorrow" ? "Tomorrow's Events" : "Today's Events");
        $("#stat-mode").textContent = modeText;
      }
      if (s.events_count !== undefined) {
        $("#stat-events").textContent = s.events_count;
      }
      if (s.last_weather) {
        $("#stat-weather").textContent = s.last_weather;
      } else {
        $("#stat-weather").textContent = "Not configured";
      }
      if (s.last_prompt) {
        $("#last-prompt-card").classList.remove("hidden");
        $("#last-prompt-text").textContent = s.last_prompt;
      }
    }
  } catch (e) {
    console.error(e);
  }

  // Hosted tier users get unlimited regens (they use their own API key)
  try {
    updateRegenUI(-1, -1); // unlimited
  } catch (e) {
    console.error("regen limit load:", e);
  }

  // Load settings for stats (try account first, then legacy config)
  try {
    let configDoc = await getDoc(doc(db, userPath("settings/account")));
    if (!configDoc.exists()) {
      configDoc = await getDoc(doc(db, userPath("settings/config")));
    }

    // Load device config for model/aesthetic
    let deviceDoc = await getDoc(doc(db, devicePath("")));
    const deviceData = deviceDoc.exists() ? deviceDoc.data() : {};

    if (configDoc.exists()) {
      const c = configDoc.data();
      const model = deviceData.image_model || c.image_model || "default";
      $("#stat-model").textContent = model;

      // Check calendar (iCal URL based for self-hosted)
      calendarConnected = !!c.ical_url;
      $("#stat-calendar").textContent = c.ical_url
        ? "iCal URL"
        : "Not configured";

      // Display URL — fetch from backend which knows its own network IP
      try {
        const infoRes = await fetch("/api/server-info");
        if (infoRes.ok) {
          const info = await infoRes.json();
          const piUrl = info.display_url;
          if ($("#setting-pi-url")) {
            $("#setting-pi-url").value = piUrl;
          }
        }
      } catch (e) { /* non-critical */ }


      // Load chars count
      const charsSnap = await getDocs(
        collection(db, userPath("characters"))
      );
      $("#stat-chars").textContent = charsSnap.size;
    }
  } catch (e) {
    console.error(e);
  }

  // Update device switcher
  renderDeviceSwitcher();
}

// ─── Mobile Sidebar Toggle ─────────────────────────────────────

function openMobileSidebar() {
  $("#sidebar").classList.add("open");
  $("#sidebar-backdrop").classList.add("active");
  $("#mobile-menu-btn").classList.add("active");
}

function closeMobileSidebar() {
  $("#sidebar").classList.remove("open");
  $("#sidebar-backdrop").classList.remove("active");
  $("#mobile-menu-btn").classList.remove("active");
}

$("#mobile-menu-btn").addEventListener("click", () => {
  const sidebar = $("#sidebar");
  if (sidebar.classList.contains("open")) {
    closeMobileSidebar();
  } else {
    openMobileSidebar();
  }
});

$("#sidebar-backdrop").addEventListener("click", closeMobileSidebar);

// ═══════════════════════════════════════════════════════════════
// LAYOUT BUILDER — Grid Engine, Drag System, Config Panels
// ═══════════════════════════════════════════════════════════════

function buildCapabilities() {
  const caps = {};
  Object.keys(placements).forEach(wk => {
    if (wk === "weather") caps.weather = true;
    else if (wk === "calendar") caps.calendar = true;
    else if (wk === "sports") caps.sports = { enabled: true, team: widgetConfigs.sports?.team || "" };
    else if (wk === "quote") caps.daily_quote = true;
    else if (wk === "news") caps.news = true;
    else if (wk === "history") caps.this_day_in_history = true;
    else if (wk === "countdown") caps.countdown = { enabled: true, ...(widgetConfigs.countdown || {}) };
    else if (wk === "stocks") caps.stocks = { enabled: true, ...(widgetConfigs.stocks || {}) };
    else if (wk === "email") caps.email = { enabled: true, ...(widgetConfigs.email || {}) };
  });
  for (const wk of Object.keys(WIDGETS)) {
    if (wk === "weather" && !caps.weather) caps.weather = false;
    else if (wk === "calendar" && !caps.calendar) caps.calendar = false;
    else if (wk === "sports" && !caps.sports) caps.sports = false;
    else if (wk === "quote" && !caps.daily_quote) caps.daily_quote = false;
    else if (wk === "news" && !caps.news) caps.news = false;
    else if (wk === "history" && !caps.this_day_in_history) caps.this_day_in_history = false;
    else if (wk === "countdown" && !caps.countdown) caps.countdown = false;
    else if (wk === "stocks" && !caps.stocks) caps.stocks = false;
    else if (wk === "email" && !caps.email) caps.email = false;
  }
  return caps;
}

let _layoutSaveTimer = null;
function layoutAutoSave() {
  if (_layoutSaveTimer) clearTimeout(_layoutSaveTimer);
  _layoutSaveTimer = setTimeout(async () => {
    if (!currentUser) return;
    try {
      const caps = buildCapabilities();
      const saveData = {
        layout_placements: placements,
        widget_configs: widgetConfigs,
        capabilities: caps,
      };
      await setDoc(doc(db, devicePath("")), saveData, { merge: true });
      console.log("💾 Layout auto-saved");
    } catch (e) {
      console.warn("Layout auto-save failed:", e);
    }
  }, 500);
}

function pixelToGrid(px, py) {
  const gridEl = $("#canvas-grid");
  if (!gridEl) return { col: 1, row: 1 };
  const rect = gridEl.getBoundingClientRect();
  const cellW = rect.width / GRID_COLS;
  const cellH = rect.height / GRID_ROWS;
  return {
    col: Math.max(1, Math.min(GRID_COLS, Math.floor((px - rect.left) / cellW) + 1)),
    row: Math.max(1, Math.min(GRID_ROWS, Math.floor((py - rect.top) / cellH) + 1)),
  };
}

function isRectFree(col, row, cols, rows, excludeKey = null) {
  if (col < 1 || row < 1 || col + cols - 1 > GRID_COLS || row + rows - 1 > GRID_ROWS) return false;
  for (const [key, p] of Object.entries(placements)) {
    if (key === excludeKey) continue;
    if (col < p.col + p.cols && col + cols > p.col && row < p.row + p.rows && row + rows > p.row) return false;
  }
  return true;
}

function findFreePosition(cols, rows) {
  for (let r = 1; r <= GRID_ROWS - rows + 1; r++) {
    for (let c = 1; c <= GRID_COLS - cols + 1; c++) {
      if (isRectFree(c, r, cols, rows)) return { col: c, row: r };
    }
  }
  return null;
}

function isInsideCanvas(px, py) {
  const gridEl = $("#canvas-grid");
  if (!gridEl) return false;
  const rect = gridEl.getBoundingClientRect();
  return px >= rect.left && px <= rect.right && py >= rect.top && py <= rect.bottom;
}

function showDropPreview(col, row, cols, rows, valid) {
  const preview = $("#drop-preview");
  if (!preview) return;
  preview.style.gridColumn = `${col} / span ${cols}`;
  preview.style.gridRow = `${row} / span ${rows}`;
  preview.classList.add("visible");
  preview.classList.toggle("invalid", !valid);
}

function hideDropPreview() {
  const preview = $("#drop-preview");
  if (preview) preview.classList.remove("visible");
}

function layoutRenderTray() {
  const tray = $("#widget-tray");
  if (!tray) return;
  const placedKeys = new Set(Object.keys(placements));
  tray.innerHTML = Object.entries(WIDGETS)
    .filter(([key]) => !placedKeys.has(key))
    .map(([key, w]) => `
      <div class="tray-widget" data-widget="${key}" draggable="true">
        <span class="tw-icon">${w.icon}</span>
        <span class="tw-name">${w.name}</span>
      </div>
    `).join("");
  tray.querySelectorAll(".tray-widget").forEach(el => {
    setupTrayDrag(el, el.dataset.widget);
  });
}

function layoutRenderCanvas() {
  const grid = $("#canvas-grid");
  if (!grid) return;
  grid.querySelectorAll(".placed-widget").forEach(w => w.remove());
  for (const [widgetKey, p] of Object.entries(placements)) {
    if (!WIDGETS[widgetKey]) continue;
    createPlacedWidget(widgetKey, p.col, p.row, p.cols, p.rows, false);
  }
}

function hasRequiredConfig(widgetKey) {
  const cfg = widgetConfigs[widgetKey] || {};
  switch (widgetKey) {
    case "weather": return !!(cfg.latitude || cfg.location_name);
    case "sports": return !!(cfg.team);
    case "calendar": return calendarConnected || !!(_localConfig && _localConfig.ical_url);
    case "countdown": return !!(cfg.event_name && cfg.event_date);
    case "stocks": {
      const symbols = cfg.symbols || (cfg.symbol ? [cfg.symbol] : []);
      return symbols.length > 0;
    }
    case "email": return !!cfg._authorised;
    default: return true;
  }
}

function createPlacedWidget(widgetKey, col, row, cols, rows, animate = true) {
  const grid = $("#canvas-grid");
  const w = WIDGETS[widgetKey];
  if (!w || !grid) return;
  const isConfigured = !w.needsConfig || hasRequiredConfig(widgetKey);
  const badge = w.needsConfig && !isConfigured ? '<span class="pw-badge">\u26a0\ufe0f</span>' : '';
  const preview = w.preview.replace(/\n/g, "<br>");
  const el = document.createElement("div");
  el.className = `placed-widget ${animate ? '' : 'no-anim'}`;
  el.dataset.widget = widgetKey;
  el.style.gridColumn = `${col} / span ${cols}`;
  el.style.gridRow = `${row} / span ${rows}`;
  el.innerHTML = `
    <button class="pw-remove" title="Remove">\u2715</button>
    <div class="pw-resize" title="Resize"></div>
    ${badge}
    <span class="pw-icon">${w.icon}</span>
    <span class="pw-title">${w.name}</span>
    <span class="pw-preview">${preview}</span>
  `;
  grid.appendChild(el);
  el.addEventListener("click", (e) => {
    if (e.target.closest(".pw-remove") || e.target.closest(".pw-resize")) return;
    openLayoutConfig(widgetKey);
  });
  el.querySelector(".pw-remove").addEventListener("click", (e) => {
    e.stopPropagation();
    delete placements[widgetKey];
    el.remove();
    layoutRenderTray();
    layoutAutoSave();
  });
  setupMoveDrag(el, widgetKey);
  setupResizeDrag(el.querySelector(".pw-resize"), widgetKey, el);
}

function attachPointerHandlers(startEvent, onMove, onEnd) {
  if (startEvent.type === "mousedown") {
    const mousemove = (e) => { e.preventDefault(); onMove(e.clientX, e.clientY); };
    const mouseup = (e) => {
      document.removeEventListener("mousemove", mousemove);
      document.removeEventListener("mouseup", mouseup);
      onEnd(e.clientX, e.clientY);
    };
    document.addEventListener("mousemove", mousemove);
    document.addEventListener("mouseup", mouseup);
  } else {
    const touchmove = (e) => { e.preventDefault(); const t = e.touches[0]; onMove(t.clientX, t.clientY); };
    const touchend = (e) => {
      document.removeEventListener("touchmove", touchmove);
      document.removeEventListener("touchend", touchend);
      document.removeEventListener("touchcancel", touchend);
      const t = e.changedTouches?.[0];
      onEnd(t?.clientX ?? 0, t?.clientY ?? 0);
    };
    document.addEventListener("touchmove", touchmove, { passive: false });
    document.addEventListener("touchend", touchend);
    document.addEventListener("touchcancel", touchend);
  }
}

function setupTrayDrag(el, widgetKey) {
  let dragActive = false;
  const pointerDown = (x, y, e) => {
    const startX = x, startY = y;
    let ghost = null;
    const onMove = (mx, my) => {
      if (!dragActive) {
        if (Math.abs(mx - startX) > 6 || Math.abs(my - startY) > 6) {
          dragActive = true;
          el.classList.add("dragging");
          ghost = $("#drag-ghost");
          const w = WIDGETS[widgetKey];
          ghost.innerHTML = `<span class="tw-icon">${w.icon}</span><span class="tw-name">${w.name}</span>`;
          ghost.classList.remove("hidden");
        } else return;
      }
      ghost.style.left = `${mx}px`;
      ghost.style.top = `${my}px`;
      if (isInsideCanvas(mx, my)) {
        const g = pixelToGrid(mx, my);
        const sz = DEFAULT_WIDGET_SIZE;
        const c = Math.max(1, Math.min(g.col - Math.floor(sz.cols / 2), GRID_COLS - sz.cols + 1));
        const r = Math.max(1, Math.min(g.row - Math.floor(sz.rows / 2), GRID_ROWS - sz.rows + 1));
        showDropPreview(c, r, sz.cols, sz.rows, isRectFree(c, r, sz.cols, sz.rows));
      } else {
        hideDropPreview();
      }
    };
    const onEnd = (ex, ey) => {
      el.classList.remove("dragging");
      if (ghost) ghost.classList.add("hidden");
      hideDropPreview();
      if (!dragActive) return;
      dragActive = false;
      if (isInsideCanvas(ex, ey)) {
        const g = pixelToGrid(ex, ey);
        const sz = DEFAULT_WIDGET_SIZE;
        const c = Math.max(1, Math.min(g.col - Math.floor(sz.cols / 2), GRID_COLS - sz.cols + 1));
        const r = Math.max(1, Math.min(g.row - Math.floor(sz.rows / 2), GRID_ROWS - sz.rows + 1));
        if (isRectFree(c, r, sz.cols, sz.rows)) {
          placements[widgetKey] = { col: c, row: r, cols: sz.cols, rows: sz.rows };
          layoutRenderCanvas();
          layoutRenderTray();
          layoutAutoSave();
        }
      }
    };
    attachPointerHandlers(e, onMove, onEnd);
  };
  el.addEventListener("mousedown", (e) => { if (e.button === 0) { e.preventDefault(); pointerDown(e.clientX, e.clientY, e); } });
  el.addEventListener("touchstart", (e) => { const t = e.touches[0]; pointerDown(t.clientX, t.clientY, e); }, { passive: true });
}

function setupMoveDrag(el, widgetKey) {
  const pointerDown = (x, y, e) => {
    if (e.target.closest(".pw-remove") || e.target.closest(".pw-resize")) return;
    const startX = x, startY = y;
    let moved = false, ghost = null;
    const onMove = (mx, my) => {
      const p = placements[widgetKey];
      if (!p) return;
      if (!moved) {
        if (Math.abs(mx - startX) > 6 || Math.abs(my - startY) > 6) {
          moved = true;
          el.classList.add("dragging-widget");
          ghost = $("#drag-ghost");
          const w = WIDGETS[widgetKey];
          ghost.innerHTML = `<span class="tw-icon">${w.icon}</span><span class="tw-name">${w.name}</span>`;
          ghost.classList.remove("hidden");
        } else return;
      }
      ghost.style.left = `${mx}px`;
      ghost.style.top = `${my}px`;
      if (isInsideCanvas(mx, my)) {
        const g = pixelToGrid(mx, my);
        const c = Math.max(1, Math.min(g.col - Math.floor(p.cols / 2), GRID_COLS - p.cols + 1));
        const r = Math.max(1, Math.min(g.row - Math.floor(p.rows / 2), GRID_ROWS - p.rows + 1));
        showDropPreview(c, r, p.cols, p.rows, isRectFree(c, r, p.cols, p.rows, widgetKey));
      } else {
        hideDropPreview();
      }
    };
    const onEnd = (ex, ey) => {
      el.classList.remove("dragging-widget");
      if (ghost) ghost.classList.add("hidden");
      hideDropPreview();
      if (!moved) return;
      const p = placements[widgetKey];
      if (!p) { layoutRenderCanvas(); layoutRenderTray(); return; }
      if (isInsideCanvas(ex, ey)) {
        const g = pixelToGrid(ex, ey);
        const c = Math.max(1, Math.min(g.col - Math.floor(p.cols / 2), GRID_COLS - p.cols + 1));
        const r = Math.max(1, Math.min(g.row - Math.floor(p.rows / 2), GRID_ROWS - p.rows + 1));
        if (isRectFree(c, r, p.cols, p.rows, widgetKey)) {
          placements[widgetKey] = { ...p, col: c, row: r };
        }
      } else {
        delete placements[widgetKey];
      }
      layoutRenderCanvas();
      layoutRenderTray();
      layoutAutoSave();
    };
    attachPointerHandlers(e, onMove, onEnd);
  };
  el.addEventListener("mousedown", (e) => { if (e.button === 0) { e.preventDefault(); pointerDown(e.clientX, e.clientY, e); } });
  el.addEventListener("touchstart", (e) => { const t = e.touches[0]; pointerDown(t.clientX, t.clientY, e); }, { passive: true });
}

function setupResizeDrag(handle, widgetKey, widgetEl) {
  const pointerDown = (x, y, e) => {
    e.stopPropagation();
    e.preventDefault();
    const p = placements[widgetKey];
    if (!p) return;
    const startP = { ...p };
    const onMove = (mx, my) => {
      const g = pixelToGrid(mx, my);
      let newCols = Math.max(MIN_WIDGET_SIZE.cols, g.col - startP.col + 1);
      let newRows = Math.max(MIN_WIDGET_SIZE.rows, g.row - startP.row + 1);
      newCols = Math.min(newCols, GRID_COLS - startP.col + 1);
      newRows = Math.min(newRows, GRID_ROWS - startP.row + 1);
      if (isRectFree(startP.col, startP.row, newCols, newRows, widgetKey)) {
        widgetEl.style.gridColumn = `${startP.col} / span ${newCols}`;
        widgetEl.style.gridRow = `${startP.row} / span ${newRows}`;
        placements[widgetKey] = { ...startP, cols: newCols, rows: newRows };
      }
    };
    const onEnd = () => { layoutAutoSave(); };
    attachPointerHandlers(e, onMove, onEnd);
  };
  handle.addEventListener("mousedown", (e) => { pointerDown(e.clientX, e.clientY, e); });
  handle.addEventListener("touchstart", (e) => { e.stopPropagation(); const t = e.touches[0]; pointerDown(t.clientX, t.clientY, e); }, { passive: false });
}

function openLayoutConfig(widgetKey) {
  const w = WIDGETS[widgetKey];
  if (!w) return;
  const panel = $("#layout-config-panel");
  const body = $("#layout-config-panel-body");
  $("#layout-config-panel-title").textContent = `${w.icon} ${w.name}`;
  const cfg = widgetConfigs[widgetKey] || {};
  let html = "";
  switch (w.configType) {
    case "location":
      html = `<div class="form-group"><label>Location</label><div class="location-input-row"><input type="text" id="cfg-location" placeholder="e.g. Sydney" value="${cfg.location_name || ""}"><button id="cfg-geocode-btn" class="btn btn-secondary" type="button">Find</button></div><p id="cfg-location-result" class="help-text">${cfg.location_name ? "📍 " + cfg.location_name : ""}</p></div>`;
      break;
    case "sports":
      html = `<div class="form-group"><label>Your team</label><input type="text" id="cfg-sports-team" placeholder="e.g. Arsenal, Lakers" value="${cfg.team || ""}" maxlength="60"></div>`;
      break;
    case "calendar": {
      const icalSet = calendarConnected || !!(_localConfig && _localConfig.ical_url);
      html = icalSet
        ? `<p class="help-text" style="color:var(--success)">✅ Calendar connected via iCal URL</p>`
        : `<p class="help-text">⚠️ No calendar connected yet.</p>
           <p class="help-text">Add your iCal URL in <a href="#settings" class="cfg-go-settings" style="color:var(--accent);font-weight:600;cursor:pointer;">⚙️ Settings</a> to show your events on the display.</p>`;
      break;
    }
    case "countdown":
      html = `<div class="form-group"><label>Event name</label><input type="text" id="cfg-countdown-name" placeholder="e.g. Holiday" value="${cfg.event_name || ""}" maxlength="40"></div><div class="form-group"><label>Date</label><input type="date" id="cfg-countdown-date" value="${cfg.event_date || ""}"></div>`;
      break;
    case "stocks": {
      const symbols = cfg.symbols || (cfg.symbol ? [cfg.symbol] : []);
      html = `<div class="form-group"><label>Ticker symbols</label><input type="text" id="cfg-stock-symbols" placeholder="e.g. GOOG, AAPL, TSLA" value="${symbols.join(', ')}" style="text-transform:uppercase"><p class="help-text">Separate multiple tickers with commas</p></div>`;
      break;
    }
    case "email": {
      html = `<div class="form-group" id="cfg-email-status"><p class="help-text">Checking email status...</p></div>`;
      break;
    }
    default:
      html = `<p class="help-text">No configuration needed — this widget just works!</p>`;
  }
  html += `<button id="cfg-save-btn" class="btn btn-primary" style="width:100%;margin-top:16px;">Save</button>`;
  body.innerHTML = html;
  panel.classList.remove("hidden");
  wireLayoutConfigHandlers(widgetKey);
}

function wireLayoutConfigHandlers(widgetKey) {
  // Calendar "go to Settings" link
  document.querySelector(".cfg-go-settings")?.addEventListener("click", (e) => {
    e.preventDefault();
    $("#layout-config-panel").classList.add("hidden");
    document.querySelector('[data-page="settings"]').click();
  });
  $("#cfg-save-btn")?.addEventListener("click", () => {
    saveLayoutWidgetConfig(widgetKey);
    $("#layout-config-panel").classList.add("hidden");
    layoutRenderCanvas();
    layoutAutoSave();
    toast("Widget updated ✅", "success");
  });
  $("#cfg-geocode-btn")?.addEventListener("click", async () => {
    const query = $("#cfg-location").value.trim();
    if (!query) return;
    const btn = $("#cfg-geocode-btn");
    btn.disabled = true; btn.textContent = "...";
    try {
      const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=1&language=en&format=json`;
      const resp = await fetch(url);
      const data = await resp.json();
      if (data.results?.length > 0) {
        const r = data.results[0];
        widgetConfigs.weather = {
          latitude: r.latitude, longitude: r.longitude,
          location_name: [r.name, r.admin1, r.country].filter(Boolean).join(", "),
        };
        $("#cfg-location-result").textContent = `📍 ${widgetConfigs.weather.location_name}`;
        $("#cfg-location-result").style.color = "var(--success)";
      } else {
        $("#cfg-location-result").textContent = "❌ Not found";
      }
    } catch (_) {
      $("#cfg-location-result").textContent = "❌ Error";
    }
    btn.disabled = false; btn.textContent = "Find";
  });

  // Email widget: check status and show appropriate UI
  if (WIDGETS[widgetKey]?.configType === "email") {
    _loadEmailConfigPanel(widgetKey);
  }
}

async function _loadEmailConfigPanel(widgetKey) {
  const container = $("#cfg-email-status");
  if (!container) return;
  try {
    const baseUrl = _localConfig ? '' : '';
    const resp = await fetch(`${baseUrl}/api/email/status`);
    const data = await resp.json();

    if (!data.available) {
      container.innerHTML = `
        <p class="help-text" style="color:var(--warning)">⚠️ Email dependencies not installed</p>
        <p class="help-text">Run this in your <code>server/</code> directory:</p>
        <pre style="background:var(--bg-tertiary);padding:12px;border-radius:8px;font-size:13px;overflow-x:auto;">pip install -r requirements-email.txt</pre>
        <p class="help-text">Then restart the server. See <a href="https://github.com/google-gemini/glanceboard/blob/main/EMAIL_SETUP.md" target="_blank" style="color:var(--accent)">EMAIL_SETUP.md</a> for full instructions.</p>
      `;
      return;
    }

    if (!data.configured) {
      container.innerHTML = `
        <p class="help-text" style="color:var(--warning)">⚠️ Gmail credentials not found</p>
        <p class="help-text">You need to create Google OAuth credentials and save them as <code>server/data/gmail_credentials.json</code>.</p>
        <p class="help-text">See <a href="https://github.com/google-gemini/glanceboard/blob/main/EMAIL_SETUP.md" target="_blank" style="color:var(--accent)">EMAIL_SETUP.md</a> for step-by-step instructions.</p>
      `;
      return;
    }

    if (data.authorised) {
      const maxEmails = (widgetConfigs.email || {}).max_emails || 5;
      container.innerHTML = `
        <p class="help-text" style="color:var(--success)">✅ Gmail connected</p>
        <div class="form-group" style="margin-top:12px;">
          <label>Max emails to show</label>
          <input type="number" id="cfg-email-max" min="1" max="10" value="${maxEmails}" style="width:80px;">
        </div>
        <button id="cfg-email-disconnect" class="btn btn-secondary" style="margin-top:8px;width:100%;">Disconnect Gmail</button>
      `;
      widgetConfigs.email = { ...(widgetConfigs.email || {}), _authorised: true };
      $("#cfg-email-disconnect")?.addEventListener("click", async () => {
        if (!confirm("Disconnect Gmail from Glanceboard?")) return;
        await fetch("/api/email/disconnect", { method: "POST" });
        delete widgetConfigs.email?._authorised;
        _loadEmailConfigPanel(widgetKey);
        layoutRenderCanvas();
        layoutAutoSave();
        toast("Gmail disconnected", "info");
      });
    } else {
      container.innerHTML = `
        <p class="help-text">Connect your Gmail account to show an email digest on your display.</p>
        <p class="help-text" style="font-size:12px;opacity:0.7;">Only subject lines and sender names are read. See <a href="https://github.com/google-gemini/glanceboard/blob/main/EMAIL_SETUP.md" target="_blank" style="color:var(--accent)">EMAIL_SETUP.md</a> for details.</p>
        <button id="cfg-email-connect" class="btn btn-primary" style="margin-top:12px;width:100%;">Connect Gmail</button>
      `;
      $("#cfg-email-connect")?.addEventListener("click", async () => {
        try {
          const resp = await fetch("/api/email/auth-url");
          const data = await resp.json();
          if (data.auth_url) {
            window.open(data.auth_url, "_blank");
            // Poll for completion
            const poll = setInterval(async () => {
              const sr = await fetch("/api/email/status");
              const sd = await sr.json();
              if (sd.authorised) {
                clearInterval(poll);
                widgetConfigs.email = { ...(widgetConfigs.email || {}), _authorised: true };
                _loadEmailConfigPanel(widgetKey);
                layoutRenderCanvas();
                layoutAutoSave();
                toast("Gmail connected! ✅", "success");
              }
            }, 2000);
            // Stop polling after 5 minutes
            setTimeout(() => clearInterval(poll), 300000);
          }
        } catch (e) {
          toast("Failed to start Gmail auth", "error");
        }
      });
    }
  } catch (e) {
    container.innerHTML = `<p class="help-text" style="color:var(--error)">❌ Could not check email status</p>`;
  }
}

function saveLayoutWidgetConfig(widgetKey) {
  switch (widgetKey) {
    case "sports":
      widgetConfigs.sports = { team: $("#cfg-sports-team")?.value.trim() || "" };
      break;
    case "countdown":
      widgetConfigs.countdown = {
        event_name: $("#cfg-countdown-name")?.value.trim() || "",
        event_date: $("#cfg-countdown-date")?.value || "",
      };
      break;
    case "stocks": {
      const raw = ($("#cfg-stock-symbols")?.value || "").toUpperCase();
      const symbols = raw.split(/[,\s]+/).map(s => s.trim()).filter(Boolean);
      widgetConfigs.stocks = { symbols, symbol: symbols[0] || "" };
      break;
    }
    case "email": {
      const maxEmails = parseInt($("#cfg-email-max")?.value || "5", 10);
      widgetConfigs.email = { ...(widgetConfigs.email || {}), max_emails: Math.max(1, Math.min(10, maxEmails || 5)) };
      break;
    }
  }
}

$("#layout-config-panel-close")?.addEventListener("click", () => {
  $("#layout-config-panel").classList.add("hidden");
});

async function loadExistingLayout() {
  if (!currentUser) return;
  try {
    const cfg = await getDoc(doc(db, userPath("settings/config")));
    if (cfg.exists()) {
      const data = cfg.data();
      if (data.layout_placements && Object.keys(data.layout_placements).length > 0) {
        placements = data.layout_placements;
      }
      widgetConfigs = data.widget_configs || {};
      layoutRenderCanvas();
      layoutRenderTray();
      const styleName = data.aesthetic || data.custom_aesthetic || "whimsical";
      const labelEl = $("#layout-style-name");
      if (labelEl) labelEl.textContent = styleName;
    }
  } catch (e) {
    console.warn("Failed to load layout:", e);
  }
}

function initLayout() {
  if (layoutInitialized) return;
  layoutInitialized = true;
  layoutRenderTray();
  layoutRenderCanvas();
  loadExistingLayout();
}

// ─── Navigation ────────────────────────────────────────────────

$$(".nav-link").forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const page = link.dataset.page;
    showPage(page);
    if (page === "layout") initLayout();
    if (page === "characters") loadCharacters();
    if (page === "prompt") loadPromptTemplate();
    if (page === "settings") {
      loadSettings();
      renderDeviceManagement();
    }
    // Close mobile sidebar after navigation
    closeMobileSidebar();
  });
});

// ─── Generate ──────────────────────────────────────────────────

$("#generate-btn").addEventListener("click", async () => {
  const btn = $("#generate-btn");
  const progress = $("#generation-progress");
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span> Generating...';
  progress.classList.remove("hidden");

  try {
    // Show the prompt immediately so the user can see it while generating
    try {
      const previewRes = await fetch("/api/preview");
      if (previewRes.ok) {
        const previewData = await previewRes.json();
        if (previewData.prompt) {
          $("#last-prompt-card")?.classList.remove("hidden");
          $("#last-prompt-text").textContent = previewData.prompt;
        }
      }
    } catch (e) { /* non-critical */ }

    const generate = httpsCallable(functions, "generate_display");
    const result = await generate({ device_id: currentDeviceId });
    toast("Image generated!", "success");
    // Update regen count display
    if (result.data && result.data.regen_limit !== undefined) {
      if (result.data.regen_limit === -1) {
        // Unlimited (hosted/free tier — own API key)
        updateRegenUI(-1, -1);
      } else {
        const remaining = result.data.regen_limit - (result.data.regen_count || 0);
        updateRegenUI(remaining, result.data.regen_limit);
      }
    }
    loadDashboard();
  } catch (err) {
    console.error(err);
    const msg = err.message || String(err);
    if (msg.includes("regeneration") || msg.includes("RESOURCE_EXHAUSTED")) {
      toast("Daily limit reached — 3 regenerations per day. Try again tomorrow!", "error");
      updateRegenUI(0, 3);
    } else {
      toast("Generation failed: " + msg, "error");
    }
  } finally {
    btn.disabled = false;
    const regenBadge = $("#regen-badge");
    const badgeText = regenBadge ? regenBadge.textContent : "";
    btn.innerHTML = `<span class="btn-icon">🎨</span> Generate Now${badgeText ? ' <span id="regen-badge" class="regen-badge">' + badgeText + '</span>' : ''}`;
    progress.classList.add("hidden");
  }
});

function updateRegenUI(remaining, limit) {
  const btn = $("#generate-btn");
  if (!btn) return;
  const badge = btn.querySelector(".regen-badge") || document.createElement("span");
  badge.className = "regen-badge";
  badge.id = "regen-badge";
  badge.style.cssText = "font-size: 0.75em; opacity: 0.7; margin-left: 6px; font-weight: 400;";

  if (limit === -1 || remaining === -1) {
    // Self-hosted — no limits, no badge needed
    badge.textContent = "";
    badge.style.display = "none";
  } else {
    badge.textContent = `${remaining}/${limit} left`;
    if (remaining <= 0) {
      badge.style.color = "var(--red, #e74c3c)";
      badge.style.opacity = "1";
    }
  }

  if (!btn.querySelector(".regen-badge")) {
    btn.appendChild(badge);
  }
}

// ─── Characters ────────────────────────────────────────────────

async function loadCharacters() {
  const kidsGrid = $("#kids-grid");
  const extrasGrid = $("#extras-grid");
  kidsGrid.innerHTML = "";
  extrasGrid.innerHTML = "";

  const snap = await getDocs(collection(db, userPath("characters")));
  snap.forEach((d) => {
    const c = d.data();
    c.id = d.id;
    const card = document.createElement("div");
    card.className = "character-card";
    card.innerHTML = `
      ${c.imageUrl ? `<img src="${c.imageUrl}" alt="${c.name}" class="char-thumb">` : '<div class="char-thumb-placeholder">📷</div>'}
      <div class="char-info">
        <span class="char-name">${c.name}</span>
        <span class="char-desc">${c.description || ""}</span>
      </div>
    `;
    card.addEventListener("click", () => openCharacterModal(c));
    if (c.type === "kid") kidsGrid.appendChild(card);
    else extrasGrid.appendChild(card);
  });
}

function openCharacterModal(existing) {
  const modal = $("#character-modal");
  const isEdit = !!existing?.id;
  const isPerson = existing?.type === "kid" || (!existing && event?.target?.id === "add-kid-btn");

  $("#modal-title").textContent = isEdit ? "Edit Character" : (isPerson ? "Add Person" : "Add Character");
  $("#char-id").value = existing?.id || "";
  $("#char-type").value = existing?.type || (isPerson ? "kid" : "extra");
  $("#char-name").value = existing?.name || "";
  $("#char-gender").value = existing?.gender || "male";
  $("#char-age").value = existing?.age || "";
  $("#char-birthday").value = existing?.birthday || "";
  $("#char-description").value = existing?.description || "";
  // Show gender, age, birthday for people, hide for extras
  const showPersonFields = (existing?.type || (isPerson ? "kid" : "extra")) === "kid";
  $("#gender-group").style.display = showPersonFields ? "" : "none";
  $("#age-group").style.display = showPersonFields ? "" : "none";
  $("#birthday-group").style.display = showPersonFields ? "" : "none";
  $("#modal-delete").classList.toggle("hidden", !isEdit);

  // Image preview
  const preview = $("#char-image-preview");
  if (existing?.imageUrl) {
    preview.innerHTML = `<img src="${existing.imageUrl}" alt="Preview">`;
  } else {
    preview.innerHTML = '<span class="upload-icon">📷</span><span>Click or drag to upload</span>';
  }
  $("#char-image").value = "";

  modal.showModal();
}

// Image preview on select
$("#char-image").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) {
    const reader = new FileReader();
    reader.onload = (ev) => {
      $("#char-image-preview").innerHTML = `<img src="${ev.target.result}" alt="Preview">`;
    };
    reader.readAsDataURL(file);
  }
});

$("#modal-cancel").addEventListener("click", () =>
  $("#character-modal").close()
);

$("#modal-delete").addEventListener("click", async () => {
  const id = $("#char-id").value;
  if (!id) return;
  if (!confirm("Delete this character?")) return;
  await deleteDoc(doc(db, userPath(`characters/${id}`)));
  toast("Character deleted.", "info");
  $("#character-modal").close();
  loadCharacters();
});

$("#character-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#char-id").value || crypto.randomUUID();
  const charType = $("#char-type").value;
  const data = {
    name: $("#char-name").value.trim(),
    type: charType,
    gender: $("#char-gender").value,
    age: $("#char-age").value ? parseInt($("#char-age").value, 10) : null,
    birthday: $("#char-birthday").value || null,
    description: $("#char-description").value.trim(),
  };

  const file = $("#char-image").files[0];
  if (file) {
    const imgRef = storageRef(stg, `users/${currentUser.uid}/characters/${id}_photo.png`);
    await uploadBytes(imgRef, file);
    data.imageUrl = await getDownloadURL(imgRef);
  } else {
    // Preserve existing URL
    const existing = await getDoc(doc(db, userPath(`characters/${id}`)));
    if (existing.exists() && existing.data().imageUrl) {
      data.imageUrl = existing.data().imageUrl;
    }
  }

  await setDoc(doc(db, userPath(`characters/${id}`)), data);
  toast("Character saved!", "success");
  $("#character-modal").close();
  loadCharacters();
});

let pendingCharType = "kid";
$("#add-kid-btn").addEventListener("click", () => {
  pendingCharType = "kid";
  openCharacterModal({ type: "kid" });
});
$("#add-extra-btn").addEventListener("click", () => {
  pendingCharType = "extra";
  openCharacterModal({ type: "extra" });
});

// ─── Prompt ────────────────────────────────────────────────────

const DEFAULT_PROMPT_TEMPLATES = {
  whimsical: `Create a children's illustrated daily planner in pen-and-ink style on warm parchment/cream paper background with crosshatching. The output image MUST be EXACTLY 800×480 pixels — a wide landscape format (5:3 aspect ratio). The image MUST be significantly wider than it is tall.

CRITICAL FRAMING: Leave generous margins — at least 40 pixels of padding on ALL sides (top, bottom, left, right). Do NOT place any text, characters, or important elements near the edges. Everything must be well within the safe zone to avoid clipping on the e-ink display.

LAYOUT — FULL-WIDTH SCENE WITH OVERLAID TEXT:

The ENTIRE image is a single charming pen-and-ink illustration of a {{SEASON}} scene related to the day's activities. The scene fills the whole canvas.

TOP: A ribbon banner reads: '{{BANNER_TEXT}}' in bold hand-drawn block letters. Keep it well below the top edge.

LEFT SIDE (roughly 40% width) — TEXT OVERLAY:
Overlaid on top of the left portion of the scene, write a clear readable handwritten-style list of the day's schedule. The text sits in the FOREGROUND on top of the illustration, but the scene continues behind and around it — you might see trees, sky, a wall, or background details peeking around the edges. Keep the area behind the text relatively uncluttered so it stays legible.
Each event on its own line with a bullet, time, and name.
Events to show:
{{EVENT_LIST}}

RIGHT SIDE (roughly 60% width) — MAIN SCENE:
This is where the main action and characters are. The illustration flows naturally from the left side but the main focal point (characters, action) is on the right so it doesn't compete with the text.
{{CHARACTERS}}

BOTTOM LEFT CORNER — WEATHER:
{{WEATHER}}

BOTTOM RIGHT CORNER — COUNTDOWN:
{{COUNTDOWN}}

STYLE RULES: Pen-and-ink illustration, warm parchment background, hand-drawn crosshatching, charming and whimsical.
Use ONLY these colors: black ink, cream/white paper, plus limited accents of red, green, blue, and yellow.
Kid-friendly, warm, joyful. No scary elements.
The text on the left must be CLEARLY READABLE — high contrast against the background.
Remember: 800×480 pixels, wide landscape, generous margins on all sides.`,
  fashion: `Create a stylish fashion-illustration daily planner in high-end editorial sketch style. The output image MUST be EXACTLY 800×480 pixels — a wide landscape format (5:3 aspect ratio). The image MUST be significantly wider than it is tall.

CRITICAL FRAMING: Leave generous margins — at least 40 pixels of padding on ALL sides (top, bottom, left, right). Do NOT place any text, characters, or important elements near the edges.

LAYOUT — FULL-WIDTH SCENE WITH OVERLAID TEXT:

The ENTIRE image is a single elegant fashion illustration depicting a {{SEASON}} scene related to the day's activities. Think high-fashion editorial meets daily planner.

TOP: An elegant hand-lettered header reads: '{{BANNER_TEXT}}' in stylish calligraphic or modern serif letters. Keep it well below the top edge.

LEFT SIDE (roughly 40% width) — TEXT OVERLAY:
Events to show:
{{EVENT_LIST}}

RIGHT SIDE (roughly 60% width) — MAIN SCENE:
{{CHARACTERS}}

BOTTOM LEFT CORNER — WEATHER:
{{WEATHER}}

BOTTOM RIGHT CORNER — COUNTDOWN:
{{COUNTDOWN}}

STYLE RULES: Fashion illustration / editorial sketch style. Confident loose ink lines, watercolor washes.
Remember: 800×480 pixels, wide landscape, generous margins on all sides.`,
};

function getDefaultPrompt() {
  const aesthetic = document.querySelector('input[name="aesthetic"]:checked')?.value || "whimsical";
  return DEFAULT_PROMPT_TEMPLATES[aesthetic] || DEFAULT_PROMPT_TEMPLATES.whimsical;
}

async function loadPromptTemplate() {
  // Try device-level prompt first, then legacy
  let promptDoc = await getDoc(doc(db, devicePath("prompt/prompt")));
  if (!promptDoc.exists()) {
    promptDoc = await getDoc(doc(db, userPath("settings/prompt")));
  }
  if (promptDoc.exists() && promptDoc.data().template) {
    $("#prompt-template").value = promptDoc.data().template;
  } else {
    // Show the default so users can see and edit it
    $("#prompt-template").value = getDefaultPrompt();
  }
}

$("#save-prompt-btn").addEventListener("click", async () => {
  const template = $("#prompt-template").value;
  await setDoc(doc(db, devicePath("prompt/prompt")), { template });
  toast("Prompt template saved!", "success");
});

$("#reset-prompt-btn").addEventListener("click", async () => {
  if (confirm("Reset to the default prompt template?")) {
    await setDoc(doc(db, devicePath("prompt/prompt")), { template: "" });
    $("#prompt-template").value = getDefaultPrompt();
    toast("Prompt reset to default.", "info");
  }
});

$("#preview-prompt-btn").addEventListener("click", async () => {
  const btn = $("#preview-prompt-btn");
  btn.disabled = true;
  btn.textContent = "Loading...";

  try {
    const preview = httpsCallable(functions, "preview_prompt");
    const result = await preview({ device_id: currentDeviceId });
    const data = result.data;
    $("#prompt-preview").classList.remove("hidden");
    let previewText = data.prompt || "(empty)";
    if (data.weather) {
      previewText += `\n\n--- Weather Data ---\n${data.weather.emoji} ${data.weather.temp}${data.weather.unit_symbol} ${data.weather.condition}`;
    }
    $("#prompt-preview-text").textContent = previewText;
  } catch (err) {
    toast("Preview failed: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Preview Prompt";
  }
});

// ─── Settings ──────────────────────────────────────────────────

/**
 * Load dynamic model list from Firestore (system/available_models).
 * Falls back to the hardcoded <option> elements if unavailable.
 */
async function loadDynamicModels() {
  // Self-hosted: use the hardcoded options in the HTML select.
  // Don't try to fetch from Firebase system/available_models.
  return;
}

async function loadSettings() {
  // Load user-level settings (try account first, then legacy config)
  let configDoc = await getDoc(doc(db, userPath("settings/account")));
  if (!configDoc.exists()) {
    configDoc = await getDoc(doc(db, userPath("settings/config")));
  }
  if (!configDoc.exists()) return;
  const c = configDoc.data();

  // Load device-level settings
  const deviceDoc = await getDoc(doc(db, devicePath("")));
  const d = deviceDoc.exists() ? deviceDoc.data() : c; // fallback to config

  // User-level fields
  const apiKey = c.openrouter_api_key || "";
  let provider = c.api_provider || "google";
  if (!c.api_provider && apiKey.startsWith("sk-or-")) provider = "openrouter";
  $("#setting-api-provider").value = provider;
  // Update help text but skip model filtering (we do it after setting model value)
  const helpEl = $("#setting-api-help"), inputEl = $("#setting-api-key");
  if (provider === "google") {
    helpEl.innerHTML = 'Get one at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">Google AI Studio → Create API Key</a>';
    inputEl.placeholder = "AIza...";
  } else {
    helpEl.innerHTML = 'Get one at <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener">openrouter.ai/settings/keys</a>';
    inputEl.placeholder = "sk-or-v1-...";
  }
  $("#setting-api-key").value = apiKey;
  $("#setting-ical-url").value = c.ical_url || "";
  $("#setting-timezone").value = c.timezone || DEFAULT_TIMEZONE;
  $("#setting-location").value = c.location_name || "";

  // Device-level fields — load dynamic models, set value, THEN filter by provider
  await loadDynamicModels();
  $("#setting-model").value = d.image_model || c.image_model || "google/gemini-3-pro-image";
  filterModelsByProvider(provider);
  // Set text model
  $("#setting-text-model").value = d.text_model || c.text_model || "gemini-flash-latest";
  // Set aesthetic radio button
  const aestheticVal = d.aesthetic || c.aesthetic || "whimsical";
  const isBuiltIn = document.querySelector(`input[name="aesthetic"][value="${aestheticVal}"]`);
  if (isBuiltIn) {
    isBuiltIn.checked = true;
    $("#custom-aesthetic-group")?.classList.add("hidden");
  } else {
    // Custom aesthetic
    const customRadio = document.querySelector('input[name="aesthetic"][value="custom"]');
    if (customRadio) customRadio.checked = true;
    $("#custom-aesthetic-input").value = aestheticVal;
    $("#custom-aesthetic-group")?.classList.remove("hidden");
  }
  $("#setting-characters").checked = (d.characters_enabled !== undefined ? d.characters_enabled : c.characters_enabled) !== false;

  // Temp unit radio (user-level)
  const tempUnit = c.temp_unit || "celsius";
  const radio = document.querySelector(
    `input[name="setting-temp-unit"][value="${tempUnit}"]`
  );
  if (radio) radio.checked = true;

  // Show location result if already configured
  if (c.latitude && c.longitude) {
    $("#setting-location-result").textContent = `${c.location_name || "Configured"} (${c.latitude.toFixed(2)}, ${c.longitude.toFixed(2)})`;
    $("#setting-location-result").className = "help-text success";
  }

  // Calendar connection status (iCal URL for self-hosted)
  calendarConnected = !!c.ical_url;

  // Device URL — fetch from backend which knows its own network IP
  try {
    const infoRes = await fetch("/api/server-info");
    if (infoRes.ok) {
      const info = await infoRes.json();
      const piUrl = info.display_url;
      $("#setting-pi-url").value = piUrl;
      $("#setting-pi-url").dataset.defaultUrl = piUrl;
    }
  } catch (e) { /* non-critical */ }

  // Generation schedule
  const schedule = c.generation_schedule || [4, 10, 14, 18];
  renderSchedule(schedule);

  // Email Scanner settings
  const emailScan = c.email_scan || {};
  const emailEnabled = emailScan.enabled || false;
  $("#email-scan-enabled").checked = emailEnabled;
  $("#email-scan-settings").classList.toggle("hidden", !emailEnabled);
  emailScanTopics = emailScan.topics || [];
  renderEmailScanTags();
  $("#email-scan-frequency").value = emailScan.scan_frequency || 2;
  $("#email-scan-days-back").value = emailScan.days_back || 7;

  // Load scan log for status
  try {
    const scanLog = await getDoc(doc(db, userPath("settings/email_scan_log")));
    if (scanLog.exists()) {
      const log = scanLog.data();
      const statusEl = $("#email-scan-status");
      const textEl = $("#email-scan-status-text");
      statusEl.classList.remove("hidden");
      const lastScanned = log.last_scanned ? new Date(log.last_scanned).toLocaleDateString() : "never";
      textEl.textContent = `Last scan: ${lastScanned} — found ${log.events_found || 0} events, added ${log.events_added || 0} to calendar`;
    }
  } catch (e) {
    console.warn("Could not load email scan log:", e);
  }
}

// ─── Generation Schedule ────────────────────────────────────────

let currentSchedule = [4, 10, 14, 18];

function formatHour(h) {
  if (h === 0) return "12:00 AM";
  if (h === 12) return "12:00 PM";
  if (h < 12) return `${h}:00 AM`;
  return `${h - 12}:00 PM`;
}

function renderSchedule(schedule) {
  currentSchedule = [...schedule].sort((a, b) => a - b);
  const container = $("#schedule-pills");
  container.innerHTML = "";

  currentSchedule.forEach((h) => {
    const pill = document.createElement("span");
    pill.className = "schedule-pill";
    pill.innerHTML = `${formatHour(h)} <button type="button" data-hour="${h}" class="schedule-remove">&times;</button>`;
    container.appendChild(pill);
  });

  // Wire up remove buttons
  container.querySelectorAll(".schedule-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      const hour = parseInt(btn.dataset.hour);
      currentSchedule = currentSchedule.filter((h) => h !== hour);
      renderSchedule(currentSchedule);
    });
  });

  // Update the add dropdown — show only hours not already scheduled
  const select = $("#schedule-add-hour");
  select.innerHTML = '<option value="">Add a time…</option>';
  for (let h = 0; h < 24; h++) {
    if (!currentSchedule.includes(h)) {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = formatHour(h);
      select.appendChild(opt);
    }
  }

  // Update limit info
  const limitInfo = $("#schedule-limit-info");
  limitInfo.textContent = "";
  select.disabled = false;
  $("#schedule-add-btn").disabled = false;
}

$("#schedule-add-btn")?.addEventListener("click", () => {
  const select = $("#schedule-add-hour");
  const hour = select.value;
  if (hour === "") return;

  const h = parseInt(hour);

  if (!currentSchedule.includes(h)) {
    currentSchedule.push(h);
    renderSchedule(currentSchedule);
  }
});

// Settings: Geocode
$("#setting-geocode-btn")?.addEventListener("click", async () => {
  const query = $("#setting-location").value.trim();
  if (!query) return toast("Enter a city name.", "error");

  $("#setting-geocode-btn").disabled = true;
  const result = await geocodeLocation(query);
  $("#setting-geocode-btn").disabled = false;

  if (result) {
    // Store temporarily — saved when user clicks Save Settings
    onboardingData.latitude = result.latitude;
    onboardingData.longitude = result.longitude;
    onboardingData.location_name = result.name;
    const loc = [result.name, result.admin1, result.country]
      .filter(Boolean)
      .join(", ");
    $("#setting-location-result").textContent = `✅ Found: ${loc} (${result.latitude.toFixed(2)}, ${result.longitude.toFixed(2)})`;
    $("#setting-location-result").className = "help-text success";
  } else {
    $("#setting-location-result").textContent = "❌ Not found.";
    $("#setting-location-result").className = "help-text error";
  }
});



// Save Settings
// Copy Pi URL
$("#copy-pi-url")?.addEventListener("click", () => {
  const url = $("#setting-pi-url").value;
  navigator.clipboard.writeText(url).then(() => {
    toast("URL copied to clipboard!", "success");
  });
});

// Reset Pi URL to default
$("#reset-pi-url")?.addEventListener("click", () => {
  const input = $("#setting-pi-url");
  input.value = input.dataset.defaultUrl || "";
  toast("Reset to default URL.", "info");
});

let _settingsSaveTimer = null;
function settingsAutoSave() {
  if (_settingsSaveTimer) clearTimeout(_settingsSaveTimer);
  _settingsSaveTimer = setTimeout(() => doSaveSettings(), 800);
}

async function doSaveSettings() {
  // User-level settings (shared across all devices)
  const account = {
    api_provider: $("#setting-api-provider")?.value || "google",
    openrouter_api_key: $("#setting-api-key").value.trim(),
    ical_url: $("#setting-ical-url").value.trim(),
    timezone: $("#setting-timezone").value,
    generation_schedule: currentSchedule,
    setup_complete: true,
  };

  // Device-level settings (per display)
  const deviceConfig = {
    image_model: $("#setting-model").value,
    text_model: $("#setting-text-model").value,
    aesthetic: (() => {
      const sel = document.querySelector('input[name="aesthetic"]:checked')?.value || "whimsical";
      if (sel === "custom") return $("#custom-aesthetic-input")?.value?.trim() || "whimsical";
      return sel;
    })(),
    characters_enabled: $("#setting-characters").checked,
  };

  // iCal URL (user-level, saved to config)
  const icalUrl = $("#setting-ical-url")?.value?.trim();
  if (icalUrl) {
    account.ical_url = icalUrl;
  }

  // Weather location (user-level)
  const tempUnit =
    document.querySelector('input[name="setting-temp-unit"]:checked')?.value ||
    "celsius";
  account.temp_unit = tempUnit;

  if (onboardingData.latitude && onboardingData.longitude) {
    account.latitude = onboardingData.latitude;
    account.longitude = onboardingData.longitude;
    account.location_name = onboardingData.location_name;
  } else {
    // Preserve existing location
    let existing = await getDoc(doc(db, userPath("settings/account")));
    if (!existing.exists()) {
      existing = await getDoc(doc(db, userPath("settings/config")));
    }
    if (existing.exists()) {
      const d = existing.data();
      if (d.latitude) account.latitude = d.latitude;
      if (d.longitude) account.longitude = d.longitude;
      if (d.location_name) account.location_name = d.location_name;
    }
  }

  // Write user-level
  await setDoc(doc(db, userPath("settings/account")), account);
  // Write device-level (merge to preserve other fields like name, selected_characters)
  await setDoc(doc(db, devicePath("")), deviceConfig, { merge: true });
  // Also write legacy config for backwards compat during transition
  await setDoc(doc(db, userPath("settings/config")), { ...account, ...deviceConfig });

  toast("Settings saved!", "success");
}

// Manual save button
$("#save-settings-btn")?.addEventListener("click", () => doSaveSettings());

// Auto-save on settings changes
["#setting-api-provider", "#setting-model", "#setting-text-model", "#setting-timezone",
 "#setting-characters", "#email-scan-enabled"].forEach(sel => {
  $(sel)?.addEventListener("change", settingsAutoSave);
});
// Text inputs — debounce on input
["#setting-api-key", "#setting-ical-url"].forEach(sel => {
  $(sel)?.addEventListener("input", settingsAutoSave);
});
// Aesthetic radio buttons
document.querySelectorAll('input[name="aesthetic"]').forEach(r => {
  r.addEventListener("change", settingsAutoSave);
});
// Custom aesthetic text
$("#custom-aesthetic-input")?.addEventListener("input", settingsAutoSave);
// Temp unit radios
document.querySelectorAll('input[name="setting-temp-unit"]').forEach(r => {
  r.addEventListener("change", settingsAutoSave);
});

// ─── Email Scanner ─────────────────────────────────────────────

let emailScanTopics = [];

// Toggle email scan settings visibility
$("#email-scan-enabled")?.addEventListener("change", () => {
  const enabled = $("#email-scan-enabled").checked;
  $("#email-scan-settings").classList.toggle("hidden", !enabled);
});

// Tag input for topics
function renderEmailScanTags() {
  const container = $("#email-scan-tags");
  if (!container) return;
  container.innerHTML = "";
  emailScanTopics.forEach((topic, i) => {
    const tag = document.createElement("span");
    tag.className = "tag-chip";
    tag.innerHTML = `${topic} <button type="button" data-index="${i}" class="tag-remove">×</button>`;
    container.appendChild(tag);
  });
  // Bind remove buttons
  container.querySelectorAll(".tag-remove").forEach(btn => {
    btn.addEventListener("click", () => {
      emailScanTopics.splice(parseInt(btn.dataset.index), 1);
      renderEmailScanTags();
    });
  });
}

$("#email-scan-topic-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    const val = e.target.value.trim().replace(/,/g, "");
    if (val && !emailScanTopics.includes(val)) {
      emailScanTopics.push(val);
      renderEmailScanTags();
    }
    e.target.value = "";
  }
});

// Save email scan settings
$("#email-scan-save-btn")?.addEventListener("click", async () => {
  const config = {
    email_scan: {
      enabled: $("#email-scan-enabled").checked,
      topics: emailScanTopics,
      scan_frequency: parseInt($("#email-scan-frequency").value),
      days_back: parseInt($("#email-scan-days-back").value),
    },
  };

  try {
    await setDoc(doc(db, userPath("settings/config")), config, { merge: true });
    toast("Email scanner settings saved!", "success");
  } catch (e) {
    toast("Failed to save: " + e.message, "error");
  }
});

// Scan Now button
$("#email-scan-now-btn")?.addEventListener("click", async () => {
  const btn = $("#email-scan-now-btn");
  btn.disabled = true;
  btn.textContent = "⏳ Scanning...";

  try {
    const scanFn = httpsCallable(functions, "scan_emails_now");
    const result = await scanFn();
    const data = result.data;

    const statusEl = $("#email-scan-status");
    const textEl = $("#email-scan-status-text");
    statusEl.classList.remove("hidden");
    textEl.textContent = `Scan complete — found ${data.events_found} events, added ${data.events_added} to calendar`;

    if (data.events_added > 0) {
      toast(`📧 Added ${data.events_added} new event${data.events_added > 1 ? "s" : ""} to your calendar!`, "success");
    } else if (data.events_found > 0) {
      toast("All discovered events were already on your calendar.", "info");
    } else {
      toast("No new events found in your emails.", "info");
    }
  } catch (e) {
    toast("Scan failed: " + (e.message || e), "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "📧 Scan Now";
  }
});

// ─── Subscription Management ───────────────────────────────────

// ─── Subscription (self-hosted — no limits) ────────────────────
// Self-hosted version has no subscription checks or limits.

// ─── Account Management (Pause / Delete) ───────────────────────

function listenToPauseStatus() {
  if (!currentUser) return;
  const accountRef = doc(db, userPath("settings/account"));
  onSnapshot(accountRef, (snap) => {
    const paused = snap.exists() && snap.data().paused === true;
    updatePauseUI(paused);
  });
}

function updatePauseUI(paused) {
  const activeEl = $("#pause-status-active");
  const normalEl = $("#pause-status-normal");
  if (!activeEl || !normalEl) return;

  if (paused) {
    activeEl.classList.remove("hidden");
    normalEl.classList.add("hidden");
  } else {
    activeEl.classList.add("hidden");
    normalEl.classList.remove("hidden");
  }
}

// Pause account
$("#pause-account-btn")?.addEventListener("click", async () => {
  if (!confirm("Pause your account? Image generation will stop until you resume.")) return;

  const btn = $("#pause-account-btn");
  btn.disabled = true;
  btn.textContent = "Pausing...";

  try {
    await setDoc(doc(db, userPath("settings/account")), { paused: true }, { merge: true });
    toast("Account paused. Image generation is stopped.", "info");
  } catch (err) {
    console.error("Pause error:", err);
    toast("Failed to pause: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "⏸️ Pause Account";
  }
});

// Resume account
$("#resume-account-btn")?.addEventListener("click", async () => {
  const btn = $("#resume-account-btn");
  btn.disabled = true;
  btn.textContent = "Resuming...";

  try {
    await setDoc(doc(db, userPath("settings/account")), { paused: false }, { merge: true });
    toast("Account resumed! Image generation will continue on schedule.", "success");
  } catch (err) {
    console.error("Resume error:", err);
    toast("Failed to resume: " + err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Resume Account";
  }
});

// Delete account
$("#delete-account-btn")?.addEventListener("click", async () => {
  const firstConfirm = confirm(
    "Are you sure you want to permanently delete your account?\n\n" +
    "This will delete ALL your data:\n" +
    "• Settings and preferences\n" +
    "• Characters and photos\n" +
    "• Generated images\n" +
    "• Subscription (if any)\n\n" +
    "This action CANNOT be undone."
  );
  if (!firstConfirm) return;

  const secondConfirm = confirm(
    "This is your final confirmation.\n\n" +
    "Type OK to permanently delete your account and all data."
  );
  if (!secondConfirm) return;

  const btn = $("#delete-account-btn");
  btn.disabled = true;
  btn.textContent = "Deleting...";

  try {
    const deleteFn = httpsCallable(functions, "delete_account");
    await deleteFn();
    toast("Account deleted. Goodbye! 👋", "info");
    await signOut(auth);
    window.location.reload();
  } catch (err) {
    console.error("Delete account error:", err);
    toast("Failed to delete account: " + err.message, "error");
    btn.disabled = false;
    btn.textContent = "🗑️ Delete Account";
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList.contains("copy-code-btn")) {
    const code = e.target.dataset.code;
    navigator.clipboard.writeText(code).then(() => {
      const orig = e.target.textContent;
      e.target.textContent = "Copied";
      setTimeout(() => (e.target.textContent = orig), 1500);
    });
  }
});

// ─── Multi-Device Management ───────────────────────────────────

// Settings page "Add Display" button
document.getElementById("add-device-settings-btn")?.addEventListener("click", () => {
  showAddDeviceModal();
});

async function loadDevices() {
  if (!currentUser) return;
  const snap = await getDocs(collection(db, userPath("devices")));
  devices = [];
  snap.forEach((d) => {
    devices.push({ id: d.id, ...d.data() });
  });

  // If no devices exist, create a "default" entry for the switcher
  if (devices.length === 0) {
    devices = [{ id: "default", name: "Main Display" }];
  }

  // Set current device if not set
  if (!devices.find((d) => d.id === currentDeviceId)) {
    currentDeviceId = devices[0].id;
  }
}

function renderDeviceSwitcher() {
  const container = $("#device-switcher");
  if (!container) return;

  const current = devices.find((d) => d.id === currentDeviceId) || devices[0];

  if (devices.length <= 1) {
    // Single device — show simple label with add button
    container.innerHTML = `
      <div class="device-current">
        <span class="device-name">${current?.name || "Main Display"}</span>
        <button id="add-device-btn" class="btn-icon-small" title="Add display">+</button>
      </div>
    `;
  } else {
    // Multiple devices — show dropdown
    const options = devices.map((d) =>
      `<option value="${d.id}" ${d.id === currentDeviceId ? "selected" : ""}>${d.name || d.id}</option>`
    ).join("");

    container.innerHTML = `
      <div class="device-switcher-row">
        <select id="device-select" class="device-select">${options}</select>
        <button id="add-device-btn" class="btn-icon-small" title="Add display">+</button>
      </div>
    `;

    $("#device-select")?.addEventListener("change", async (e) => {
      currentDeviceId = e.target.value;
      loadDashboard();
      loadSettings();
      loadPromptTemplate();
    });
  }

  // Add device button
  $("#add-device-btn")?.addEventListener("click", () => {
    showAddDeviceModal();
  });
}

function showAddDeviceModal() {
  const modal = document.createElement("div");
  modal.className = "modal-overlay";
  modal.id = "add-device-modal";
  modal.innerHTML = `
    <div class="modal-content">
      <h3>Add a display</h3>
      <p class="help-text">Each display generates its own images and can have different settings.</p>
      <div class="form-group">
        <label for="new-device-name">Display name</label>
        <input type="text" id="new-device-name" placeholder="e.g. Kitchen, Kids Room" maxlength="30">
      </div>
      <div class="modal-actions">
        <button id="modal-cancel" class="btn secondary">Cancel</button>
        <button id="modal-add-device" class="btn primary">Add Display</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  $("#modal-cancel").addEventListener("click", () => modal.remove());
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.remove();
  });

  $("#modal-add-device").addEventListener("click", async () => {
    const name = $("#new-device-name").value.trim();
    if (!name) {
      toast("Please enter a name.", "error");
      return;
    }
    const aesthetic = _localConfig.aesthetic || "whimsical";

    $("#modal-add-device").disabled = true;
    $("#modal-add-device").textContent = "Adding...";

    try {
      const createFn = httpsCallable(functions, "create_device");
      const result = await createFn({ name, aesthetic });
      const data = result.data;

      toast(`"${name}" added!`, "success");
      modal.remove();

      // Switch to the new device
      currentDeviceId = data.device_id;
      await loadDevices();
      loadDashboard();
      loadSettings();

      if (data.billing_required) {
        toast("Additional display added. Your billing will be updated.", "info");
      }
    } catch (err) {
      toast("Failed to add display: " + err.message, "error");
      $("#modal-add-device").disabled = false;
      $("#modal-add-device").textContent = "Add Display";
    }
  });
}

// Device management in settings page
async function renderDeviceManagement() {
  const container = $("#device-management-list");
  if (!container) return;

  await loadDevices();

  container.innerHTML = devices.map((d) => `
    <div class="device-card ${d.id === currentDeviceId ? "active" : ""}">
      <div class="device-card-info">
        <span class="device-card-name">${d.name || d.id}</span>
        <span class="device-card-style">${d.aesthetic || "whimsical"}</span>
      </div>
      <div class="device-card-actions">
        ${devices.length > 1
          ? `<button class="btn-text delete-device-btn" data-id="${d.id}">Remove</button>`
          : ""}
      </div>
    </div>
  `).join("");

  // Delete handlers
  container.querySelectorAll(".delete-device-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const deviceId = btn.dataset.id;
      const device = devices.find((d) => d.id === deviceId);
      if (!confirm(`Remove "${device?.name || deviceId}"? This will delete all its images and settings.`)) return;

      btn.disabled = true;
      btn.textContent = "Removing...";

      try {
        const deleteFn = httpsCallable(functions, "delete_device");
        await deleteFn({ device_id: deviceId });

        // If we deleted the current device, switch to another
        if (currentDeviceId === deviceId) {
          currentDeviceId = devices.find((d) => d.id !== deviceId)?.id || "default";
        }

        toast("Display removed.", "info");
        await loadDevices();
        renderDeviceManagement();
        renderDeviceSwitcher();
        loadDashboard();
      } catch (err) {
        toast("Failed to remove: " + err.message, "error");
        btn.disabled = false;
        btn.textContent = "Remove";
      }
    });
  });
}
