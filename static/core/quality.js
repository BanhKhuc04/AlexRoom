/**
 * @typedef {"performance" | "balanced" | "cinematic"} QualityMode
 * @typedef {{quality: QualityMode, reducedMotion: boolean, animationScale: number, particles: number, glow: number}} MotionProfile
 */

/** @type {readonly QualityMode[]} */
export const QUALITY_MODES = Object.freeze(["performance", "balanced", "cinematic"]);

/**
 * @param {string | null | undefined} value
 * @returns {QualityMode}
 */
export function normalizeQualityMode(value) {
  return QUALITY_MODES.includes(/** @type {QualityMode} */ (value))
    ? /** @type {QualityMode} */ (value)
    : "balanced";
}

/**
 * @param {QualityMode} quality
 * @param {boolean} reducedMotion
 * @returns {MotionProfile}
 */
export function createMotionProfile(quality, reducedMotion) {
  if (!QUALITY_MODES.includes(quality)) {
    throw new TypeError(`Unknown quality mode: ${quality}`);
  }

  if (reducedMotion) {
    return { quality, reducedMotion: true, animationScale: 0, particles: 0, glow: 0.55 };
  }

  const profiles = {
    performance: { animationScale: 0.55, particles: 0, glow: 0.65 },
    balanced: { animationScale: 1, particles: 18, glow: 0.82 },
    cinematic: { animationScale: 1.35, particles: 42, glow: 1 },
  };

  return { quality, reducedMotion: false, ...profiles[quality] };
}
