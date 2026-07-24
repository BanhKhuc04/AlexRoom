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

    const AudioContextClass = window.AudioContext || /** @type {typeof AudioContext} */ (Reflect.get(window, "webkitAudioContext"));
    if (!AudioContextClass) return;

    if (!this.context || this.context.state === "closed") {
      this.context = new AudioContextClass();
    }

    if (this.context.state === "suspended") {
      await this.context.resume();
    }

    try {
      const audioBuffer = await this.context.decodeAudioData(arrayBuffer.slice(0));
      const source = this.context.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.context.destination);

      this.currentSource = source;
      this.isPlaying = true;

      return new Promise((resolve) => {
        source.onended = () => {
          this.isPlaying = false;
          if (this.currentSource === source) {
            this.currentSource = null;
          }
          resolve();
        };
        source.start(0);
      });
    } catch (err) {
      this.isPlaying = false;
      console.warn("TTS Audio Decode Error", err);
    }
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
