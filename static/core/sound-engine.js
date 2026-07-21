/** @typedef {"normal" | "quiet" | "night" | "silent"} SoundMode */
/** @typedef {"interface" | "alerts" | "voice" | "ambience"} SoundGroup */
/** @typedef {{mode: SoundMode, master: number, interface: number, alerts: number, voice: number, ambience: number}} SoundSettings */
/** @typedef {{group: SoundGroup, priority: number, frequency: number, endFrequency: number, duration: number}} SoundCue */

/** @type {Readonly<Record<string, SoundCue>>} */
export const SOUND_CUES = Object.freeze({
  wake: { group: "interface", priority: 2, frequency: 410, endFrequency: 690, duration: 0.18 },
  listen_open: { group: "interface", priority: 2, frequency: 620, endFrequency: 760, duration: 0.12 },
  input_accept: { group: "interface", priority: 3, frequency: 520, endFrequency: 430, duration: 0.1 },
  processing_delay: { group: "interface", priority: 1, frequency: 280, endFrequency: 340, duration: 0.16 },
  action_success: { group: "alerts", priority: 4, frequency: 480, endFrequency: 880, duration: 0.24 },
  action_partial: { group: "alerts", priority: 5, frequency: 420, endFrequency: 360, duration: 0.22 },
  warning: { group: "alerts", priority: 7, frequency: 330, endFrequency: 250, duration: 0.3 },
  critical: { group: "alerts", priority: 10, frequency: 190, endFrequency: 120, duration: 0.42 },
  offline: { group: "alerts", priority: 8, frequency: 260, endFrequency: 110, duration: 0.38 },
  cancel: { group: "interface", priority: 3, frequency: 360, endFrequency: 220, duration: 0.12 },
});

/** @type {Readonly<SoundSettings>} */
export const DEFAULT_SOUND_SETTINGS = Object.freeze({
  mode: "normal",
  master: 0.55,
  interface: 0.7,
  alerts: 0.82,
  voice: 0.85,
  ambience: 0,
});

const MODE_SCALE = Object.freeze({ normal: 1, quiet: 0.45, night: 0.24, silent: 0 });

/** @param {unknown} value */
function volume(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : 0;
}

/** @param {Partial<SoundSettings>} raw @returns {Readonly<SoundSettings>} */
export function normalizeSoundSettings(raw = {}) {
  const mode = Object.hasOwn(MODE_SCALE, raw.mode ?? "") ? /** @type {SoundMode} */ (raw.mode) : "normal";
  return Object.freeze({
    mode,
    master: volume(raw.master ?? DEFAULT_SOUND_SETTINGS.master),
    interface: volume(raw.interface ?? DEFAULT_SOUND_SETTINGS.interface),
    alerts: volume(raw.alerts ?? DEFAULT_SOUND_SETTINGS.alerts),
    voice: volume(raw.voice ?? DEFAULT_SOUND_SETTINGS.voice),
    ambience: volume(raw.ambience ?? DEFAULT_SOUND_SETTINGS.ambience),
  });
}

/**
 * Centralized, gesture-unlocked Web Audio engine. It never creates more than one
 * AudioContext and isolates cue failures from application state transitions.
 * @param {{AudioContext?: typeof AudioContext, now?: () => number}} environment
 */
export function createSoundEngine(environment = {}) {
  const AudioContextClass = environment.AudioContext;
  const now = environment.now ?? (() => Date.now());
  /** @type {Readonly<SoundSettings>} */
  let settings = DEFAULT_SOUND_SETTINGS;
  /** @type {AudioContext | null} */
  let context = null;
  /** @type {GainNode | null} */
  let masterGain = null;
  /** @type {Record<SoundGroup, GainNode> | null} */
  let groups = null;
  let unlocked = false;
  let destroyed = false;
  let ducked = false;
  let activePriority = -1;
  let activeUntil = 0;
  const recent = new Map();

  function ensureGraph() {
    if (destroyed || context || !AudioContextClass) return context;
    context = new AudioContextClass();
    masterGain = context.createGain();
    groups = {
      interface: context.createGain(),
      alerts: context.createGain(),
      voice: context.createGain(),
      ambience: context.createGain(),
    };
    const rootGain = masterGain;
    Object.values(groups).forEach((node) => node.connect(rootGain));
    rootGain.connect(context.destination);
    applyGains();
    return context;
  }

  function applyGains() {
    if (!context || !masterGain || !groups) return;
    const at = context.currentTime;
    const scale = MODE_SCALE[settings.mode];
    masterGain.gain.setTargetAtTime(settings.master * scale, at, 0.025);
    groups.interface.gain.setTargetAtTime(settings.interface * (ducked ? 0.2 : 1), at, 0.025);
    groups.alerts.gain.setTargetAtTime(settings.alerts * (ducked ? 0.35 : 1), at, 0.025);
    groups.voice.gain.setTargetAtTime(settings.voice, at, 0.025);
    groups.ambience.gain.setTargetAtTime(settings.ambience, at, 0.08);
  }

  async function unlock() {
    const graph = ensureGraph();
    if (!graph) return false;
    try {
      if (graph.state === "suspended") await graph.resume();
      unlocked = graph.state === "running";
      return unlocked;
    } catch {
      unlocked = false;
      return false;
    }
  }

  /** @param {string} name */
  function play(name) {
    const cue = SOUND_CUES[name];
    if (!cue || !unlocked || destroyed || settings.mode === "silent") return false;
    const graph = ensureGraph();
    if (!graph || !groups) return false;
    const timestamp = now();
    if (timestamp - (recent.get(name) ?? -Infinity) < 180) return false;
    if (timestamp < activeUntil && cue.priority < activePriority) return false;
    recent.set(name, timestamp);
    activePriority = cue.priority;
    activeUntil = timestamp + cue.duration * 1000;
    try {
      const oscillator = graph.createOscillator();
      const envelope = graph.createGain();
      const start = graph.currentTime;
      oscillator.type = cue.priority >= 7 ? "triangle" : "sine";
      oscillator.frequency.setValueAtTime(cue.frequency, start);
      oscillator.frequency.exponentialRampToValueAtTime(cue.endFrequency, start + cue.duration);
      envelope.gain.setValueAtTime(0.0001, start);
      envelope.gain.exponentialRampToValueAtTime(0.16, start + Math.min(0.035, cue.duration / 3));
      envelope.gain.exponentialRampToValueAtTime(0.0001, start + cue.duration);
      oscillator.connect(envelope);
      envelope.connect(groups[cue.group]);
      oscillator.start(start);
      oscillator.stop(start + cue.duration + 0.01);
      oscillator.addEventListener("ended", () => { oscillator.disconnect(); envelope.disconnect(); }, { once: true });
      return true;
    } catch {
      return false;
    }
  }

  /** @param {Partial<SoundSettings>} next */
  function configure(next) {
    settings = normalizeSoundSettings({ ...settings, ...next });
    applyGains();
    return settings;
  }

  /** @param {boolean} active */
  function setTtsDucking(active) { ducked = active; applyGains(); }

  async function destroy() {
    if (destroyed) return;
    destroyed = true;
    unlocked = false;
    groups && Object.values(groups).forEach((node) => node.disconnect());
    masterGain?.disconnect();
    if (context && context.state !== "closed") await context.close();
    context = null; masterGain = null; groups = null; recent.clear();
  }

  return Object.freeze({ unlock, play, configure, setTtsDucking, destroy,
    get settings() { return settings; },
    get diagnostics() { return Object.freeze({ hasContext: Boolean(context), unlocked, destroyed, mode: settings.mode, ducked, activePriority }); },
  });
}
