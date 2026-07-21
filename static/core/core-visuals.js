import { ALEX_VISUAL_STATES } from "./alex-state.js";

/** @typedef {import("./alex-state.js").AlexVisualState} AlexVisualState */

/**
 * Visual parameters are data, not animation logic. Keeping them centralized makes
 * every state auditable and prevents decorative motion from drifting away from meaning.
 * @typedef {{
 *   hue: number,
 *   saturation: number,
 *   lightness: number,
 *   energy: number,
 *   rotation: number,
 *   pulse: number,
 *   wave: number,
 *   direction: -1 | 0 | 1,
 *   turbulence: number,
 *   label: string
 * }} CoreVisualProfile
 */

/** @type {Readonly<Record<AlexVisualState, CoreVisualProfile>>} */
export const CORE_VISUAL_PROFILES = Object.freeze({
  idle: Object.freeze({ hue: 190, saturation: 92, lightness: 62, energy: 0.26, rotation: 0.12, pulse: 0.14, wave: 0.08, direction: 1, turbulence: 0.06, label: "CALM ORBIT" }),
  wake: Object.freeze({ hue: 190, saturation: 98, lightness: 70, energy: 0.72, rotation: 0.7, pulse: 0.85, wave: 0.3, direction: -1, turbulence: 0.12, label: "RINGS ALIGNING" }),
  listening: Object.freeze({ hue: 188, saturation: 96, lightness: 68, energy: 0.58, rotation: 0.3, pulse: 0.42, wave: 1, direction: 1, turbulence: 0.16, label: "INPUT CHANNEL" }),
  thinking: Object.freeze({ hue: 201, saturation: 92, lightness: 65, energy: 0.7, rotation: 0.92, pulse: 0.28, wave: 0.42, direction: -1, turbulence: 0.28, label: "INWARD PROCESSING" }),
  acting: Object.freeze({ hue: 184, saturation: 96, lightness: 62, energy: 0.88, rotation: 0.55, pulse: 0.5, wave: 0.22, direction: 1, turbulence: 0.08, label: "ACTION PATH" }),
  speaking: Object.freeze({ hue: 176, saturation: 84, lightness: 64, energy: 0.66, rotation: 0.24, pulse: 0.62, wave: 0.9, direction: 1, turbulence: 0.12, label: "OUTPUT CHANNEL" }),
  success: Object.freeze({ hue: 154, saturation: 73, lightness: 60, energy: 0.76, rotation: 0.2, pulse: 0.95, wave: 0.16, direction: 0, turbulence: 0.04, label: "CONFIRMED" }),
  warning: Object.freeze({ hue: 38, saturation: 100, lightness: 66, energy: 0.62, rotation: 0.12, pulse: 0.68, wave: 0.24, direction: -1, turbulence: 0.36, label: "VERIFY STATE" }),
  critical: Object.freeze({ hue: 7, saturation: 100, lightness: 66, energy: 0.9, rotation: 0.08, pulse: 1, wave: 0.18, direction: 0, turbulence: 0.58, label: "SAFE STOP" }),
  offline: Object.freeze({ hue: 198, saturation: 16, lightness: 52, energy: 0.12, rotation: 0, pulse: 0.04, wave: 0, direction: 0, turbulence: 0, label: "NO CARRIER" }),
});

/** @param {AlexVisualState} state */
export function getCoreVisualProfile(state) {
  if (!ALEX_VISUAL_STATES.includes(state)) throw new TypeError(`Unknown Core visual state: ${state}`);
  return CORE_VISUAL_PROFILES[state];
}

