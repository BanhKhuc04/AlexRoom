/**
 * Typed Voice WebSocket Client for ALEX Phase 1.0 Voice Transport.
 * Communicates with backend /api/v1/voice/stream using the first-message auth protocol
 * and typed session events.
 */

export class VoiceClient {
  /**
   * @param {{
   *   onStateChange?: (state: string, data?: Record<string, unknown>) => void,
   *   onTranscript?: (transcript: string, isFinal: boolean) => void,
   *   onAssistantText?: (text: string) => void,
   *   onAudioData?: (audioBase64: string) => void,
   *   onError?: (error: string) => void,
   *   onClose?: () => void
   * }} [callbacks]
   */
  constructor(callbacks = {}) {
    this.callbacks = callbacks;
    /** @type {WebSocket | null} */
    this.ws = null;
    this.sessionId = "";
    this.requestId = "";
    this.authenticated = false;
    this.state = "idle";
    /** @private */
    this._closing = false;
    /** @private */
    this._endedAudio = false;
    /** @private @type {ReturnType<typeof setTimeout> | null} */
    this._authTimer = null;
    /** @private @type {ReturnType<typeof setTimeout> | null} */
    this._closeTimer = null;
  }

  /**
   * Connects to Voice WebSocket endpoint and performs first-message auth.
   * @param {string} apiKey
   * @param {string} [baseUrl]
   * @returns {Promise<boolean>}
   */
  connect(apiKey, baseUrl = "") {
    return new Promise((resolve, reject) => {
      this.close();

      this.sessionId = `session-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      this.requestId = `req-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      this._closing = false;
      this._endedAudio = false;
      this._accumulatedText = "";

      let wsUrl = "";
      const loc = typeof window !== "undefined" ? window.location : { protocol: "http:", host: "localhost:8000", href: "http://localhost:8000" };
      if (baseUrl) {
        const urlObj = new URL(baseUrl, loc.href);
        const wsScheme = urlObj.protocol === "https:" ? "wss:" : "ws:";
        wsUrl = `${wsScheme}//${urlObj.host}/api/v1/voice/stream?session_id=${encodeURIComponent(this.sessionId)}&request_id=${encodeURIComponent(this.requestId)}`;
      } else {
        const wsScheme = loc.protocol === "https:" ? "wss:" : "ws:";
        wsUrl = `${wsScheme}//${loc.host}/api/v1/voice/stream?session_id=${encodeURIComponent(this.sessionId)}&request_id=${encodeURIComponent(this.requestId)}`;
      }

      try {
        this.ws = new WebSocket(wsUrl);
      } catch (err) {
        this.callbacks.onError?.("websocket_connection_failed");
        reject(err);
        return;
      }

      this.ws.binaryType = "arraybuffer";

      this._authTimer = setTimeout(() => {
        if (!this.authenticated) {
          this.close();
          this.callbacks.onError?.("auth_timeout");
          reject(new Error("auth_timeout"));
        }
      }, 5000);

      this.ws.onopen = () => {
        // First message must be auth JSON
        this._safeSend(JSON.stringify({ type: "auth", api_key: apiKey }));
      };

      this.ws.onmessage = (event) => {
        try {
          if (typeof event.data === "string") {
            const msg = JSON.parse(event.data);
            this._handleTextMessage(msg, resolve);
          }
        } catch {
          // Ignore malformed text
        }
      };

      this.ws.onerror = () => {
        this._clearTimers();
        this.callbacks.onError?.("websocket_error");
      };

      this.ws.onclose = () => {
        this._clearTimers();
        this.authenticated = false;
        this._closing = false;
        this._endedAudio = false;
        this.state = "idle";
        this.ws = null;
        this.callbacks.onClose?.();
      };
    });
  }

  /**
   * Centralized safe send primitive.
   * Checks ws exists, is OPEN, and not closing.
   * @param {string | ArrayBuffer | Uint8Array} data
   * @returns {boolean} true if sent
   * @private
   */
  _safeSend(data) {
    if (!this.ws || this._closing) return false;
    const OPEN = typeof WebSocket !== "undefined" ? WebSocket.OPEN : 1;
    if (this.ws.readyState !== OPEN) return false;
    try {
      this.ws.send(data);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Clear all internal timers.
   * @private
   */
  _clearTimers() {
    if (this._authTimer !== null) {
      clearTimeout(this._authTimer);
      this._authTimer = null;
    }
    if (this._closeTimer !== null) {
      clearTimeout(this._closeTimer);
      this._closeTimer = null;
    }
  }

  /**
   * Internal text message handler for typed protocol.
   * @param {any} msg
   * @param {function(boolean): void} resolveConnect
   * @private
   */
  _handleTextMessage(msg, resolveConnect) {
    if (msg.type === "auth_ok" || (msg.state && !this.authenticated)) {
      this.authenticated = true;
      if (this._authTimer !== null) {
        clearTimeout(this._authTimer);
        this._authTimer = null;
      }
      resolveConnect(true);
    }

    if (msg.state) {
      const nextState =
        msg.type === "completed" && msg.is_action === false
          ? "chat_completed"
          : msg.state;

      this.state = nextState;
      this.callbacks.onStateChange?.(nextState, msg);
    }

    if (msg.transcript) {
      this.callbacks.onTranscript?.(msg.transcript, true);
    }

    if (msg.assistant_text) {
      this._accumulatedText = msg.assistant_text;
      this.callbacks.onAssistantText?.(this._accumulatedText);
    }

    if (msg.type === "text_delta" && msg.delta != null) {
      this._accumulatedText += msg.delta;
      this.callbacks.onAssistantText?.(this._accumulatedText);
    }

    if (msg.audio_base64) {
      this.callbacks.onAudioData?.(msg.audio_base64);
    }

    if (msg.error_code) {
      this.callbacks.onError?.(msg.error_code);
    }

    if (msg.type === "no_speech") {
      this.callbacks.onAssistantText?.("Không nghe thấy giọng nói.");
      this.state = "cancelled";
      this.callbacks.onStateChange?.("cancelled");
    }
  }

  /**
   * Sends binary audio chunk (PCM/WAV data) to server.
   * Requires authenticated, OPEN, not ended, and not closing.
   * @param {ArrayBuffer | Uint8Array} chunk
   */
  sendAudioChunk(chunk) {
    if (!this.authenticated || this._endedAudio || this._closing) return;
    this._safeSend(chunk);
  }

  /**
   * Signal end of audio stream. Idempotent.
   */
  endAudio() {
    if (this._endedAudio) return;
    this._endedAudio = true;
    this._safeSend(JSON.stringify({ type: "end_audio" }));
  }

  /**
   * Cancels active session. Idempotent.
   * Sends cancel only while OPEN, uses bounded fallback close.
   */
  cancel() {
    if (this._closing) return;
    this._closing = true;
    this._safeSend(JSON.stringify({ type: "cancel" }));

    // Give server 2s to close gracefully, then force close
    this._closeTimer = setTimeout(() => {
      this._closeTimer = null;
      this._forceClose();
    }, 2000);
  }

  /**
   * Close connection cleanly.
   */
  close() {
    this._forceClose();
  }

  /**
   * Internal force close — detaches all state.
   * @private
   */
  _forceClose() {
    this._clearTimers();
    this._closing = true;
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Safe ignore
      }
      // Don't null ws here — onclose handler will do it
    }
    this.authenticated = false;
    this._endedAudio = false;
    this.state = "idle";
  }
}
