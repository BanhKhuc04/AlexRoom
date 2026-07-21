/** @typedef {"synthetic" | "requesting" | "microphone" | "denied" | "unavailable"} WaveformMode */

/**
 * Owns the optional microphone graph. No AudioContext or MediaStream is created
 * before an explicit user gesture, and every node/track is released by stop().
 * @param {Navigator} navigatorObject
 * @param {Window} windowObject
 */
export function createAudioWaveform(navigatorObject = navigator, windowObject = window) {
  /** @type {AudioContext | null} */
  let context = null;
  /** @type {AnalyserNode | null} */
  let analyser = null;
  /** @type {MediaStreamAudioSourceNode | null} */
  let source = null;
  /** @type {MediaStream | null} */
  let stream = null;
  /** @type {Uint8Array<ArrayBuffer> | null} */
  let bytes = null;
  /** @type {WaveformMode} */
  let mode = "synthetic";

  async function start() {
    if (mode === "microphone") return true;
    if (!navigatorObject.mediaDevices?.getUserMedia) {
      mode = "unavailable";
      return false;
    }
    const AudioContextClass = /** @type {typeof AudioContext | undefined} */ (/** @type {unknown} */ (Reflect.get(windowObject, "AudioContext")));
    if (!AudioContextClass) {
      mode = "unavailable";
      return false;
    }
    mode = "requesting";
    try {
      stream = await navigatorObject.mediaDevices.getUserMedia({ audio: true, video: false });
      const nextContext = new AudioContextClass();
      const nextAnalyser = nextContext.createAnalyser();
      nextAnalyser.fftSize = 256;
      nextAnalyser.smoothingTimeConstant = 0.78;
      const nextSource = nextContext.createMediaStreamSource(stream);
      nextSource.connect(nextAnalyser);
      context = nextContext;
      analyser = nextAnalyser;
      source = nextSource;
      bytes = new Uint8Array(nextAnalyser.frequencyBinCount);
      mode = "microphone";
      return true;
    } catch {
      await stop();
      mode = "denied";
      return false;
    }
  }

  async function stop() {
    source?.disconnect();
    analyser?.disconnect();
    stream?.getTracks().forEach((track) => track.stop());
    if (context && context.state !== "closed") await context.close();
    context = null;
    analyser = null;
    source = null;
    stream = null;
    bytes = null;
    if (mode === "microphone" || mode === "requesting") mode = "synthetic";
  }

  /**
   * @param {number} count
   * @param {number} timeSeconds
   * @param {number} semanticEnergy
   */
  function samples(count, timeSeconds, semanticEnergy) {
    const currentAnalyser = analyser;
    const currentBytes = bytes;
    if (currentAnalyser && currentBytes) {
      currentAnalyser.getByteTimeDomainData(currentBytes);
      return Array.from({ length: count }, (_, index) => {
        const sourceIndex = Math.floor((index / Math.max(1, count - 1)) * (currentBytes.length - 1));
        return Math.max(-1, Math.min(1, ((currentBytes[sourceIndex] ?? 128) - 128) / 128));
      });
    }
    return Array.from({ length: count }, (_, index) => {
      const envelope = Math.sin((index / Math.max(1, count - 1)) * Math.PI);
      const carrier = Math.sin(index * 1.13 + timeSeconds * 4.1) * 0.58 + Math.sin(index * 0.41 - timeSeconds * 2.7) * 0.24;
      return carrier * envelope * semanticEnergy;
    });
  }

  return Object.freeze({
    start,
    stop,
    samples,
    get mode() { return mode; },
    get diagnostics() {
      return Object.freeze({
        mode,
        hasContext: context !== null,
        hasStream: stream !== null,
        liveTracks: stream?.getTracks().filter((track) => track.readyState === "live").length ?? 0,
      });
    },
  });
}
