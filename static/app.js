import { AlexApi } from "./core/api.js";
import { ALEX_STATE_COPY, createAlexStateMachine } from "./core/alex-state.js";
import { createDeviceCommand, transitionCommand } from "./core/command-lifecycle.js";
import { createMotionProfile, normalizeQualityMode } from "./core/quality.js";
import { createSoundEngine, DEFAULT_SOUND_SETTINGS, normalizeSoundSettings } from "./core/sound-engine.js";
import { AlexRealtime } from "./core/realtime.js";
import { elements, query } from "./ui/elements-phase2.js";
import { createPresenceCommands } from "./ui/presence-commands.js";
import { createPresenceView } from "./ui/presence-view.js";
import { WORKSPACES, renderWorkspace } from "./ui/workspaces.js";

/** @typedef {import("./core/alex-state.js").AlexVisualState} AlexVisualState */
/** @typedef {import("./core/command-lifecycle.js").DeviceCommand} DeviceCommand */
/** @typedef {import("./core/domain").SystemSnapshot} SystemSnapshot */
/** @typedef {import("./core/domain").AppMode} AppMode */
/** @typedef {import("./core/domain").RoomMode} RoomMode */
/** @typedef {import("./core/domain").V1Command} V1Command */
/** @typedef {import("./core/quality.js").QualityMode} QualityMode */

const api = new AlexApi();
/** @type {number | null} */
let realtimeRefreshTimer = null;
const realtime = new AlexRealtime({
  onEvent: (event) => {
    const data = event.data;
    if (activeCommand && data.command_id === activeCommand.id) renderCommandTrace(serverCommandToUi(/** @type {V1Command} */ (/** @type {unknown} */ (data))));
    if (realtimeRefreshTimer === null) realtimeRefreshTimer = window.setTimeout(() => {
      realtimeRefreshTimer = null;
      void refreshSnapshot();
    }, 80);
  },
});
const alexState = createAlexStateMachine();
const systemReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const presenceView = createPresenceView();
const soundEngine = createSoundEngine({ AudioContext: window.AudioContext });
const STATE_CUES = Object.freeze({ wake: "wake", listening: "listen_open", thinking: "input_accept", acting: "processing_delay", success: "action_success", warning: "warning", critical: "critical", offline: "offline" });

/** @type {AppMode} */
let appMode = "presence";
/** @type {keyof typeof WORKSPACES} */
let activeWorkspace = "overview";
/** @type {SystemSnapshot | null} */
let snapshot = null;
/** @type {DeviceCommand | null} */
let activeCommand = null;
/** @type {number | null} */
let pollTimer = null;
/** @type {number | null} */
let clockTimer = null;
/** @type {number | null} */
let idleTimer = null;
let refreshInFlight = false;
let destroyed = false;
let lastSoundState = "idle";
let userReducedMotion = localStorage.getItem("alexReducedMotion") === "true";
/** @type {QualityMode} */
let quality = normalizeQualityMode(localStorage.getItem("alexQuality"));
let soundSettings = loadSoundSettings();

function loadSoundSettings() {
  try {
    return normalizeSoundSettings(JSON.parse(localStorage.getItem("alexSoundSettings") ?? "{}"));
  } catch {
    return DEFAULT_SOUND_SETTINGS;
  }
}

const presenceCommands = createPresenceCommands({
  visualState: () => alexState.value,
  canTransition: (state) => alexState.can(state),
  setVisualState: setAlexState,
  beginThinking,
  setAppMode,
  refreshSnapshot,
  getSnapshot: () => snapshot,
  executeRelay: executeRelayCommand,
  executeTestLed: executeTestLedCommand,
  executeMode: executeModeCommand,
  scheduleIdle,
  reducedMotion: () => userReducedMotion || systemReducedMotion.matches,
  view: presenceView,
});

/** @param {AlexVisualState} next */
function setAlexState(next) {
  if (!alexState.can(next)) return false;
  alexState.transition(next);
  const copy = ALEX_STATE_COPY[next];
  document.body.dataset.alexState = next;
  elements.alexCore.dataset.state = next;
  elements.stateKicker.textContent = `ALEX CORE · ${next.toUpperCase()}`;
  elements.stateLabel.textContent = copy.label;
  elements.stateDetail.textContent = copy.detail;
  elements.assistantState.textContent = next.toUpperCase();
  presenceView.setVisualState(next);
  soundEngine.setTtsDucking(next === "speaking");
  if (next !== lastSoundState) {
    const cue = STATE_CUES[/** @type {keyof typeof STATE_CUES} */ (next)];
    if (cue) soundEngine.play(cue);
    lastSoundState = next;
  }
  return true;
}

function scheduleIdle() {
  if (idleTimer !== null) window.clearTimeout(idleTimer);
  idleTimer = window.setTimeout(() => {
    idleTimer = null;
    if (alexState.can("idle")) setAlexState("idle");
  }, 3600);
}

/** @param {string} message @param {"" | "success" | "error"} [type] */
function showToast(message, type = "") {
  elements.toast.textContent = message;
  elements.toast.className = `toast ${type}`.trim();
  elements.toast.hidden = false;
  window.setTimeout(() => { elements.toast.hidden = true; }, 3600);
}

/** @param {AppMode} mode */
function setAppMode(mode) {
  appMode = mode;
  document.body.dataset.mode = mode;
  const showPresence = mode === "presence";
  elements.presence.hidden = !showPresence;
  elements.commandCenter.hidden = showPresence;
  presenceView.setActive(showPresence && !document.hidden);
  if (!showPresence) void presenceView.stopMicrophone();
  if (showPresence) {
    elements.alexCore.focus({ preventScroll: true });
  } else {
    renderActiveWorkspace();
    const activeNav = elements.commandNav.querySelector("button.active");
    if (activeNav instanceof HTMLButtonElement) activeNav.focus({ preventScroll: true });
  }
}

/** @param {keyof typeof WORKSPACES} workspace */
function setWorkspace(workspace) {
  activeWorkspace = workspace;
  elements.commandNav.querySelectorAll("button[data-workspace]").forEach((button) => {
    button.classList.toggle("active", button instanceof HTMLButtonElement && button.dataset.workspace === workspace);
  });
  renderActiveWorkspace();
}

function renderActiveWorkspace() {
  const metadata = WORKSPACES[activeWorkspace];
  elements.workspaceEyebrow.textContent = metadata.eyebrow;
  elements.workspaceTitle.textContent = metadata.title;
  elements.workspaceDescription.textContent = metadata.description;
  renderWorkspace(elements.workspaceContent, activeWorkspace, snapshot, {
    onRelay: (id, action) => { void executeRelayCommand(id, action); },
    onTestLed: (value) => { void executeTestLedCommand(value); },
    onMode: (mode) => { void executeModeCommand(mode); },
    onOta: (version) => { void executeOtaCommand(version); },
    onSettings: openExperienceDialog,
  });
}

function updateClock() {
  const value = new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  elements.presenceClock.textContent = value;
  elements.commandClock.textContent = value;
}

/** @param {QualityMode} nextQuality @param {boolean} reduced */
function applyExperience(nextQuality, reduced) {
  quality = normalizeQualityMode(nextQuality);
  userReducedMotion = reduced;
  const effectiveReduced = systemReducedMotion.matches || userReducedMotion;
  const profile = createMotionProfile(quality, effectiveReduced);

  document.body.dataset.quality = quality;
  document.body.dataset.reducedMotion = String(effectiveReduced);
  document.documentElement.style.setProperty("--motion-scale", String(profile.animationScale));
  document.documentElement.style.setProperty("--glow-scale", String(profile.glow));
  elements.presenceQuality.value = quality;
  elements.dialogQuality.value = quality;
  elements.reduceMotion.checked = userReducedMotion;
  elements.motionStatus.textContent = effectiveReduced ? "MOTION / REDUCED" : "MOTION / ACTIVE";
  presenceView.setMotionProfile(profile);
  localStorage.setItem("alexQuality", quality);
  localStorage.setItem("alexReducedMotion", String(userReducedMotion));
}

function openExperienceDialog() {
  elements.dialogQuality.value = quality;
  elements.reduceMotion.checked = userReducedMotion;
  syncSoundControls();
  elements.experienceDialog.showModal();
}

function syncSoundControls() {
  elements.soundMode.value = soundSettings.mode;
  elements.masterVolume.value = String(Math.round(soundSettings.master * 100));
  elements.masterVolumeValue.value = `${elements.masterVolume.value}%`;
  elements.interfaceVolume.value = String(Math.round(soundSettings.interface * 100));
  elements.alertsVolume.value = String(Math.round(soundSettings.alerts * 100));
  elements.voiceVolume.value = String(Math.round(soundSettings.voice * 100));
  elements.ambienceVolume.value = String(Math.round(soundSettings.ambience * 100));
}

function applySoundSettings() {
  soundSettings = soundEngine.configure({
    mode: /** @type {"normal" | "quiet" | "night" | "silent"} */ (elements.soundMode.value),
    master: Number(elements.masterVolume.value) / 100,
    interface: Number(elements.interfaceVolume.value) / 100,
    alerts: Number(elements.alertsVolume.value) / 100,
    voice: Number(elements.voiceVolume.value) / 100,
    ambience: Number(elements.ambienceVolume.value) / 100,
  });
  localStorage.setItem("alexSoundSettings", JSON.stringify(soundSettings));
  syncSoundControls();
}

function openCommandWithAudio() {
  void soundEngine.unlock();
  presenceCommands.openCommandEntry();
}

function openAuthDialog() {
  elements.authDialog.showModal();
  window.setTimeout(() => elements.controlKey.focus(), 50);
}

/** @param {DeviceCommand} command */
function renderCommandTrace(command) {
  activeCommand = command;
  const values = elements.commandTrace.querySelectorAll("b");
  if (values[0]) values[0].textContent = `${command.deviceId} / ${command.action}`;
  if (values[1]) values[1].textContent = command.phase.toUpperCase();
  if (values[2]) values[2].textContent = command.acknowledgmentSource?.toUpperCase() ?? "—";
  elements.assistantMessage.textContent = command.failureReason ?? commandMessage(command);
  elements.assistantEvidence.textContent = `EVIDENCE / ${command.acknowledgmentSource?.toUpperCase() ?? "PENDING"}`;
}

/** @param {RoomMode} mode @param {"UPDATED" | "FAILED"} status @param {string} message */
function renderLogicalModeTrace(mode, status, message) {
  activeCommand = null;
  const values = elements.commandTrace.querySelectorAll("b");
  if (values[0]) values[0].textContent = `alex-core/room-mode / ${mode.toUpperCase()}`;
  if (values[1]) values[1].textContent = status;
  if (values[2]) values[2].textContent = "NOT APPLICABLE";
  elements.assistantMessage.textContent = message;
  elements.assistantEvidence.textContent = "EVIDENCE / API LOGICAL STATE";
}

/** @param {DeviceCommand} command */
function commandMessage(command) {
  const messages = {
    queued: "Lệnh đã vào hàng đợi cục bộ.",
    sending: "Đang gửi yêu cầu đến Alex Core.",
    waiting_ack: "API đã chấp nhận. ALEX đang chờ reported state từ ESP01.",
    accepted: "ESP01 đã ACK; đang chờ reported state.",
    waiting_reported_state: "ACK hợp lệ. ALEX đang đợi trạng thái vật lý báo về.",
    retrying: "Chưa nhận ACK; đang thử lại trong giới hạn an toàn.",
    confirmed: "ESP01 đã báo trạng thái khớp với yêu cầu.",
    failed: "Lệnh thất bại trước khi có xác nhận.",
    timed_out: "Hết thời gian chờ reported state; trạng thái được giữ là unknown.",
    cancelled: "Lệnh đã được hủy.",
    idle: "Chưa có lệnh nào được gửi.",
  };
  return messages[command.phase];
}

/** @param {V1Command} command @returns {DeviceCommand} */
function serverCommandToUi(command) {
  /** @type {DeviceCommand} */
  const converted = {
    id: String(command.command_id),
    deviceId: `${command.node_id ?? "esp01"}/${command.target ?? "test_led"}`,
    action: String(command.action ?? "set"),
    payload: /** @type {Record<string, unknown>} */ (command.desired_state ?? {}),
    phase: /** @type {import("./core/command-lifecycle.js").CommandPhase} */ (command.phase),
    requestedAt: String(command.created_at ?? new Date().toISOString()),
    updatedAt: String(command.updated_at ?? new Date().toISOString()),
  };
  if (command.acknowledged_at) converted.acknowledgedAt = String(command.acknowledged_at);
  if (command.phase === "confirmed") converted.acknowledgmentSource = `${command.source ?? "mqtt"}_reported_state`;
  else if (command.ack_status) converted.acknowledgmentSource = `${command.source ?? "mqtt"}_ack`;
  if (command.failure_reason) converted.failureReason = String(command.failure_reason);
  return converted;
}

function renderSnapshot() {
  if (!snapshot) return;
  const apiOnline = snapshot.health.api === "online";
  const mqttOnline = snapshot.health.mqtt === "connected";
  const espConnection = snapshot.v1Device?.connection ?? snapshot.device.availability;
  const espOnline = espConnection === "online";
  const roomMode = snapshot.device.mode.toUpperCase();

  elements.presenceRoomMode.textContent = roomMode;
  elements.commandRoomMode.textContent = roomMode;
  elements.sidebarRoomName.textContent = snapshot.config.room_name.toUpperCase();
  elements.presenceNodeState.textContent = espConnection.toUpperCase();
  elements.presenceMqttState.textContent = snapshot.health.mqtt.toUpperCase();
  elements.stripApi.textContent = apiOnline ? "ONLINE" : "OFFLINE";
  elements.stripMqtt.textContent = mqttOnline ? "CONNECTED" : "DISCONNECTED";
  elements.stripEsp.textContent = espOnline ? "1 / 1" : "0 / 1";
  elements.stripEvent.textContent = snapshot.events[0]?.message ?? "NO DATA";
  elements.sidebarCoreState.textContent = apiOnline ? "ONLINE" : "OFFLINE";
  elements.sidebarCoreDot.style.background = apiOnline ? "var(--alex-emerald)" : "var(--alex-critical)";
  presenceView.renderSnapshot(snapshot);

  const connectionText = apiOnline ? "CORE ONLINE" : "CORE OFFLINE";
  for (const target of [elements.presenceConnection, elements.commandConnection]) {
    target.classList.toggle("is-online", apiOnline);
    target.classList.toggle("is-offline", !apiOnline);
  }
  elements.presenceConnection.innerHTML = `<i></i> ${connectionText}`;
  elements.commandConnection.innerHTML = `<i></i> CORE / ${apiOnline ? "ONLINE" : "OFFLINE"}`;

  if (appMode === "command") renderActiveWorkspace();
}

async function refreshSnapshot() {
  if (refreshInFlight) return snapshot;
  refreshInFlight = true;
  try {
    snapshot = await api.getSnapshot();
    renderSnapshot();
    if (alexState.value === "offline") setAlexState("idle");
    return snapshot;
  } catch (error) {
    if (alexState.can("offline")) setAlexState("offline");
    elements.presenceConnection.className = "connection-label is-offline";
    elements.presenceConnection.innerHTML = "<i></i> CORE OFFLINE";
    elements.commandConnection.className = "top-connection is-offline";
    elements.commandConnection.innerHTML = "<i></i> CORE / OFFLINE";
    elements.stripApi.textContent = "OFFLINE";
    elements.sidebarCoreState.textContent = "OFFLINE";
    if (appMode === "command") renderActiveWorkspace();
    console.warn("Alex Core snapshot unavailable", error);
    return null;
  } finally {
    refreshInFlight = false;
  }
}

/** @param {number} milliseconds */
function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function prepareCommandVisualState() {
  if (!beginThinking()) return false;
  return setAlexState("acting");
}

function beginThinking() {
  if (alexState.value === "offline") return false;
  if (alexState.value === "success" || alexState.value === "warning" || alexState.value === "critical") setAlexState("idle");
  if (alexState.value === "idle" && !setAlexState("wake")) return false;
  if (alexState.value === "wake" || alexState.value === "listening") return setAlexState("thinking");
  return alexState.value === "thinking";
}

/** @param {number} relayId @param {"ON" | "OFF"} action */
async function executeRelayCommand(relayId, action) {
  if (!api.apiKey) {
    showToast("Cần xác minh API key trước khi gửi lệnh.");
    openAuthDialog();
    return;
  }
  if (!prepareCommandVisualState()) {
    showToast("Alex Core đang offline; lệnh không được gửi.", "error");
    return;
  }

  let command = createDeviceCommand({ deviceId: `esp01/relay_${relayId}`, action, payload: { relayId, action } });
  renderCommandTrace(command);
  command = transitionCommand(command, "sending");
  renderCommandTrace(command);

  try {
    await api.requestDeviceCommand(`relay_${relayId}`, action.toLowerCase(), {});
    throw new Error("SafetyPolicy không trả về kết quả từ chối như dự kiến.");
  } catch (error) {
    const detail = error instanceof Error ? error.message : "restricted_capability";
    const safetyDecision = error instanceof Error && "detail" in error && typeof error.detail === "object"
      ? /** @type {{risk_level?: string, verification_status?: string, reason?: string}} */ (error.detail)
      : null;
    const risk = safetyDecision?.risk_level?.replaceAll("_", " ").toUpperCase();
    const verification = safetyDecision?.verification_status?.replaceAll("_", " ").toUpperCase();
    const reason = safetyDecision
      ? `Relay ${relayId} bị khóa: ${risk ?? "UNKNOWN"} / ${verification ?? "UNKNOWN"} (${safetyDecision.reason ?? detail}).`
      : detail;
    command = transitionCommand(command, "failed", { failureReason: reason });
    renderCommandTrace(command);
    setAlexState("warning");
    presenceView.showMicroResponse(reason);
    showToast(reason, "error");
  }
  renderActiveWorkspace();
  scheduleIdle();
}

/** @param {boolean} value */
async function executeTestLedCommand(value) {
  if (!api.apiKey) {
    showToast("Cần xác minh API key trước khi điều khiển test_led.");
    openAuthDialog();
    return;
  }
  if (!prepareCommandVisualState()) return;
  try {
    let serverCommand = await api.setTestLed(value);
    renderCommandTrace(serverCommandToUi(serverCommand));
    const deadline = Date.now() + 12000;
    while (!['confirmed', 'failed', 'timed_out', 'cancelled'].includes(serverCommand.phase) && Date.now() < deadline) {
      await delay(180);
      serverCommand = await api.getCommand(serverCommand.command_id);
      renderCommandTrace(serverCommandToUi(serverCommand));
    }
    await refreshSnapshot();
    if (serverCommand.phase === "confirmed") {
      setAlexState("success");
      presenceView.showMicroResponse(`ESP01 đã xác nhận test LED ${value ? "bật" : "tắt"} bằng reported state.`);
      showToast(`Test LED ${value ? "ON" : "OFF"} · CONFIRMED`, "success");
    } else {
      setAlexState("warning");
      const reason = serverCommand.failure_reason ?? "Không nhận được reported state khớp.";
      presenceView.showMicroResponse(`Không thể xác nhận test LED: ${reason}`);
      showToast(String(reason), "error");
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Không thể gửi test_led command";
    setAlexState("warning");
    presenceView.showMicroResponse(`Lệnh không được xác nhận: ${reason}`);
    showToast(reason, "error");
  }
  renderActiveWorkspace();
  scheduleIdle();
}

/** @param {string} targetVersion */
async function executeOtaCommand(targetVersion) {
  if (!api.apiKey) {
    showToast("Cần xác minh API key trước khi cập nhật firmware.");
    openAuthDialog();
    return;
  }
  const confirmMsg = `ESP01 sẽ được cập nhật lên firmware ${targetVersion}. Bạn có chắc chắn muốn tiến hành?`;
  if (!window.confirm(confirmMsg)) return;

  if (!prepareCommandVisualState()) return;
  try {
    await api.requestOta("esp01", targetVersion);
    setAlexState("acting");
    presenceView.showMicroResponse(`Đã gửi yêu cầu cập nhật firmware ESP01 lên ${targetVersion}.`);
    showToast(`OTA Request ${targetVersion} sent`, "success");
    void refreshSnapshot();
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Không thể gửi lệnh OTA";
    setAlexState("warning");
    presenceView.showMicroResponse(`Lỗi cập nhật OTA: ${reason}`);
    showToast(reason, "error");
  }
  renderActiveWorkspace();
  scheduleIdle();
}

/** @param {RoomMode} mode */
async function executeModeCommand(mode) {
  if (!api.apiKey) {
    showToast("Cần xác minh API key trước khi đổi room mode.");
    openAuthDialog();
    return;
  }
  if (!prepareCommandVisualState()) return;

  try {
    const response = /** @type {{logical_mode_updated?: boolean, physical_actions?: unknown[]}} */ (await api.setRoomMode(mode));
    snapshot = await api.getSnapshot();
    renderSnapshot();
    if (snapshot.device.mode === mode && response.logical_mode_updated === true && response.physical_actions?.length === 0) {
      const message = `Room mode logic ${mode.toUpperCase()} đã cập nhật; không gửi lệnh relay.`;
      renderLogicalModeTrace(mode, "UPDATED", message);
      setAlexState("success");
      presenceView.showMicroResponse(message);
      showToast(`Room mode logic đã cập nhật: ${mode.toUpperCase()} · không gửi relay.`, "success");
    } else {
      renderLogicalModeTrace(mode, "FAILED", "Room mode logic báo về không khớp yêu cầu.");
      setAlexState("warning");
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Không thể đổi room mode";
    renderLogicalModeTrace(mode, "FAILED", reason);
    setAlexState("warning");
    showToast(reason, "error");
  }
  renderActiveWorkspace();
  scheduleIdle();
}

function bindEvents() {
  query("#presenceBrand").addEventListener("click", () => setAppMode("command"));
  query("#openCommandCenter").addEventListener("click", () => setAppMode("command"));
  query("#closeCommandCenter").addEventListener("click", () => setAppMode("presence"));
  query("#alexCore").addEventListener("click", openCommandWithAudio);
  query("#commandWake").addEventListener("click", openCommandWithAudio);
  query("#askAlexButton").addEventListener("click", openCommandWithAudio);
  query("#assistantInputButton").addEventListener("click", openCommandWithAudio);
  query("#dismissResponse").addEventListener("click", presenceView.hideMicroResponse);
  query("#dismissContext").addEventListener("click", presenceView.hideContextPanel);
  query("#cancelCommand").addEventListener("click", () => { soundEngine.play("cancel"); presenceCommands.closeCommandEntry(); });
  elements.microphoneToggle.addEventListener("click", () => { void presenceView.toggleMicrophone(); });
  query("#refreshButton").addEventListener("click", () => { void refreshSnapshot().then(() => showToast("Đã đồng bộ trạng thái mới nhất.")); });
  query("#openSettings").addEventListener("click", openExperienceDialog);
  query("#roomModeButton").addEventListener("click", () => setWorkspace("scenes"));

  elements.commandForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void presenceCommands.processTextCommand(elements.commandInput.value);
  });

  elements.commandNav.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("button[data-workspace]") : null;
    const workspace = button instanceof HTMLButtonElement ? button.dataset.workspace : undefined;
    if (workspace && Object.hasOwn(WORKSPACES, workspace)) setWorkspace(/** @type {keyof typeof WORKSPACES} */ (workspace));
  });

  elements.presenceQuality.addEventListener("change", () => applyExperience(normalizeQualityMode(elements.presenceQuality.value), userReducedMotion));
  elements.masterVolume.addEventListener("input", () => { elements.masterVolumeValue.value = `${elements.masterVolume.value}%`; });
  query("#saveExperience").addEventListener("click", () => {
    applyExperience(normalizeQualityMode(elements.dialogQuality.value), elements.reduceMotion.checked);
    applySoundSettings();
  });

  elements.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = elements.controlKey.value.trim();
    if (!key) return;
    api.setApiKey(key);
    const valid = await api.verifyKey();
    if (valid) {
      elements.authDialog.close();
      elements.controlKey.value = "";
      showToast("Đã mở quyền điều khiển. Hãy chọn lại hành động để gửi.", "success");
    } else {
      api.setApiKey("");
      showToast("API key không hợp lệ.", "error");
    }
  });
  query("#closeAuth").addEventListener("click", () => elements.authDialog.close());

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const isTyping = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement;
    if (event.ctrlKey && event.code === "Space") {
      event.preventDefault();
      setAppMode(appMode === "presence" ? "command" : "presence");
    } else if (event.ctrlKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openCommandWithAudio();
    } else if (event.code === "Space" && appMode === "presence" && !isTyping) {
      event.preventDefault();
      openCommandWithAudio();
    } else if (event.key === "Escape" && appMode === "command") {
      setAppMode("presence");
    }
  });

  systemReducedMotion.addEventListener("change", () => applyExperience(quality, userReducedMotion));
  document.addEventListener("visibilitychange", () => {
    document.body.dataset.paused = String(document.hidden);
    presenceView.setActive(!document.hidden && appMode === "presence");
    if (document.hidden) {
      realtime.visibilityChanged();
      stopPolling();
      void presenceView.stopMicrophone();
    } else {
      realtime.visibilityChanged();
      startPolling();
      void refreshSnapshot();
    }
  });
  window.addEventListener("pagehide", destroyRuntime, { once: true });
}

function startPolling() {
  if (pollTimer !== null) return;
  // Dynamic polling based on OTA state
  const otaState = snapshot?.otaInfo?.state?.status ?? "idle";
  const isOtaActive = ["requested", "downloading", "installing", "rebooting"].includes(otaState);
  const interval = isOtaActive ? 2500 : 30000;
  pollTimer = window.setInterval(() => { void refreshSnapshot(); }, interval);
}

function stopPolling() {
  if (pollTimer === null) return;
  window.clearInterval(pollTimer);
  pollTimer = null;
}

async function init() {
  applyExperience(quality, userReducedMotion);
  soundEngine.configure(soundSettings);
  syncSoundControls();
  bindEvents();
  exposeDiagnostics();
  updateClock();
  clockTimer = window.setInterval(updateClock, 1000);
  renderActiveWorkspace();
  await refreshSnapshot();
  startPolling();
  realtime.start();

  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    void navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.warn("Service worker registration failed", error);
    });
  }
}

function exposeDiagnostics() {
  /** @type {Window & {ALEX: unknown}} */ (/** @type {unknown} */ (window)).ALEX = Object.freeze({
    setAppMode,
    setWorkspace,
    setAlexState,
    processTextCommand: presenceCommands.processTextCommand,
    get mode() { return appMode; },
    get visualState() { return alexState.value; },
    get activeCommand() { return activeCommand; },
    get diagnostics() {
      return Object.freeze({
        ...presenceView.diagnostics,
        pollActive: pollTimer !== null,
        destroyed,
      });
    },
  });
}

function destroyRuntime() {
  if (destroyed) return;
  destroyed = true;
  stopPolling();
  realtime.destroy();
  if (realtimeRefreshTimer !== null) window.clearTimeout(realtimeRefreshTimer);
  realtimeRefreshTimer = null;
  if (clockTimer !== null) window.clearInterval(clockTimer);
  if (idleTimer !== null) window.clearTimeout(idleTimer);
  clockTimer = null;
  idleTimer = null;
  presenceCommands.destroy();
  presenceView.destroy();
  void soundEngine.destroy();
}

void init();
