/**
 * Orchestrates workspace-specific asynchronous data (Audit, Brain, Automations).
 */

/**
 * Stable UUID helper - uses crypto.randomUUID when available,
 * falls back to a non-cryptographic unique string otherwise.
 * @returns {string}
 */
export function generateId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Non-secret uniqueness fallback (tests / old environments)
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export class WorkspaceDataController {
  /**
   * @param {import("./api").AlexApi} api
   * @param {() => void} onStateChange
   */
  constructor(api, onStateChange) {
    this.api = api;
    this.onStateChange = onStateChange;
    this._destroyed = false;

    // Audit State
    /** @type {import("./domain").AuditPayload | null} */
    this.auditPayload = null;
    this.auditLoading = false;
    /** @type {string | null} */
    this.auditError = null;

    // Brain State
    /** @type {import("./domain").BrainStatus | null} */
    this.brainPayload = null;
    this.brainLoading = false;
    /** @type {string | null} */
    this.brainError = null;
    this.brainWakeInFlight = false;
    /** @type {number | NodeJS.Timeout | null} */
    this.brainWakePollTimer = null;
    this.brainWakePollCount = 0;
    this.BRAIN_WAKE_POLL_INTERVAL_MS = 2000;
    this.BRAIN_WAKE_MAX_POLLS = 23;

    // Automations State
    /** @type {import("./domain").AutomationRecord[] | null} */
    this.automationsPayload = null;
    this.automationsLoading = false;
    /** @type {string | null} */
    this.automationsError = null;
    /** @type {Set<string>} */
    this.automationRunInFlight = new Set();
    /** @type {Set<string>} */
    this.automationSaveInFlight = new Set();

    // Missions State
    /** @type {import("./domain").MissionRecord[] | null} */
    this.missionsPayload = null;
    /** @type {import("./domain").MissionRunRecord[] | null} */
    this.missionRunsPayload = null;
    this.missionsLoading = false;
    /** @type {string | null} */
    this.missionsError = null;
    /** @type {Set<string>} */
    this.missionRunInFlight = new Set();
    /** @type {Set<string>} */
    this.missionSaveInFlight = new Set();

    // Backup State
    /** @type {import("./domain").BackupHistoryPayload | null} */
    this.backupPayload = null;
    this.backupLoading = false;
    /** @type {string | null} */
    this.backupError = null;
    this.backupCreateInFlight = false;

    // Scenes State
    /** @type {import("./domain").SceneRecord[] | null} */
    this.scenesPayload = null;
    this.scenesLoading = false;
    /** @type {string | null} */
    this.scenesError = null;
    /** @type {Set<string>} */
    this.sceneSaveInFlight = new Set();
  }

  // === LIFECYCLE ===

  destroy() {
    this._destroyed = true;
    this.cancelBrainPolling();
  }

  _notify() {
    if (!this._destroyed) this.onStateChange();
  }

  // === AUDIT ===

  loadAudit(force = false) {
    if (this.auditLoading) return;
    if (!force && (this.auditPayload || this.auditError)) return;
    this.auditLoading = true;
    this.auditError = null;
    this._notify();
    this.api.getAudit().then((payload) => {
      this.auditPayload = payload;
    }).catch((error) => {
      console.error("Audit load failed", error);
      this.auditError = "Loi khi tai du lieu tu backend. Vui long thu lai sau.";
    }).finally(() => {
      this.auditLoading = false;
      this._notify();
    });
  }

  // === BRAIN ===

  cancelBrainPolling() {
    if (this.brainWakePollTimer) {
      clearTimeout(/** @type {number} */(/** @type {unknown} */(this.brainWakePollTimer)));
      this.brainWakePollTimer = null;
    }
    this.brainWakePollCount = 0;
  }

  _scheduleBrainPoll() {
    if (!this.brainWakePollTimer && this.brainWakePollCount < this.BRAIN_WAKE_MAX_POLLS) {
      this.brainWakePollTimer = setTimeout(() => {
        this.brainWakePollTimer = null;
        this.brainWakePollCount += 1;
        this.loadBrain(true);
      }, this.BRAIN_WAKE_POLL_INTERVAL_MS);
    } else if (this.brainWakePollCount >= this.BRAIN_WAKE_MAX_POLLS) {
      if (this.brainPayload && this.brainPayload.state === "waking") {
        this.brainError = "Wake confirmation timed out. Vui long thu lai.";
        this._notify();
      }
      this.cancelBrainPolling();
    }
  }

  loadBrain(force = false) {
    if (this.brainLoading) return;
    if (!force && (this.brainPayload || this.brainError)) return;
    this.brainLoading = true;
    if (force) this.brainError = null;
    this._notify();
    this.api.getBrain().then((payload) => {
      this.brainPayload = payload;
      if (payload.state === "waking") {
        this._scheduleBrainPoll();
      } else {
        this.cancelBrainPolling();
      }
    }).catch((error) => {
      console.error("Brain load failed", error);
      this.brainError = "Loi khi ket noi backend.";
    }).finally(() => {
      this.brainLoading = false;
      this._notify();
    });
  }

  executeWakeBrain() {
    if (this.brainWakeInFlight) return;
    this.brainWakeInFlight = true;
    this.brainError = null;
    this._notify();
    this.api.wakeBrain().then((payload) => {
      this.brainPayload = payload;
      this.brainWakePollCount = 0;
      if (payload.state === "waking") {
        this._scheduleBrainPoll();
      }
    }).catch((error) => {
      console.error("Brain wake failed", error);
      this.brainError = "Loi yeu cau danh thuc. Vui long thu lai.";
    }).finally(() => {
      this.brainWakeInFlight = false;
      this._notify();
    });
  }

  // === AUTOMATIONS ===

  loadAutomations(force = false) {
    if (this.automationsLoading) return;
    if (!force && (this.automationsPayload || this.automationsError)) return;
    this.automationsLoading = true;
    this.automationsError = null;
    this._notify();
    this.api.getAutomations().then((payload) => {
      this.automationsPayload = payload.items;
    }).catch((error) => {
      console.error("Automations load failed", error);
      this.automationsError = "Loi khi tai Automations. Vui long thu lai.";
    }).finally(() => {
      this.automationsLoading = false;
      this._notify();
    });
  }

  /**
   * @param {string} id
   * @param {import("./domain").AutomationDefinition} definition
   * @returns {Promise<boolean>}
   */
  async saveAutomation(id, definition) {
    if (this.automationSaveInFlight.has(id)) return false;
    this.automationSaveInFlight.add(id);
    try {
      await this.api.saveAutomation(id, definition);
      this.automationsError = null;
      this.loadAutomations(true);
      return true;
    } catch (err) {
      console.error("Save automation failed", err);
      return false;
    } finally {
      this.automationSaveInFlight.delete(id);
    }
  }

  /**
   * @param {string} id
   */
  runAutomation(id) {
    if (this.automationRunInFlight.has(id)) return;
    this.automationRunInFlight.add(id);
    this.automationsError = null;
    this._notify();
    this.api.runAutomation(id).then(() => {
      this.loadAutomations(true);
    }).catch((error) => {
      console.error("Automation run failed", error);
      this.automationsError = `Loi khi chay Rule ${id}.`;
    }).finally(() => {
      this.automationRunInFlight.delete(id);
      this._notify();
    });
  }

  // === MISSIONS ===

  loadMissions(force = false) {
    if (this.missionsLoading) return;
    if (!force && (this.missionsPayload || this.missionsError)) return;
    this.missionsLoading = true;
    this.missionsError = null;
    this._notify();
    
    Promise.all([
      this.api.getMissions(),
      this.api.getMissionRuns()
    ]).then(([missions, runs]) => {
      this.missionsPayload = missions.items;
      this.missionRunsPayload = runs.items;
    }).catch((error) => {
      console.error("Missions load failed", error);
      this.missionsError = "Loi khi tai Missions. Vui long thu lai.";
    }).finally(() => {
      this.missionsLoading = false;
      this._notify();
    });
  }

  /**
   * @param {string} id
   * @param {import("./domain").MissionDefinition} definition
   * @returns {Promise<boolean>}
   */
  async saveMission(id, definition) {
    if (this.missionSaveInFlight.has(id)) return false;
    this.missionSaveInFlight.add(id);
    
    try {
      await this.api.saveMission(id, definition);
      this.loadMissions(true);
      return true;
    } catch (error) {
      console.error("Mission save failed", error);
      return false;
    } finally {
      this.missionSaveInFlight.delete(id);
    }
  }

  /**
   * @param {string} id
   */
  runMission(id) {
    if (this.missionRunInFlight.has(id)) return;
    this.missionRunInFlight.add(id);
    this._notify();

    this.api.runMission(id).then(() => {
      this.loadMissions(true);
    }).catch((error) => {
      console.error("Mission run failed", error);
      this.missionsError = `Loi khi chay Mission ${id}.`;
    }).finally(() => {
      this.missionRunInFlight.delete(id);
      this._notify();
    });
  }

  // === BACKUP ===
  /**
   * @param {boolean} force
   */
  loadBackups(force = false) {
    if (this._destroyed) return;
    if (this.backupLoading) return;
    if (!force && (this.backupPayload !== null || this.backupError !== null)) return;

    this.backupLoading = true;
    this.backupError = null;
    this._notify();

    this.api.getBackups().then((payload) => {
      if (this._destroyed) return;
      this.backupPayload = payload;
      this.backupLoading = false;
      this._notify();
    }).catch((error) => {
      if (this._destroyed) return;
      console.error("Backup load failed", error);
      this.backupError = "Loi khi tai du lieu Backup.";
      this.backupLoading = false;
      this._notify();
    });
  }

  async createBackup() {
    if (this.backupCreateInFlight) return false;
    this.backupCreateInFlight = true;
    this.backupError = null;
    this._notify();

    try {
      await this.api.createBackup();
      this.loadBackups(true);
      return true;
    } catch (err) {
      console.error("Create backup failed", err);
      this.backupError = "Loi khi tao backup.";
      return false;
    } finally {
      this.backupCreateInFlight = false;
      this._notify();
    }
  }

  // === SCENES ===
  
  loadScenes(force = false) {
    if (this.scenesLoading) return;
    if (!force && (this.scenesPayload !== null || this.scenesError !== null)) return;
    
    this.scenesLoading = true;
    this.scenesError = null;
    this._notify();

    this.api.getScenes().then((payload) => {
      if (this._destroyed) return;
      this.scenesPayload = payload.items;
      this.scenesLoading = false;
      this._notify();
    }).catch((error) => {
      if (this._destroyed) return;
      console.error("Scenes load failed", error);
      this.scenesError = "Loi khi tai du lieu Scenes.";
      this.scenesLoading = false;
      this._notify();
    });
  }

  /**
   * @param {string} id
   * @param {import("./domain").SceneDefinition} definition
   * @returns {Promise<boolean>}
   */
  async saveScene(id, definition) {
    if (this.sceneSaveInFlight.has(id)) return false;
    this.sceneSaveInFlight.add(id);
    
    try {
      await this.api.saveScene(id, definition);
      this.scenesError = null;
      this.loadScenes(true);
      return true;
    } catch (error) {
      console.error("Scene save failed", error);
      return false;
    } finally {
      this.sceneSaveInFlight.delete(id);
    }
  }
}
