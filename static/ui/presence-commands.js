import { elements } from "./elements-phase2.js";

/** @typedef {import("../core/alex-state.js").AlexVisualState} AlexVisualState */
/** @typedef {import("../core/domain").RoomMode} RoomMode */
/** @typedef {import("../core/domain").SystemSnapshot} SystemSnapshot */

/**
 * Owns text intent routing and the temporary wake timer. Hardware mutations remain
 * injected callbacks so this module cannot bypass the Phase 1 acknowledgment model.
 * @param {{
 *   visualState: () => AlexVisualState,
 *   canTransition: (state: AlexVisualState) => boolean,
 *   setVisualState: (state: AlexVisualState) => boolean,
 *   beginThinking: () => boolean,
 *   setAppMode: (mode: "presence" | "command") => void,
 *   refreshSnapshot: () => Promise<SystemSnapshot | null>,
 *   getSnapshot: () => SystemSnapshot | null,
 *   executeRelay: (id: number, action: "ON" | "OFF") => Promise<void>,
 *   executeTestLed: (value: boolean) => Promise<void>,
 *   executeMode: (mode: RoomMode) => Promise<void>,
 *   scheduleIdle: () => void,
 *   reducedMotion: () => boolean,
 *   view: import("./presence-view.js").createPresenceView extends (...args: never[]) => infer R ? R : never
 * }} options
 */
export function createPresenceCommands(options) {
  /** @type {number | null} */
  let wakeTimer = null;

  /** @param {number} milliseconds */
  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  /** @param {string} raw */
  async function processTextCommand(raw) {
    const normalized = raw.trim().toLocaleLowerCase("vi-VN");
    if (!normalized) return;
    elements.commandInput.value = "";

    if (normalized.includes("mở trung tâm") || normalized.includes("command center")) {
      options.setAppMode("command");
      return;
    }
    if (normalized.includes("quay lại") || normalized.includes("giao diện tối giản")) {
      options.setAppMode("presence");
      return;
    }

    const relayMatch = normalized.match(/\b(bật|tắt)\s+(?:relay\s*)?([1-4])\b/u);
    if (relayMatch) {
      await options.executeRelay(Number(relayMatch[2]), relayMatch[1] === "bật" ? "ON" : "OFF");
      return;
    }

    if (/(bật|tắt)\s+(?:đèn\s+thử|test\s*led|led\s+thử)/u.test(normalized)) {
      await options.executeTestLed(normalized.includes("bật"));
      return;
    }

    const roomModes = /** @type {const} */ (["home", "study", "sleep", "away"]);
    const matchedMode = roomModes.find((mode) => normalized.includes(`chế độ ${mode}`));
    if (matchedMode) {
      await options.executeMode(matchedMode);
      return;
    }

    if (normalized.includes("kiểm tra") || normalized.includes("trạng thái")) {
      if (options.visualState() === "offline") {
        options.view.showMicroResponse("Alex Core chưa phản hồi. Không có lệnh điều khiển nào được gửi.");
        return;
      }
      options.beginThinking();
      await delay(620);
      await options.refreshSnapshot();
      const snapshot = options.getSnapshot();
      if (snapshot) {
        if (options.visualState() === "thinking") options.setVisualState("acting");
        await delay(620);
        const mqtt = snapshot.health.mqtt === "connected" ? "MQTT đã kết nối" : "MQTT đang ngắt kết nối";
        const coreOnly = normalized.includes("alex core") || normalized.includes("core local");
        const espConnection = snapshot.v1Device?.connection ?? snapshot.device.availability;
        const verification = (snapshot.v1Device?.verification_status ?? "unknown").replaceAll("_", " ").toUpperCase();
        const nodeClaim = snapshot.v1Device?.hardware_verified ? "node hardware verified" : "node chưa hardware verified";
        const confirmed = snapshot.health.api === "online"
          && snapshot.health.mqtt === "connected"
          && (coreOnly || espConnection === "online");
        options.view.showMicroResponse(coreOnly
          ? `Alex Core online; ${mqtt}. Phép kiểm tra này không khẳng định trạng thái ESP01.`
          : `Alex Core online; ${mqtt}; ESP01 ${espConnection}; ${verification}; ${nodeClaim}.`);
        options.setVisualState(confirmed ? "success" : "warning");
      }
      options.scheduleIdle();
      return;
    }

    if (normalized.includes("xin chào") || normalized.includes("chào alex")) {
      if (!options.beginThinking()) return;
      await delay(560);
      if (options.visualState() === "thinking") options.setVisualState("speaking");
      options.view.showMicroResponse("Xin chào Việt Anh. Kênh phụ đề đang hoạt động; âm thanh sẽ được triển khai ở Phase 3.");
      await delay(1500);
      if (options.visualState() === "speaking") options.setVisualState("success");
      options.scheduleIdle();
      return;
    }

    if (options.beginThinking()) options.setVisualState("warning");
    options.view.showMicroResponse("Intent này chưa được nối trong Phase 2. ALEX không thực hiện hành động giả lập.");
    options.scheduleIdle();
  }

  function openCommandEntry() {
    options.setAppMode("presence");
    options.view.hideMicroResponse();
    options.view.hideContextPanel();
    if (wakeTimer !== null) window.clearTimeout(wakeTimer);
    if (options.visualState() === "offline") {
      options.view.showMicroResponse("Alex Core đang offline; bạn vẫn có thể mở Command Center để xem shell.");
    } else {
      if (options.visualState() !== "idle" && options.canTransition("idle")) options.setVisualState("idle");
      if (!options.setVisualState("wake")) return;
      wakeTimer = window.setTimeout(() => {
        wakeTimer = null;
        if (options.visualState() === "wake") options.setVisualState("listening");
        elements.commandInput.focus();
      }, options.reducedMotion() ? 80 : 620);
    }
    elements.commandInput.focus();
  }

  function closeCommandEntry() {
    if (wakeTimer !== null) window.clearTimeout(wakeTimer);
    wakeTimer = null;
    void options.view.stopMicrophone();
    if (options.canTransition("idle")) options.setVisualState("idle");
  }

  function destroy() {
    if (wakeTimer !== null) window.clearTimeout(wakeTimer);
    wakeTimer = null;
  }

  return Object.freeze({ processTextCommand, openCommandEntry, closeCommandEntry, destroy });
}
