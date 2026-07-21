export class AlexRealtime {
  /** @param {{onEvent: (event: {type: string, source: string, data: Record<string, unknown>}) => void, onState?: (state: string) => void}} options */
  constructor(options) {
    this.options = options;
    this.source = null;
    this.retry = 0;
    this.timer = null;
    this.stopped = true;
  }

  start() {
    this.stopped = false;
    this.connect();
  }

  connect() {
    if (this.stopped || document.hidden || this.source) return;
    this.options.onState?.("connecting");
    const source = new EventSource("/api/v1/realtime");
    this.source = source;
    source.onopen = () => {
      this.retry = 0;
      this.options.onState?.("online");
    };
    const eventTypes = ["node_online", "node_offline", "heartbeat", "command_created", "command_sent", "command_ack", "reported_state", "command_confirmed", "command_retry", "command_timeout", "state_mismatch", "telemetry", "security_event", "system_health"];
    for (const eventType of eventTypes) {
      source.addEventListener(eventType, (event) => {
        try { this.options.onEvent(JSON.parse(event.data)); } catch { /* Ignore malformed server event. */ }
      });
    }
    source.onerror = () => {
      source.close();
      if (this.source === source) this.source = null;
      this.options.onState?.("degraded");
      if (this.stopped) return;
      const delay = Math.min(1000 * 2 ** this.retry, 30000);
      this.retry = Math.min(this.retry + 1, 5);
      this.timer = window.setTimeout(() => { this.timer = null; this.connect(); }, delay);
    };
  }

  visibilityChanged() {
    if (document.hidden) this.closeSource();
    else this.connect();
  }

  closeSource() {
    this.source?.close();
    this.source = null;
  }

  destroy() {
    this.stopped = true;
    this.closeSource();
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.timer = null;
  }
}
