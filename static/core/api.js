/** @typedef {import("./domain").SystemSnapshot} SystemSnapshot */
/** @typedef {import("./domain").HealthPayload} HealthPayload */
/** @typedef {import("./domain").ConfigPayload} ConfigPayload */
/** @typedef {import("./domain").DevicePayload} DevicePayload */
/** @typedef {import("./domain").SystemPayload} SystemPayload */
/** @typedef {import("./domain").EventItem} EventItem */

export class AlexApi {
  /**
   * @param {string} [baseUrl]
   */
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = sessionStorage.getItem("alexKey") ?? "";
  }

  /** @param {string} value */
  setApiKey(value) {
    this.apiKey = value;
    if (value) sessionStorage.setItem("alexKey", value);
    else sessionStorage.removeItem("alexKey");
  }

  /**
   * @param {string} path
   * @param {RequestInit} [options]
   * @param {number} [timeoutMs]
   * @returns {Promise<unknown>}
   */
  async request(path, options = {}, timeoutMs = 5000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    const headers = new Headers(options.headers);
    if (this.apiKey) headers.set("X-Alex-Key", this.apiKey);

    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        ...options,
        cache: "no-store",
        headers,
        signal: controller.signal,
      });
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        /** @type {string | {reason?: string, risk_level?: string, verification_status?: string} | null} */
        let detail = null;
        try {
          const payload = /** @type {{detail?: string | {reason?: string, risk_level?: string, verification_status?: string}}} */ (await response.json());
          detail = payload.detail ?? null;
          message = typeof payload.detail === "string" ? payload.detail : payload.detail?.reason ?? message;
        } catch {
          // The status code remains the safest available error message.
        }
        const error = new Error(message);
        Object.assign(error, { status: response.status, detail });
        throw error;
      }
      return await response.json();
    } finally {
      window.clearTimeout(timeout);
    }
  }

  /** @returns {Promise<boolean>} */
  async verifyKey() {
    try {
      await this.request("/api/auth/verify");
      return true;
    } catch {
      return false;
    }
  }

  /** @returns {Promise<SystemSnapshot>} */
  async getSnapshot() {
    const [health, config, device, system, systemHealth, eventPayload, v1Devices, v1Commands, otaPayload] = await Promise.all([
      this.request("/health"),
      this.request("/api/config"),
      this.request("/api/devices/esp01"),
      this.request("/api/system"), this.request("/api/system/health").catch(() => null),
      this.request("/api/events"),
      this.request("/api/v1/devices"),
      this.request("/api/v1/commands?limit=1"),
      this.request("/api/v1/ota/esp01").catch(() => null),
    ]);

    return {
      health: /** @type {HealthPayload} */ (health),
      config: /** @type {ConfigPayload} */ (config),
      device: /** @type {DevicePayload} */ (device),
      system: /** @type {SystemPayload} */ (system), systemHealth,
      events: /** @type {{items: EventItem[]}} */ (eventPayload).items ?? [],
      v1Device: /** @type {{items: import("./domain").V1Device[]}} */ (v1Devices).items?.find((item) => item.node_id === "esp01") ?? null,
      currentCommand: /** @type {{items: import("./domain").V1Command[]}} */ (v1Commands).items?.[0] ?? null,
      otaInfo: /** @type {import("./domain").OtaInfo | null} */ (otaPayload),
      receivedAt: new Date().toISOString(),
    };
  }

  /** @param {import("./domain").RoomMode} mode */
  async setRoomMode(mode) {
    return await this.request("/api/modes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  }

  /**
   * @param {string} target
   * @param {string} action
   * @param {Record<string, unknown>} payload
   */
  async requestDeviceCommand(target, action, payload) {
    return /** @type {Promise<import("./domain").V1Command>} */ (this.request("/api/v1/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: "esp01", target, action, payload, origin: "user" }),
    }));
  }

  /** @param {boolean} value */
  async setTestLed(value) {
    return await this.requestDeviceCommand("test_led", "set", { value });
  }

  /** @param {string} commandId */
  async getCommand(commandId) {
    return /** @type {Promise<import("./domain").V1Command>} */ (this.request(`/api/v1/commands/${encodeURIComponent(commandId)}`));
  }

  /**
   * @param {string} nodeId
   * @param {string} targetVersion
   */
  async requestOta(nodeId, targetVersion) {
    return await this.request(`/api/v1/ota/${encodeURIComponent(nodeId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: targetVersion }),
    });
  }

  /**
   * Fetch persistent audit records from SQLite.
   * @param {number|string|undefined} [limit]
   * @returns {Promise<import("./domain").AuditPayload>}
   */
  async getAudit(limit) {
    const numericLimit = Number(limit);
    const boundedLimit = Number.isFinite(numericLimit)
      ? Math.max(1, Math.min(200, Math.trunc(numericLimit)))
      : 80;
    return /** @type {Promise<import("./domain").AuditPayload>} */ (this.request(`/api/v1/audit?limit=${boundedLimit}`));
  }

  /**
   * Fetch current ALEX Brain compute node status.
   * @returns {Promise<import("./domain").BrainStatus>}
   */
  async getBrain() {
    return /** @type {Promise<import("./domain").BrainStatus>} */ (this.request("/api/v1/brain"));
  }

  /**
   * Request Wake-on-LAN packet to wake ALEX Brain.
   * @returns {Promise<import("./domain").BrainStatus>}
   */
  async wakeBrain() {
    return /** @type {Promise<import("./domain").BrainStatus>} */ (this.request("/api/v1/brain/wake", { method: "POST" }));
  }
}
