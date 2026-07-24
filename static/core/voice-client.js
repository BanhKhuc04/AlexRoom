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

      const authTimer = setTimeout(() => {
        if (!this.authenticated) {
          this.close();
          this.callbacks.onError?.("auth_timeout");
          reject(new Error("auth_timeout"));
        }
      }, 5000);

      this.ws.onopen = () => {
        // First message must be auth JSON
        if (this.ws && (this.ws.readyState === 1 || this.ws.readyState === (typeof WebSocket !== "undefined" ? WebSocket.OPEN : 1))) {
          this.ws.send(JSON.stringify({ type: "auth", api_key: apiKey }));
        }
      };

      this.ws.onmessage = (event) => {
        try {
          if (typeof event.data === "string") {
            const msg = JSON.parse(event.data);
            this._handleTextMessage(msg, authTimer, resolve);
          }
        } catch {
          // Ignore malformed text
        }
      };

      this.ws.onerror = (err) => {
        clearTimeout(authTimer);
        this.callbacks.onError?.("websocket_error");
      };

      this.ws.onclose = () => {
        clearTimeout(authTimer);
        this.authenticated = false;
        this.state = "idle";
        this.callbacks.onClose?.();
      };
    });
  }

  /**
   * Internal text message handler for typed protocol.
   * @private
   */
  _handleTextMessage(msg, authTimer, resolveConnect) {
    if (msg.type === "auth_ok" || (msg.state && !this.authenticated)) {
      this.authenticated = true;
      clearTimeout(authTimer);
      resolveConnect(true);
    }

    if (msg.state) {
      this.state = msg.state;
      this.callbacks.onStateChange?.(msg.state, msg);
    }

    if (msg.transcript) {
      this.callbacks.onTranscript?.(msg.transcript, true);
    }

    if (msg.assistant_text) {
      this.callbacks.onAssistantText?.(msg.assistant_text);
    }

    if (msg.audio_base64) {
      this.callbacks.onAudioData?.(msg.audio_base64);
    }

    if (msg.error_code) {
      this.callbacks.onError?.(msg.error_code);
    }
  }

  /**
   * Sends binary audio chunk (PCM/WAV data) to server.
   * @param {ArrayBuffer | Uint8Array} chunk
   */
  sendAudioChunk(chunk) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(chunk);
    }
  }

  /**
   * Signal end of audio stream.
   */
  endAudio() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "end_audio" }));
      // Also send legacy string frame for backward compat if server expects text
      this.ws.send("DONE");
    }
  }

  /**
   * Cancels active session.
   */
  cancel() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel" }));
      this.ws.send("CANCEL");
    }
    this.close();
  }

  /**
   * Close connection cleanly.
   */
  close() {
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Safe ignore
      }
      this.ws = null;
    }
    this.authenticated = false;
    this.state = "idle";
  }
}
