/**
 * Captures audio from a MediaStream, resamples to 16kHz mono 16-bit signed PCM LE,
 * and packages it as chunks and WAV header payload for Voice Client streaming.
 */

export class AudioRecorder {
  /**
   * @param {{ onChunk?: (chunk: ArrayBuffer) => void }} [options]
   */
  constructor(options = {}) {
    this.options = options;
    /** @type {AudioContext | null} */
    this.context = null;
    /** @type {MediaStreamAudioSourceNode | null} */
    this.source = null;
    /** @type {ScriptProcessorNode | null} */
    this.processor = null;
    /** @type {Float32Array[]} */
    this.pcmChunks = [];
    this.recording = false;
  }

  /**
   * Starts recording from an existing MediaStream.
   * @param {MediaStream} stream
   */
  start(stream) {
    if (this.recording) return;
    this.pcmChunks = [];

    const AudioContextClass = window.AudioContext || /** @type {typeof AudioContext} */ (Reflect.get(window, "webkitAudioContext"));
    if (!AudioContextClass) {
      throw new Error("AudioContext not supported");
    }

    this.context = new AudioContextClass({ sampleRate: 16000 });
    this.source = this.context.createMediaStreamSource(stream);

    // ScriptProcessorNode with buffer size 4096, 1 input channel, 1 output channel
    this.processor = this.context.createScriptProcessor(4096, 1, 1);

    this.processor.onaudioprocess = (e) => {
      if (!this.recording) return;
      const inputBuffer = e.inputBuffer.getChannelData(0);
      const copy = new Float32Array(inputBuffer.length);
      copy.set(inputBuffer);
      this.pcmChunks.push(copy);

      // Convert chunk to Int16 PCM and emit
      const pcm16Chunk = this._encodePCM16Chunk(copy);
      this.options.onChunk?.(pcm16Chunk.buffer);
    };

    this.source.connect(this.processor);
    this.processor.connect(this.context.destination);
    this.recording = true;
  }

  /**
   * Stops recording and returns complete WAV Audio ArrayBuffer (16kHz 16-bit mono).
   * @returns {Promise<ArrayBuffer>}
   */
  async stop() {
    this.recording = false;

    if (this.processor) {
      this.processor.disconnect();
      this.processor.onaudioprocess = null;
      this.processor = null;
    }

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }

    if (this.context && this.context.state !== "closed") {
      await this.context.close();
      this.context = null;
    }

    return this._exportWAV();
  }

  /**
   * Encodes a single Float32 chunk to Int16 PCM.
   * @private
   */
  _encodePCM16Chunk(samples) {
    const buffer = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      buffer[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return buffer;
  }

  /**
   * Exports accumulated Float32 PCM samples to a 16kHz 16-bit Mono WAV ArrayBuffer.
   * @private
   */
  _exportWAV() {
    let totalSamples = 0;
    for (const chunk of this.pcmChunks) {
      totalSamples += chunk.length;
    }

    const wavBuffer = new ArrayBuffer(44 + totalSamples * 2);
    const view = new DataView(wavBuffer);

    // RIFF chunk descriptor
    this._writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + totalSamples * 2, true);
    this._writeString(view, 8, "WAVE");

    // fmt sub-chunk
    this._writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, 1, true);  // AudioFormat (1 for PCM)
    view.setUint16(22, 1, true);  // NumChannels (1 mono)
    view.setUint32(24, 16000, true); // SampleRate (16000)
    view.setUint32(28, 16000 * 2, true); // ByteRate (SampleRate * NumChannels * BitsPerSample/8)
    view.setUint16(32, 2, true);  // BlockAlign (NumChannels * BitsPerSample/8)
    view.setUint16(34, 16, true); // BitsPerSample (16)

    // data sub-chunk
    this._writeString(view, 36, "data");
    view.setUint32(40, totalSamples * 2, true);

    // Write Float32 PCM to Int16
    let offset = 44;
    for (const chunk of this.pcmChunks) {
      for (let i = 0; i < chunk.length; i++) {
        const s = Math.max(-1, Math.min(1, chunk[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        offset += 2;
      }
    }

    return wavBuffer;
  }

  /**
   * Writes string to DataView.
   * @private
   */
  _writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }
}
