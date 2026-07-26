/**
 * Enforces microphone secure origin policy.
 * @param {boolean} isSecureContext - whether the current context is secure.
 * @param {string|undefined} canonicalOrigin - the canonical origin from config (if any).
 * @param {object} callbacks - functions to execute based on policy.
 * @param {function(string): boolean} callbacks.confirm - function(msg) returning boolean (like window.confirm).
 * @param {function(string): void} callbacks.navigate - function(url) to navigate away.
 * @param {function(): void} callbacks.toggle - function() to toggle microphone.
 */
export function handleMicrophoneOriginPolicy(isSecureContext, canonicalOrigin, callbacks) {
  if (isSecureContext) {
    callbacks.toggle();
    return;
  }

  if (typeof canonicalOrigin === "string" && canonicalOrigin.startsWith("https://")) {
    // Only permit simple https origins without paths/queries that might be malicious.
    // The backend already sanitizes it, but defense-in-depth on frontend.
    try {
      const parsed = new URL(canonicalOrigin);
      if (parsed.protocol === "https:" && parsed.pathname === "/" && !parsed.search && !parsed.hash && !parsed.username && !parsed.password) {
        const canonicalUrl = parsed.origin;
        if (callbacks.confirm(`Trình duyệt yêu cầu kết nối bảo mật (HTTPS) để dùng microphone.\nChuyển sang kênh bảo mật (${canonicalUrl})?`)) {
          callbacks.navigate(canonicalUrl);
          return;
        }
      }
    } catch {
      // Invalid URL falls through
    }
  }

  // Fallthrough to toggle (which handles the DENIED/UNAVAILABLE UI)
  callbacks.toggle();
}
