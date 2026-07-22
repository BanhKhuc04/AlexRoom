/** @typedef {import("../core/domain").SystemSnapshot} SystemSnapshot */

export const WORKSPACES = Object.freeze({
  overview: { eyebrow: "SYSTEM OVERVIEW / LIVE", title: "Không gian vận hành", description: "Trạng thái thật từ Alex Core và node ESP01." },
  devices: { eyebrow: "DEVICE FABRIC / REPORTED STATE", title: "Thiết bị", description: "Điều khiển chỉ được xác nhận sau khi ESP01 báo reported state." },
  automations: { eyebrow: "AUTOMATION ENGINE / FOUNDATION", title: "Tự động hóa", description: "Không gian dành cho rule, điều kiện an toàn và lịch sử đánh giá." },
  scenes: { eyebrow: "ROOM CONTEXT / MODES", title: "Ngữ cảnh", description: "Các mode đang có trên backend: Home, Study, Sleep và Away." },
  missions: { eyebrow: "MISSION CONTROL / FOUNDATION", title: "Nhiệm vụ", description: "Theo dõi tiến độ nhiều bước với kết quả partial và failed rõ ràng." },
  security: { eyebrow: "ALEX GUARD / FOUNDATION", title: "An ninh", description: "Shell sẵn sàng; chưa kết nối cảm biến cửa hoặc camera thật." },
  cameras: { eyebrow: "VISION CHANNEL / FOUNDATION", title: "Camera", description: "Không có camera stream nào được cấu hình trong backend hiện tại." },
  energy: { eyebrow: "ENERGY INTELLIGENCE / FOUNDATION", title: "Năng lượng", description: "Chưa có meter thật; không hiển thị số liệu demo như dữ liệu đo." },
  brain: { eyebrow: "COMPUTE NODE / FOUNDATION", title: "ALEX Brain", description: "Wake-on-LAN và telemetry PC chưa có trong backend gốc." },
  logs: { eyebrow: "AUDIT CHANNEL / LIVE", title: "Nhật ký", description: "Sự kiện gần nhất do Alex Core cung cấp trong memory." },
  system: { eyebrow: "ALEX CORE / LIVE METRICS", title: "Hệ thống", description: "Tài nguyên thật từ host đang chạy FastAPI." },
  settings: { eyebrow: "SYSTEM PREFERENCES / LOCAL", title: "Cài đặt", description: "Cấu hình chất lượng và chuyển động được lưu trên trình duyệt này." },
});

export const ROOM_LAYOUT = Object.freeze({
  zones: ["ngủ", "làm việc", "cây xanh", "lối vào"],
  fixtures: [
    { id: "bed", label: "Giường", x: 18, y: 23, kind: "furniture" },
    { id: "desk", label: "Bàn + PC", x: 70, y: 24, kind: "compute" },
    { id: "orange-pi", label: "Orange Pi", x: 62, y: 48, kind: "core" },
    { id: "esp01", label: "ESP01", x: 77, y: 55, kind: "node" },
    { id: "test-led", label: "Test LED", x: 83, y: 45, kind: "light" },
    { id: "plants", label: "2 chậu cây", x: 25, y: 72, kind: "plant" },
    { id: "door", label: "Cửa", x: 86, y: 82, kind: "entry" },
  ],
});

/** @param {unknown} value */
export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

/** @param {number} seconds */
function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days > 0 ? `${days} ngày ${hours} giờ` : `${hours} giờ`;
}

/** @param {string | null} timestamp */
function formatTime(timestamp) {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

/** @param {import("../core/domain").VerificationStatus | undefined} status */
function formatVerification(status) {
  const labels = {
    unknown: "UNKNOWN",
    simulated: "SIMULATED",
    software_verified: "SOFTWARE VERIFIED",
    basic_physical_validated: "BASIC PHYSICAL VALIDATION",
    hardware_verified: "HARDWARE VERIFIED",
    restricted: "RESTRICTED",
  };
  return status ? labels[status] ?? "UNKNOWN" : "UNKNOWN";
}

/** @param {SystemSnapshot | null} snapshot */
function renderOverview(snapshot) {
  const apiOnline = snapshot?.health.api === "online";
  const mqttOnline = snapshot?.health.mqtt === "connected";
  const deviceOnline = snapshot?.v1Device?.connection === "online";
  const ledOn = snapshot?.v1Device?.reported_state.test_led?.on === true;
  const nodeVerification = formatVerification(snapshot?.v1Device?.verification_status);
  const ledVerification = formatVerification(snapshot?.v1Device?.capabilities.test_led?.verification_status);
  const events = snapshot?.events.slice(0, 4) ?? [];

  return `
    <div class="overview-grid">
      <article class="system-map spatial-home">
        <div class="panel-caption"><span>SPATIAL HOME / ONE ROOM</span><span>${apiOnline ? "LIVE CORE" : "NO SIGNAL"}</span></div>
        <div class="room-stage" aria-label="Bản đồ cấu hình một phòng">
          <div class="room-zone zone-sleep">NGỦ</div><div class="room-zone zone-work">LÀM VIỆC</div><div class="room-zone zone-green">CÂY XANH</div><div class="room-zone zone-entry">LỐI VÀO</div>
          ${ROOM_LAYOUT.fixtures.map((item) => `<button class="room-fixture ${item.kind} ${item.id === "esp01" && !deviceOnline ? "offline" : ""} ${item.id === "test-led" && ledOn ? "is-lit" : ""}" style="--x:${item.x}%;--y:${item.y}%" type="button" aria-label="${escapeHtml(item.label)}"><i></i><span>${escapeHtml(item.label)}</span>${item.id === "orange-pi" ? `<b>${apiOnline ? "ONLINE" : "OFFLINE"}</b>` : item.id === "esp01" ? `<b>${escapeHtml(snapshot?.v1Device?.connection ?? "UNKNOWN")}</b>` : item.id === "test-led" ? `<b>${ledOn ? "ON" : "OFF"}</b>` : ""}</button>`).join("")}
          <div class="map-readout"><span>MQTT / ${mqttOnline ? "CONNECTED" : "DISCONNECTED"}</span><span>ESP01 VERIFY / ${nodeVerification}</span><span>ESP01 LAST SEEN / ${formatTime(snapshot?.v1Device?.last_seen_at ?? null)}</span><span>LAYOUT / REPORTED STATE ONLY</span></div>
        </div>
      </article>
      <div class="status-stack">
        <article><span>ALEX CORE</span><strong>${apiOnline ? "Operational" : "No signal"}</strong><p>FastAPI · local-first control plane</p><i style="color:${apiOnline ? "var(--alex-emerald)" : "var(--alex-critical)"}"></i></article>
        <article><span>ESP01 NODE</span><strong>${escapeHtml(snapshot?.v1Device?.connection ?? "Unknown")}</strong><p>${nodeVerification} · test_led ${ledVerification}</p><i style="color:${deviceOnline ? "var(--alex-emerald)" : "var(--alex-amber)"}"></i></article>
      </div>
      <article class="workspace-panel event-summary">
        <h3>RECENT SYSTEM EVENTS</h3>
        <ol>${events.length ? events.map((item) => `<li><time>${formatTime(item.time)}</time><span>${escapeHtml(item.message)}</span></li>`).join("") : "<li><time>—</time><span>Chưa có sự kiện.</span></li>"}</ol>
      </article>
    </div>`;
}

/**
 * @param {SystemSnapshot | null} snapshot
 */
function renderDevices(snapshot) {
  const twin = snapshot?.v1Device;
  const command = snapshot?.currentCommand;
  const online = twin?.connection === "online";
  const reportedOn = twin?.reported_state.test_led?.on === true;
  const desiredOn = twin?.desired_state?.test_led?.on;
  const ledCapability = twin?.capabilities.test_led;
  const relayNames = snapshot?.config.relay_names ?? {};
  const subtitles = snapshot?.config.relay_subtitles ?? {};
  const relays = snapshot?.device.relays ?? {};
  const cards = [1, 2, 3, 4].map((id) => {
    const key = String(id);
    const state = (relays[key] ?? "UNKNOWN").toUpperCase();
    const capability = twin?.capabilities[`relay_${id}`];
    const restricted = capability?.command_allowed !== true;
    const riskLabel = capability?.risk_level?.toUpperCase() ?? "UNKNOWN";
    const verificationLabel = formatVerification(capability?.verification_status);
    return `<article class="relay-card" data-relay-card="${id}">
      <header><div><span>ESP01 / RELAY 0${id}</span><h3>${escapeHtml(relayNames[key] ?? `Relay ${id}`)}</h3><p>${escapeHtml(subtitles[key] ?? "GPIO chưa khai báo")}</p></div><b class="relay-state ${state === "ON" ? "on" : ""}">${escapeHtml(state)}</b></header>
      <div class="relay-actions"><button type="button" ${restricted ? "disabled" : ""}>${escapeHtml(riskLabel)}</button><button type="button" ${restricted ? "disabled" : ""}>${escapeHtml(verificationLabel)}</button></div>
    </article>`;
  });

  const devicesPanel = `<article class="workspace-panel"><h2>ESP01 · Digital twin</h2><p>Chỉ <b>test_led</b> điện áp thấp được mở. Thành công chỉ xuất hiện sau ACK và reported state khớp.</p>
    <div class="device-twin-grid">
      <article class="relay-card test-led-card"><header><div><span>SAFE TARGET / ${escapeHtml(twin?.source ?? "NO SOURCE")}</span><h3>Test LED</h3><p>${formatVerification(ledCapability?.verification_status)} · ${ledCapability?.command_allowed ? "AVAILABLE" : "UNAVAILABLE"}</p></div><b class="relay-state ${reportedOn ? "on" : ""}">${reportedOn ? "ON" : "OFF"}</b></header>
      <dl class="integration-list"><div><dt>CONNECTION</dt><dd>${escapeHtml(twin?.connection ?? "UNKNOWN")}</dd></div><div><dt>VERIFICATION</dt><dd>${formatVerification(ledCapability?.verification_status)}</dd></div><div><dt>COMMAND</dt><dd>${ledCapability?.command_allowed ? "AVAILABLE" : "LOCKED"}</dd></div><div><dt>DESIRED</dt><dd>${desiredOn == null ? "—" : desiredOn ? "ON" : "OFF"}</dd></div><div><dt>REPORTED</dt><dd>${reportedOn ? "ON" : "OFF"}</dd></div><div><dt>FIRMWARE</dt><dd>${escapeHtml(twin?.firmware ?? "—")}</dd></div><div><dt>RSSI</dt><dd>${twin?.rssi == null ? "—" : `${twin.rssi} dBm`}</dd></div><div><dt>LAST SEEN</dt><dd>${formatTime(twin?.last_seen_at ?? null)}</dd></div><div><dt>PHASE</dt><dd>${escapeHtml(command?.phase ?? "IDLE")}</dd></div><div><dt>RETRY</dt><dd>${command?.retry_count ?? 0}</dd></div></dl>
      <div class="relay-actions"><button type="button" data-test-led="true" ${online && ledCapability?.command_allowed ? "" : "disabled"}>BẬT LED</button><button type="button" data-test-led="false" ${online && ledCapability?.command_allowed ? "" : "disabled"}>TẮT LED</button></div></article>
    </div><div class="phase-notice"><b>SAFETY</b><span>Bốn relay cũ bị khóa vì chưa có mapping tải và interlock đã xác minh. Không nối 220V, UV, khóa cửa, motor hoặc pump.</span></div><div class="relay-grid legacy-relays">${cards.join("")}</div></article>`;
  
  const ota = snapshot?.otaInfo;
  const otaState = ota?.state?.status ?? "idle";
  const otaTarget = ota?.state?.target_version ?? "none";
  const updateAvailable = ota?.update_available ? "Yes" : "No";
  const availableVer = ota?.available_version ?? "—";
  const releaseInfo = availableVer && ota?.releases?.[availableVer] 
    ? `${(ota.releases[availableVer].size / 1024).toFixed(1)} KB · SHA256: ${ota.releases[availableVer].sha256.substring(0, 8)}...`
    : "—";
  
  const isOtaActive = ["requested", "downloading", "installing", "rebooting"].includes(otaState);
  const canUpdate = online && ota?.update_available && !isOtaActive;

  const otaPanel = `<article class="workspace-panel"><h2>ESP01 · Firmware / OTA</h2><p>Quản lý firmware từ xa. Yêu cầu thiết bị online và không có lệnh đang thực thi.</p>
    <div class="device-twin-grid">
      <article class="relay-card test-led-card"><header><div><span>OTA TARGET / ${escapeHtml(otaTarget)}</span><h3>Cập nhật Firmware</h3><p>${isOtaActive ? "IN PROGRESS" : (ota?.update_available ? "UPDATE AVAILABLE" : "UP TO DATE")}</p></div><b class="relay-state ${isOtaActive ? "on" : ""}">${escapeHtml(otaState.toUpperCase())}</b></header>
      <dl class="integration-list"><div><dt>INSTALLED</dt><dd>${escapeHtml(ota?.installed_version ?? "—")}</dd></div><div><dt>AVAILABLE</dt><dd>${escapeHtml(availableVer)}</dd></div><div><dt>UPDATE AVAILABLE</dt><dd>${updateAvailable}</dd></div><div><dt>FIRMWARE INFO</dt><dd>${escapeHtml(releaseInfo)}</dd></div><div><dt>OTA STATE</dt><dd>${escapeHtml(otaState.toUpperCase())}</dd></div></dl>
      <div class="relay-actions"><button type="button" data-ota-target="${escapeHtml(availableVer)}" ${canUpdate ? "" : "disabled"}>CẬP NHẬT FIRMWARE</button></div></article>
    </div></article>`;

  return devicesPanel + otaPanel;
}

/** @param {SystemSnapshot | null} snapshot */
function renderLogs(snapshot) {
  const items = snapshot?.events ?? [];
  return `<article class="workspace-panel"><h2>Event channel</h2><p>Event deque hiện tại giữ tối đa 80 mục trong memory và mất sau restart.</p><div class="event-summary"><ol>${items.length ? items.map((item) => `<li><time>${formatTime(item.time)}</time><span>${escapeHtml(item.kind.toUpperCase())} · ${escapeHtml(item.message)}</span></li>`).join("") : "<li><time>—</time><span>Chưa có sự kiện từ backend.</span></li>"}</ol></div></article>`;
}

/** @param {SystemSnapshot | null} snapshot */
function renderSystem(snapshot) {
  const system = snapshot?.system ?? null;
  const envelope = snapshot?.systemHealth ?? null;
  const report = envelope?.report ?? null;
  const checks = report?.checks ?? {};

  const database = checks.database ?? {};
  const disk = checks.disk ?? {};
  const memory = checks.memory ?? {};
  const thermal = checks.cpu_temperature ?? {};
  const load = checks.load_average ?? {};
  const backup = checks.backup ?? {};
  const core = checks.core_service ?? {};
  const runtime = checks.core_runtime ?? {};
  const updateTimer = checks.update_timer ?? {};
  const update = checks.update ?? {};
  const hardware = checks.hardware_runtime ?? {};

  const statusText = (value) =>
    String(value ?? "unknown").toUpperCase();

  const overall = statusText(
    envelope?.status
    ?? report?.status
    ?? "unknown"
  );

  const monitorState =
    envelope?.available !== true
      ? "NO REPORT"
      : envelope?.stale
        ? "STALE"
        : "LIVE";

  const mqtt = statusText(
    hardware.mqtt
    ?? snapshot?.health?.mqtt
    ?? "unknown"
  );

  const esp01 = statusText(
    hardware.device
    ?? snapshot?.v1Device?.connection
    ?? "unknown"
  );

  const ramPercent =
    memory.used_percent
    ?? system?.memory?.percent
    ?? null;

  const cpuTemp =
    thermal.celsius
    ?? system?.temperature_c
    ?? null;

  const diskFree =
    disk.free_percent
    ?? (
      system?.disk?.percent == null
        ? null
        : 100 - system.disk.percent
    );

  const uptime =
    report?.uptime_seconds
    ?? system?.uptime_seconds
    ?? null;

  return `
<div class="workspace-status-strip">
  <span>SYSTEM HEALTH</span>
  <strong>${escapeHtml(overall)}</strong>
  <span>${escapeHtml(monitorState)}</span>
</div>

<div class="metric-grid">

  <article class="metric-card">
    <span>CORE</span>
    <h3>${escapeHtml(statusText(core.status))}</h3>
    <p>
      PID ${runtime.main_pid ?? "?"} ?
      Restarts ${runtime.restart_count ?? "?"}
    </p>
  </article>

  <article class="metric-card">
    <span>DATABASE</span>
    <h3>${escapeHtml(statusText(database.status))}</h3>
    <p>
      ${
        database.size_bytes == null
          ? "Size ?"
          : `${Math.round(database.size_bytes / 1024)} KB`
      }
    </p>
  </article>

  <article class="metric-card">
    <span>MQTT</span>
    <h3>${escapeHtml(mqtt)}</h3>
    <p>${escapeHtml(hardware.message ?? "Runtime")}</p>
  </article>

  <article class="metric-card">
    <span>ESP01</span>
    <h3>${escapeHtml(esp01)}</h3>
    <p>
      Heartbeat ${
        hardware.heartbeat_age_seconds == null
          ? "?"
          : `${hardware.heartbeat_age_seconds}s`
      }
    </p>
  </article>

  <article class="metric-card">
    <span>BACKUP</span>
    <h3>${escapeHtml(statusText(backup.status))}</h3>
    <p>
      ${backup.backup_count ?? 0} b?n ?
      ${
        backup.age_hours == null
          ? "age ?"
          : `${backup.age_hours}h`
      }
    </p>
  </article>

  <article class="metric-card">
    <span>OTA</span>
    <h3>${escapeHtml(statusText(update.status))}</h3>
    <p>
      Timer ${escapeHtml(statusText(updateTimer.status))}
    </p>
  </article>

</div>

<div class="metric-grid">

  <article class="metric-card">
    <span>RAM</span>
    <h3>${
      ramPercent == null
        ? "?"
        : `${ramPercent}%`
    }</h3>
    <p>System memory</p>
  </article>

  <article class="metric-card">
    <span>CPU TEMP</span>
    <h3>${
      cpuTemp == null
        ? "?"
        : `${cpuTemp}?C`
    }</h3>
    <p>CPU thermal zone</p>
  </article>

  <article class="metric-card">
    <span>DISK FREE</span>
    <h3>${
      diskFree == null
        ? "?"
        : `${diskFree}%`
    }</h3>
    <p>${escapeHtml(statusText(disk.status))}</p>
  </article>

  <article class="metric-card">
    <span>LOAD 1 / 5 / 15</span>
    <h3>${
      load.load_1m == null
        ? "?"
        : `${load.load_1m} / ${load.load_5m} / ${load.load_15m}`
    }</h3>
    <p>${load.cpu_count ?? "?"} CPU</p>
  </article>

  <article class="metric-card">
    <span>UPTIME</span>
    <h3>${
      uptime == null
        ? "?"
        : formatUptime(uptime)
    }</h3>
    <p>
      ${
        report?.boot_time
          ? escapeHtml(report.boot_time)
          : "Boot time ?"
      }
    </p>
  </article>

  <article class="metric-card">
    <span>ALEX VERSION</span>
    <h3>${escapeHtml(report?.alex_version ?? "?")}</h3>
    <p>
      Health schema ${report?.schema_version ?? "?"}
    </p>
  </article>

</div>

<div class="system-health-footer">
  <span>
    REPORT AGE /
    ${
      envelope?.file_age_seconds == null
        ? "?"
        : `${envelope.file_age_seconds}s`
    }
  </span>

  <span>
    TAILSCALE /
    ${escapeHtml(system?.tailscale_ip ?? "?")}
  </span>
</div>
`;
}

/** @param {string} workspace */
function renderFoundation(workspace) {
  const details = {
    automations: ["Automation rules", "0 rule", "Chưa có rule được lưu. Trigger, condition và action sẽ chỉ chạy qua simulator hoặc backend có audit.", "TẠO RULE"],
    missions: ["Mission queue", "0 mission", "Chưa có nhiệm vụ nhiều bước. Không có bước nào được đánh dấu hoàn thành giả.", "TẠO NHIỆM VỤ"],
    security: ["ALEX Guard", "UNKNOWN", "Chưa có cảm biến cửa/camera thật; vì vậy hệ thống không thể tuyên bố phòng đang an toàn.", "KIỂM TRA HỆ THỐNG"],
    cameras: ["Vision channels", "0 source", "Chưa cấu hình camera, RTSP/WebRTC hoặc chính sách riêng tư.", "THÊM CẤU HÌNH"],
    energy: ["Energy telemetry", "NO METER", "Không có meter/endpoint điện năng; biểu đồ giả và số kWh mẫu bị cấm.", "KẾT NỐI METER"],
    brain: ["ALEX Brain", "NOT CONNECTED", "Chưa có heartbeat hoặc Wake-on-LAN endpoint cho PC i5-4590.", "CẤU HÌNH WOL"],
  }[workspace] ?? ["Workspace", "EMPTY", "Không có dữ liệu cho workspace này.", "CHƯA KHẢ DỤNG"];

  return `<div class="overview-grid feature-empty"><article class="workspace-panel"><span class="panel-caption-inline">${details[1]}</span><h2>${details[0]}</h2><p>${details[2]}</p><div class="phase-notice"><b>HONEST STATE</b><span>UI chỉ hiển thị dữ liệu có nguồn. Tính năng cần backend/hardware được khóa thay vì báo thành công mô phỏng.</span></div><button class="secondary-action" type="button" disabled>${details[3]}</button></article><article class="workspace-panel"><h2>Trạng thái tích hợp</h2><dl class="integration-list"><div><dt>LOCAL UI</dt><dd>READY</dd></div><div><dt>BACKEND CONTRACT</dt><dd>PENDING</dd></div><div><dt>HARDWARE</dt><dd>NOT VERIFIED</dd></div></dl></article></div>`;
}

/** @param {SystemSnapshot | null} snapshot */
function renderScenes(snapshot) {
  const current = snapshot?.device.mode ?? "home";
  const modes = ["home", "study", "sleep", "away", "relax", "energy saving"];
  return `<article class="workspace-panel"><h2>Room modes</h2><p>Mode hiện tại: <b>${escapeHtml(current.toUpperCase())}</b>. Home, Study, Sleep và Away chỉ cập nhật ngữ cảnh logic; không mode nào được phép gửi lệnh đến bốn relay chưa xác minh.</p><div class="relay-grid">${modes.map((mode) => { const supported = ["home", "study", "sleep", "away"].includes(mode); return `<article class="relay-card"><header><div><span>${supported ? "LOGICAL ROOM MODE" : "SCENE DRAFT"}</span><h3>${mode.toUpperCase()}</h3><p>${mode === current ? "Đang hoạt động · không relay" : supported ? "Không thực thi relay" : "Chưa có backend steps"}</p></div><b class="relay-state ${mode === current ? "on" : ""}">${mode === current ? "ACTIVE" : supported ? "LOGIC ONLY" : "LOCKED"}</b></header><div class="relay-actions"><button type="button" ${supported ? `data-room-mode="${mode}"` : "disabled"}>${supported ? "KÍCH HOẠT" : "CHƯA KHẢ DỤNG"}</button></div></article>`; }).join("")}</div></article>`;
}

/**
 * @param {HTMLElement} container
 * @param {string} workspace
 * @param {SystemSnapshot | null} snapshot
 * @param {{onRelay: (id: number, action: "ON" | "OFF") => void, onTestLed: (value: boolean) => void, onMode: (mode: import("../core/domain").RoomMode) => void, onSettings: () => void, onOta?: (version: string) => void}} actions
 */
export function renderWorkspace(container, workspace, snapshot, actions) {
  if (workspace === "overview") container.innerHTML = renderOverview(snapshot);
  else if (workspace === "devices") container.innerHTML = renderDevices(snapshot);
  else if (workspace === "logs") container.innerHTML = renderLogs(snapshot);
  else if (workspace === "system") container.innerHTML = renderSystem(snapshot);
  else if (workspace === "scenes") container.innerHTML = renderScenes(snapshot);
  else if (workspace === "settings") container.innerHTML = `<article class="workspace-panel"><h2>Experience settings</h2><p>Điều chỉnh performance/balanced/cinematic, reduced motion và sound modes/gain groups.</p><button class="primary-action" type="button" data-open-experience>MỞ CÀI ĐẶT</button></article>`;
  else container.innerHTML = renderFoundation(workspace);

  container.querySelectorAll("[data-relay-action]").forEach((element) => {
    if (!(element instanceof HTMLButtonElement)) return;
    element.addEventListener("click", () => {
      const relayId = Number(element.dataset.relayId);
      const action = element.dataset.relayAction;
      if ((action === "ON" || action === "OFF") && Number.isInteger(relayId)) actions.onRelay(relayId, action);
    });
  });
  container.querySelectorAll("[data-test-led]").forEach((element) => {
    if (!(element instanceof HTMLButtonElement)) return;
    element.addEventListener("click", () => actions.onTestLed(element.dataset.testLed === "true"));
  });
  container.querySelectorAll("[data-room-mode]").forEach((element) => {
    if (!(element instanceof HTMLButtonElement)) return;
    element.addEventListener("click", () => {
      const mode = element.dataset.roomMode;
      if (mode === "home" || mode === "study" || mode === "sleep" || mode === "away") actions.onMode(mode);
    });
  });
  container.querySelectorAll("[data-ota-target]").forEach((element) => {
    if (!(element instanceof HTMLButtonElement)) return;
    element.addEventListener("click", () => {
      if (actions.onOta) actions.onOta(element.dataset.otaTarget ?? "");
    });
  });
  container.querySelector("[data-open-experience]")?.addEventListener("click", actions.onSettings);
}
