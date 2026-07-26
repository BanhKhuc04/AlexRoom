/**
 * Handles browser-side audio playback for synthesized TTS speech received from Core/Brain.
 * Uses Web Audio API AudioContext for decoding and playback, with barge-in support.
 */

export class VoicePlayback {
  constructor() {
    /** @type {AudioContext | null} */
    this.context = null;
    /** @type {AudioBufferSourceNode | null} */
    this.currentSource = null;
    this.isPlaying = false;
    /** @type {Record<string, any>} */
    this.diagnostics = {
      lastDecodeTimeMs: 0,
      lastDurationSec: 0,
      lastSampleRate: 0,
      decodeErrors: 0,
      playCount: 0,
      decodedBytes: 0,
      isRiff: false,
      isWave: false,
      channels: 0,
      playbackStart: null,
      playbackEnd: null,
    };
  }

  /**
   * Decodes and plays audio data (ArrayBuffer or base64 string).
   * @param {ArrayBuffer | string} audioData
   * @returns {Promise<void>}
   */
  async playAudio(audioData) {
    this.stop();

    let arrayBuffer;
    if (typeof audioData === "string") {
      // Decode base64 string
      const binaryString = window.atob(audioData);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      arrayBuffer = bytes.buffer;
    } else {
      arrayBuffer = audioData;
    }

    this.diagnostics.decodedBytes = arrayBuffer.byteLength;
    if (arrayBuffer.byteLength >= 12) {
      const view = new DataView(arrayBuffer);
      this.diagnostics.isRiff = view.getUint32(0, false) === 0x52494646;
      this.diagnostics.isWave = view.getUint32(8, false) === 0x57415645;
    }

    const AudioContextClass = window.AudioContext || /** @type {typeof AudioContext} */ (Reflect.get(window, "webkitAudioContext"));
    if (!AudioContextClass) return;

    if (!this.context || this.context.state === "closed") {
      this.context = new AudioContextClass();
    }

    if (this.context.state === "suspended") {
      await this.context.resume();
    }

    const startTime = performance.now();
    try {
      const audioBuffer = await this.context.decodeAudioData(arrayBuffer.slice(0));
      const source = this.context.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.context.destination);

      this.currentSource = source;
      this.isPlaying = true;

      this.diagnostics.lastDecodeTimeMs = performance.now() - startTime;
      this.diagnostics.lastDurationSec = audioBuffer.duration;
      this.diagnostics.lastSampleRate = audioBuffer.sampleRate;
      this.diagnostics.channels = audioBuffer.numberOfChannels;
      this.diagnostics.playCount++;
      this.diagnostics.playbackStart = Date.now();
      this.diagnostics.playbackEnd = null;

      return new Promise((resolve) => {
        source.onended = () => {
          this.isPlaying = false;
          this.diagnostics.playbackEnd = Date.now();
          if (this.currentSource === source) {
            this.currentSource = null;
          }
          resolve();
        };
        source.start(0);
      });
    } catch (err) {
      this.isPlaying = false;
      this.diagnostics.decodeErrors++;
      console.warn("TTS Audio Decode Error", err);
    }
  }

  /**
   * Returns current diagnostic metrics.
   * @returns {Record<string, any>}
   */
  getDiagnostics() {
    return { ...this.diagnostics, contextState: this.context?.state || "none" };
  }

  /**
   * Stops current playback immediately (Barge-in / Cancellation).
   */
  stop() {
    if (this.currentSource) {
      try {
        this.currentSource.stop();
        this.currentSource.disconnect();
      } catch {
        // Safe ignore
      }
      this.currentSource = null;
    }
    this.isPlaying = false;
  }

  /**
   * Destroys the audio context.
   */
  async destroy() {
    this.stop();
    if (this.context && this.context.state !== "closed") {
      await this.context.close();
      this.context = null;
    }
  }
}
