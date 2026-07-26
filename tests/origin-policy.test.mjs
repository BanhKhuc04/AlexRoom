import assert from "node:assert/strict";
import test from "node:test";
import { handleMicrophoneOriginPolicy } from "../static/core/origin-policy.js";

test("handleMicrophoneOriginPolicy behavioral tests", () => {
  let navigatedUrl = null;
  let confirmResult = true;
  let confirmCalled = 0;
  let toggleCalled = 0;

  const callbacks = {
    confirm: () => { confirmCalled++; return confirmResult; },
    navigate: (url) => { navigatedUrl = url; },
    toggle: () => { toggleCalled++; }
  };

  function reset() {
    navigatedUrl = null;
    confirmResult = true;
    confirmCalled = 0;
    toggleCalled = 0;
  }

  // 1. Secure context -> toggle directly, no prompt
  reset();
  handleMicrophoneOriginPolicy(true, "https://test.com", callbacks);
  assert.equal(toggleCalled, 1);
  assert.equal(confirmCalled, 0);
  assert.equal(navigatedUrl, null);

  // 2. Insecure context, valid canonical origin, user confirms -> navigate
  reset();
  handleMicrophoneOriginPolicy(false, "https://orangepione.tail81f539.ts.net", callbacks);
  assert.equal(confirmCalled, 1);
  assert.equal(navigatedUrl, "https://orangepione.tail81f539.ts.net");
  assert.equal(toggleCalled, 0);

  // 3. Insecure context, valid canonical origin, user declines -> toggle (fallthrough)
  reset();
  confirmResult = false;
  handleMicrophoneOriginPolicy(false, "https://orangepione.tail81f539.ts.net", callbacks);
  assert.equal(confirmCalled, 1);
  assert.equal(navigatedUrl, null);
  assert.equal(toggleCalled, 1);

  // 4. Insecure context, invalid canonical origins -> fallthrough without prompt or unsafe redirect
  const invalidOrigins = [
    "http://192.168.0.174",
    "javascript:alert(1)",
    "https://user:pass@test.com",
    "https://test.com/path",
    "https://test.com/?query=1",
    "https://test.com/#fragment",
    "",
    null,
    undefined
  ];

  for (const origin of invalidOrigins) {
    reset();
    handleMicrophoneOriginPolicy(false, origin, callbacks);
    assert.equal(confirmCalled, 0, `Prompted on invalid origin: ${origin}`);
    assert.equal(navigatedUrl, null, `Navigated on invalid origin: ${origin}`);
    assert.equal(toggleCalled, 1, `Did not toggle on invalid origin: ${origin}`);
  }
});
