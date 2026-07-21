/**
 * @typedef {"idle" | "queued" | "sending" | "waiting_ack" | "accepted" | "waiting_reported_state" | "retrying" | "confirmed" | "failed" | "timed_out" | "cancelled"} CommandPhase
 * @typedef {{
 *   id: string,
 *   deviceId: string,
 *   action: string,
 *   payload: Record<string, unknown>,
 *   phase: CommandPhase,
 *   requestedAt: string,
 *   updatedAt: string,
 *   acknowledgedAt?: string,
 *   acknowledgmentSource?: string,
 *   failureReason?: string,
 * }} DeviceCommand
 */

/** @type {readonly CommandPhase[]} */
export const COMMAND_PHASES = Object.freeze([
  "idle",
  "queued",
  "sending",
  "waiting_ack",
  "accepted",
  "waiting_reported_state",
  "retrying",
  "confirmed",
  "failed",
  "timed_out",
  "cancelled",
]);

/** @type {Readonly<Record<CommandPhase, readonly CommandPhase[]>>} */
const TRANSITIONS = Object.freeze({
  idle: ["queued", "cancelled"],
  queued: ["sending", "cancelled", "failed"],
  sending: ["waiting_ack", "failed", "timed_out", "cancelled"],
  waiting_ack: ["accepted", "retrying", "failed", "timed_out", "cancelled"],
  accepted: ["waiting_reported_state", "failed", "timed_out", "cancelled"],
  waiting_reported_state: ["confirmed", "failed", "timed_out", "cancelled"],
  retrying: ["sending", "failed", "timed_out", "cancelled"],
  confirmed: [],
  failed: [],
  timed_out: [],
  cancelled: [],
});

/** @type {readonly CommandPhase[]} */
export const TERMINAL_COMMAND_PHASES = Object.freeze([
  "confirmed",
  "failed",
  "timed_out",
  "cancelled",
]);

/**
 * @param {CommandPhase} phase
 */
export function isTerminalCommandPhase(phase) {
  return TERMINAL_COMMAND_PHASES.includes(phase);
}

/**
 * @param {CommandPhase} from
 * @param {CommandPhase} to
 */
export function canTransitionCommand(from, to) {
  return TRANSITIONS[from].includes(to);
}

/**
 * @param {{id?: string, deviceId: string, action: string, payload?: Record<string, unknown>, now?: string}} input
 * @returns {DeviceCommand}
 */
export function createDeviceCommand(input) {
  const now = input.now ?? new Date().toISOString();
  return {
    id: input.id ?? globalThis.crypto?.randomUUID?.() ?? `cmd-${Date.now()}`,
    deviceId: input.deviceId,
    action: input.action,
    payload: input.payload ?? {},
    phase: "queued",
    requestedAt: now,
    updatedAt: now,
  };
}

/**
 * @param {DeviceCommand} command
 * @param {CommandPhase} nextPhase
 * @param {{now?: string, acknowledgmentSource?: string, failureReason?: string}} [evidence]
 * @returns {DeviceCommand}
 */
export function transitionCommand(command, nextPhase, evidence = {}) {
  if (!COMMAND_PHASES.includes(command.phase) || !COMMAND_PHASES.includes(nextPhase)) {
    throw new TypeError(`Unknown command phase: ${command.phase} -> ${nextPhase}`);
  }
  if (!canTransitionCommand(command.phase, nextPhase)) {
    throw new Error(`Invalid command transition: ${command.phase} -> ${nextPhase}`);
  }

  const now = evidence.now ?? new Date().toISOString();
  const next = {
    ...command,
    phase: nextPhase,
    updatedAt: now,
  };

  if (nextPhase === "confirmed") {
    next.acknowledgedAt = now;
    next.acknowledgmentSource = evidence.acknowledgmentSource ?? "reported_state";
  }
  if (nextPhase === "failed" || nextPhase === "timed_out") {
    next.failureReason = evidence.failureReason ?? "Không nhận được bằng chứng xác nhận.";
  }

  return next;
}
