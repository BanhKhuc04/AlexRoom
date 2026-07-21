import { createAudioWaveform } from "../core/audio-waveform.js";
import { createCoreRenderer } from "../core/core-renderer.js";
import { getCoreVisualProfile } from "../core/core-visuals.js";
import { elements } from "./elements-phase2.js";

/** @typedef {import("../core/alex-state.js").AlexVisualState} AlexVisualState */
/** @typedef {import("../core/quality.js").MotionProfile} MotionProfile */
/** @typedef {import("../core/domain").SystemSnapshot} SystemSnapshot */

export function createPresenceView() {
  const waveform = createAudioWaveform();
  const renderer = createCoreRenderer(elements.coreCanvas, waveform);
  /** @type {number | null} */
  let responseTimer = null;
  /** @type {number | null} */
  let contextTimer = null;

  /** @param {AlexVisualState} state */
  function setVisualState(state) {
    elements.coreVisualMode.textContent = getCoreVisualProfile(state).label;
    elements.presenceCommand.setAttribute("aria-hidden", String(!["wake", "listening", "thinking", "acting", "speaking"].includes(state)));
    renderer.setState(state);
    updateContextForState(state);
    if (state === "idle") {
      hideMicroResponse();
      hideContextPanel();
    }
  }

  /** @param {string} message */
  function showMicroResponse(message) {
    if (responseTimer !== null) window.clearTimeout(responseTimer);
    elements.microResponseText.textContent = message;
    elements.microResponse.hidden = false;
    window.requestAnimationFrame(() => elements.microResponse.classList.add("is-visible"));
  }

  function hideMicroResponse() {
    elements.microResponse.classList.remove("is-visible");
    if (elements.microResponse.hidden) return;
    responseTimer = window.setTimeout(() => {
      elements.microResponse.hidden = true;
      responseTimer = null;
    }, 300);
  }

  function showContextPanel() {
    if (contextTimer !== null) window.clearTimeout(contextTimer);
    elements.presenceContext.hidden = false;
    window.requestAnimationFrame(() => elements.presenceContext.classList.add("is-visible"));
  }

  function hideContextPanel() {
    elements.presenceContext.classList.remove("is-visible");
    contextTimer = window.setTimeout(() => {
      if (!elements.presenceContext.classList.contains("is-visible")) elements.presenceContext.hidden = true;
      contextTimer = null;
    }, 420);
  }

  /** @param {AlexVisualState} state */
  function updateContextForState(state) {
    /** @type {Partial<Record<AlexVisualState, readonly [string, string, string, string]>>} */
    const contexts = {
      thinking: ["ALEX / INTENT", "ANALYZING", "Đang phân tích yêu cầu", "Dữ liệu đang hội tụ vào Core; chưa có kết quả được xác nhận."],
      acting: ["ALEX / ACTION", "VERIFYING", "Đang chờ bằng chứng", "Yêu cầu đã được xử lý; ALEX đang kiểm tra trạng thái trả về."],
      success: ["ALEX / EVIDENCE", "CONFIRMED", "Kết quả đã được xác nhận", "Thông tin hiển thị đến từ snapshot mới nhất của Alex Core."],
      warning: ["ALEX / EVIDENCE", "PARTIAL", "Chưa thể xác nhận đầy đủ", "Một kênh dữ liệu không phản hồi hoặc trạng thái báo về chưa khớp."],
      critical: ["ALEX / SAFETY", "SAFE STOP", "Hành động đã dừng", "ALEX giữ hệ thống ở trạng thái an toàn và không suy đoán kết quả."],
    };
    const content = contexts[state];
    if (!content) return;
    elements.contextEyebrow.textContent = content[0];
    elements.contextPhase.textContent = content[1];
    elements.contextTitle.textContent = content[2];
    elements.contextDetail.textContent = content[3];
    showContextPanel();
  }

  /** @param {SystemSnapshot} snapshot */
  function renderSnapshot(snapshot) {
    elements.contextApi.textContent = snapshot.health.api === "online" ? "ONLINE" : "OFFLINE";
    elements.contextMqtt.textContent = snapshot.health.mqtt === "connected" ? "CONNECTED" : "DISCONNECTED";
    elements.contextEsp.textContent = (snapshot.v1Device?.connection ?? snapshot.device.availability).toUpperCase();
  }

  function updateMicrophoneUi() {
    const live = waveform.mode === "microphone";
    elements.microphoneToggle.setAttribute("aria-pressed", String(live));
    elements.microphoneToggle.setAttribute("aria-label", live ? "Tắt microphone" : "Bật microphone");
    const labels = {
      synthetic: "KÊNH LOCAL",
      requesting: "MIC / REQUEST",
      microphone: "MIC / LIVE",
      denied: "MIC / DENIED",
      unavailable: "MIC / UNAVAILABLE",
    };
    elements.inputChannelState.textContent = labels[waveform.mode];
  }

  async function toggleMicrophone() {
    if (waveform.mode === "microphone") await waveform.stop();
    else await waveform.start();
    updateMicrophoneUi();
  }

  async function stopMicrophone() {
    await waveform.stop();
    updateMicrophoneUi();
  }

  /** @param {MotionProfile} profile */
  function setMotionProfile(profile) {
    renderer.setMotionProfile(profile);
  }

  /** @param {boolean} active */
  function setActive(active) {
    renderer.setActive(active);
  }

  function destroy() {
    if (responseTimer !== null) window.clearTimeout(responseTimer);
    if (contextTimer !== null) window.clearTimeout(contextTimer);
    renderer.destroy();
    void waveform.stop();
  }

  updateMicrophoneUi();

  return Object.freeze({
    setVisualState,
    showMicroResponse,
    hideMicroResponse,
    hideContextPanel,
    renderSnapshot,
    toggleMicrophone,
    stopMicrophone,
    setMotionProfile,
    setActive,
    destroy,
    get diagnostics() { return Object.freeze({ renderer: renderer.diagnostics, audio: waveform.diagnostics }); },
  });
}
