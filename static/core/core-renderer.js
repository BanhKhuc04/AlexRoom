import { createFrameLoop } from "./frame-loop.js";
import { getCoreVisualProfile } from "./core-visuals.js";

/** @typedef {import("./alex-state.js").AlexVisualState} AlexVisualState */
/** @typedef {import("./quality.js").MotionProfile} MotionProfile */

/**
 * Layered Canvas 2D renderer for the ALEX Core. Canvas is intentionally used in
 * Phase 2: it provides optical depth without a WebGL dependency or GPU resource
 * burden, while retaining an explicit cleanup boundary.
 * @param {HTMLCanvasElement} canvas
 * @param {{samples: (count: number, timeSeconds: number, energy: number) => number[]}} waveform
 */
export function createCoreRenderer(canvas, waveform) {
  const context = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d", { alpha: true }));
  if (!context) throw new Error("Canvas 2D is unavailable for ALEX Core");

  /** @type {AlexVisualState} */
  let state = "idle";
  /** @type {MotionProfile} */
  let motion = { quality: "balanced", reducedMotion: false, animationScale: 1, particles: 18, glow: 0.82 };
  let width = 1;
  let height = 1;
  let pixelRatio = 1;
  let stateStartedAt = performance.now();
  let lastPaintAt = 0;
  let active = true;
  let destroyed = false;

  const resizeObserver = new ResizeObserver(() => resize());
  resizeObserver.observe(canvas);

  const loop = createFrameLoop({
    requestFrame: (callback) => window.requestAnimationFrame(callback),
    cancelFrame: (handle) => window.cancelAnimationFrame(handle),
    render,
  });

  function resize() {
    if (destroyed) return;
    const rect = canvas.getBoundingClientRect();
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    const qualityRatio = motion.quality === "performance" ? 1 : motion.quality === "balanced" ? 1.5 : 2;
    pixelRatio = Math.min(window.devicePixelRatio || 1, qualityRatio);
    canvas.width = Math.max(1, Math.round(width * pixelRatio));
    canvas.height = Math.max(1, Math.round(height * pixelRatio));
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    paint(performance.now());
  }

  /** @param {number} time */
  function render(time) {
    const framesPerSecond = motion.quality === "performance" ? 30 : motion.quality === "balanced" ? 50 : 60;
    if (time - lastPaintAt < 1000 / framesPerSecond) return;
    lastPaintAt = time;
    paint(time);
  }

  /** @param {number} time */
  function paint(time) {
    if (destroyed || !active) return;
    const profile = getCoreVisualProfile(state);
    const elapsed = Math.max(0, (time - stateStartedAt) / 1000);
    const timeScale = motion.reducedMotion ? 0 : motion.animationScale;
    const phase = elapsed * timeScale;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.29;

    context.clearRect(0, 0, width, height);
    context.save();
    context.translate(centerX, centerY);
    drawAmbient(profile, radius, phase);
    drawFieldLines(profile, radius, phase);
    drawParticles(profile, radius, phase);
    drawOuterAssembly(profile, radius, phase);
    drawDataArcs(profile, radius, phase);
    drawWaveform(profile, radius, phase);
    drawOpticalCore(profile, radius, phase);
    drawStateSignature(profile, radius, phase);
    context.restore();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawAmbient(profile, radius, phase) {
    const breathe = 1 + Math.sin(phase * 0.62) * 0.018 * profile.pulse;
    const gradient = context.createRadialGradient(0, 0, radius * 0.05, 0, 0, radius * 1.78 * breathe);
    gradient.addColorStop(0, hsla(profile, 0.2 * motion.glow));
    gradient.addColorStop(0.35, hsla(profile, 0.07 * motion.glow));
    gradient.addColorStop(1, hsla(profile, 0));
    context.fillStyle = gradient;
    context.beginPath();
    context.arc(0, 0, radius * 1.8, 0, Math.PI * 2);
    context.fill();

    context.strokeStyle = hsla(profile, 0.08);
    context.lineWidth = 1;
    for (const multiplier of [1.34, 1.56]) {
      context.beginPath();
      context.arc(0, 0, radius * multiplier, 0, Math.PI * 2);
      context.stroke();
    }
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawFieldLines(profile, radius, phase) {
    const lines = motion.quality === "cinematic" ? 12 : motion.quality === "balanced" ? 8 : 4;
    context.save();
    context.rotate(phase * 0.025 * profile.direction);
    for (let index = 0; index < lines; index += 1) {
      const angle = (index / lines) * Math.PI * 2;
      const inner = radius * 1.06;
      const outer = radius * (1.38 + (index % 3) * 0.08);
      context.strokeStyle = hsla(profile, index % 4 === 0 ? 0.18 : 0.07);
      context.beginPath();
      context.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
      context.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
      context.stroke();
    }
    context.restore();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawParticles(profile, radius, phase) {
    if (motion.particles === 0 || profile.energy < 0.15) return;
    context.save();
    context.globalCompositeOperation = "screen";
    for (let index = 0; index < motion.particles; index += 1) {
      const seed = index * 7.731;
      let distance = radius * (1.08 + ((index * 17) % 31) / 38);
      if (state === "thinking") distance -= ((phase * (8 + index % 4)) % (radius * 0.65));
      if (state === "wake") distance = radius * (1.62 - Math.min(0.54, phase * 0.45) + (index % 5) * 0.015);
      const angle = seed + phase * (0.08 + (index % 4) * 0.018) * profile.direction;
      const flicker = 0.45 + 0.45 * Math.sin(phase * 1.7 + seed);
      context.fillStyle = hsla(profile, (0.12 + flicker * 0.42) * profile.energy);
      context.beginPath();
      context.arc(Math.cos(angle) * distance, Math.sin(angle) * distance, index % 6 === 0 ? 1.5 : 0.8, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawOuterAssembly(profile, radius, phase) {
    const rings = [1, 0.84, 0.68];
    const stateIntensity = state === "idle" ? 0.46 : state === "offline" ? 0.35 : 1;
    rings.forEach((multiplier, index) => {
      const direction = index % 2 === 0 ? profile.direction : -profile.direction;
      const speed = profile.rotation * (0.23 + index * 0.13);
      const rotation = phase * speed * direction + index * 0.87;
      const ringRadius = radius * multiplier;
      const segments = index === 0 ? 7 : 5;
      context.lineWidth = index === 2 ? 1.5 : 1;
      for (let segment = 0; segment < segments; segment += 1) {
        const start = rotation + (segment / segments) * Math.PI * 2;
        const span = Math.PI * (index === 0 ? 0.18 : 0.25) * (0.7 + ((segment + index) % 3) * 0.15);
        context.strokeStyle = hsla(profile, ((segment % 3 === 0 ? 0.72 : 0.26) * profile.energy + 0.06) * stateIntensity);
        context.beginPath();
        context.arc(0, 0, ringRadius, start, start + span);
        context.stroke();
      }
      context.strokeStyle = hsla(profile, 0.08);
      context.beginPath();
      context.arc(0, 0, ringRadius, 0, Math.PI * 2);
      context.stroke();
    });
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawDataArcs(profile, radius, phase) {
    if (state !== "acting" && state !== "thinking" && state !== "critical") return;
    context.save();
    context.lineCap = "round";
    const paths = state === "acting" ? 3 : 5;
    for (let index = 0; index < paths; index += 1) {
      const angle = index * (Math.PI * 2 / paths) + phase * 0.28 * profile.direction;
      const inner = state === "thinking" ? radius * 0.35 : radius * 0.82;
      const outer = state === "thinking" ? radius * 1.18 : radius * 1.48;
      const gradient = context.createLinearGradient(Math.cos(angle) * inner, Math.sin(angle) * inner, Math.cos(angle) * outer, Math.sin(angle) * outer);
      gradient.addColorStop(0, hsla(profile, state === "thinking" ? 0.65 : 0.12));
      gradient.addColorStop(1, hsla(profile, state === "thinking" ? 0.08 : 0.7));
      context.strokeStyle = gradient;
      context.lineWidth = state === "acting" && index === 0 ? 2.5 : 1;
      context.beginPath();
      context.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
      context.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
      context.stroke();
    }
    context.restore();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawWaveform(profile, radius, phase) {
    if (profile.wave <= 0) return;
    const count = motion.quality === "performance" ? 42 : motion.quality === "balanced" ? 72 : 96;
    const values = waveform.samples(count, phase, profile.wave * (0.22 + profile.energy * 0.55));
    const baseRadius = radius * 0.52;
    context.save();
    context.globalCompositeOperation = "screen";
    context.strokeStyle = hsla(profile, 0.62);
    context.lineWidth = state === "listening" || state === "speaking" ? 1.5 : 0.8;
    context.beginPath();
    values.forEach((value, index) => {
      const angle = (index / (values.length - 1)) * Math.PI * 2 - Math.PI / 2;
      const distance = baseRadius + value * radius * 0.15 * profile.wave;
      const x = Math.cos(angle) * distance;
      const y = Math.sin(angle) * distance;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.closePath();
    context.stroke();
    context.restore();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawOpticalCore(profile, radius, phase) {
    const pulse = 1 + Math.sin(phase * (0.8 + profile.pulse * 1.5)) * 0.025 * profile.pulse;
    const opticalRadius = radius * 0.42 * pulse;
    context.save();
    context.globalCompositeOperation = "screen";
    const glow = context.createRadialGradient(-opticalRadius * 0.18, -opticalRadius * 0.22, 1, 0, 0, opticalRadius * 1.5);
    glow.addColorStop(0, "rgba(240, 254, 255, 0.98)");
    glow.addColorStop(0.08, hsla(profile, 0.82));
    glow.addColorStop(0.34, hsla(profile, 0.26 * motion.glow));
    glow.addColorStop(0.7, hsla(profile, 0.05));
    glow.addColorStop(1, hsla(profile, 0));
    context.fillStyle = glow;
    context.beginPath();
    context.arc(0, 0, opticalRadius * 1.55, 0, Math.PI * 2);
    context.fill();
    context.restore();

    const lens = context.createRadialGradient(-opticalRadius * 0.22, -opticalRadius * 0.28, 0, 0, 0, opticalRadius);
    lens.addColorStop(0, "rgba(238, 254, 255, 0.9)");
    lens.addColorStop(0.08, hsla(profile, 0.78));
    lens.addColorStop(0.28, hsla(profile, 0.3));
    lens.addColorStop(0.72, "rgba(2, 13, 18, 0.96)");
    lens.addColorStop(1, hsla(profile, 0.38));
    context.fillStyle = lens;
    context.beginPath();
    context.arc(0, 0, opticalRadius, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = hsla(profile, 0.72);
    context.lineWidth = 1;
    context.stroke();

    context.strokeStyle = hsla(profile, 0.28);
    context.beginPath();
    context.arc(0, 0, opticalRadius * 0.73, phase * -0.12, phase * -0.12 + Math.PI * 1.45);
    context.stroke();
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} radius @param {number} phase */
  function drawStateSignature(profile, radius, phase) {
    if (state === "warning" || state === "critical") {
      const interruptions = state === "critical" ? 4 : 2;
      context.save();
      context.rotate(Math.sin(phase * 5) * profile.turbulence * 0.04);
      for (let index = 0; index < interruptions; index += 1) {
        const angle = index * Math.PI * 2 / interruptions + phase * 0.08;
        context.strokeStyle = hsla(profile, 0.45 + index * 0.08);
        context.lineWidth = 2;
        context.beginPath();
        context.arc(0, 0, radius * (1.1 + index * 0.07), angle, angle + Math.PI * 0.16);
        context.stroke();
      }
      context.restore();
    }
    if (state === "offline") {
      context.strokeStyle = hsla(profile, 0.3);
      context.setLineDash([2, 7]);
      context.beginPath();
      context.arc(0, 0, radius * 0.58, 0, Math.PI * 2);
      context.stroke();
      context.setLineDash([]);
    }
  }

  /** @param {import("./core-visuals.js").CoreVisualProfile} profile @param {number} alpha */
  function hsla(profile, alpha) {
    return `hsla(${profile.hue} ${profile.saturation}% ${profile.lightness}% / ${Math.max(0, Math.min(1, alpha))})`;
  }

  /** @param {AlexVisualState} next */
  function setState(next) {
    getCoreVisualProfile(next);
    state = next;
    stateStartedAt = performance.now();
    if (motion.reducedMotion) paint(stateStartedAt);
  }

  /** @param {MotionProfile} next */
  function setMotionProfile(next) {
    motion = next;
    canvas.dataset.quality = next.quality;
    canvas.dataset.reducedMotion = String(next.reducedMotion);
    resize();
    syncLoop();
  }

  /** @param {boolean} next */
  function setActive(next) {
    active = next && !destroyed;
    canvas.dataset.rendererActive = String(active && !motion.reducedMotion);
    syncLoop();
    if (active) paint(performance.now());
  }

  function syncLoop() {
    if (active && !destroyed && !motion.reducedMotion) loop.start();
    else loop.stop();
    canvas.dataset.rendererActive = String(loop.diagnostics.active);
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    active = false;
    loop.destroy();
    resizeObserver.disconnect();
    context.clearRect(0, 0, width, height);
    canvas.width = 1;
    canvas.height = 1;
    canvas.dataset.rendererActive = "false";
    canvas.dataset.rendererDestroyed = "true";
  }

  resize();
  syncLoop();

  return Object.freeze({
    setState,
    setMotionProfile,
    setActive,
    destroy,
    get diagnostics() {
      return Object.freeze({
        ...loop.diagnostics,
        state,
        quality: motion.quality,
        reducedMotion: motion.reducedMotion,
        active,
        destroyed,
        width: Math.round(width),
        height: Math.round(height),
        pixelRatio,
      });
    },
  });
}
