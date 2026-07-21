/**
 * A small, testable requestAnimationFrame owner. It guarantees at most one
 * scheduled frame and exposes diagnostics used by the browser cleanup smoke test.
 * @param {{
 *   requestFrame: (callback: FrameRequestCallback) => number,
 *   cancelFrame: (handle: number) => void,
 *   render: (time: number) => void
 * }} options
 */
export function createFrameLoop({ requestFrame, cancelFrame, render }) {
  let frameHandle = 0;
  let active = false;
  let destroyed = false;
  let renderedFrames = 0;

  /** @param {number} time */
  function tick(time) {
    frameHandle = 0;
    if (!active || destroyed) return;
    render(time);
    renderedFrames += 1;
    frameHandle = requestFrame(tick);
  }

  function start() {
    if (destroyed || active) return;
    active = true;
    frameHandle = requestFrame(tick);
  }

  function stop() {
    active = false;
    if (frameHandle) cancelFrame(frameHandle);
    frameHandle = 0;
  }

  function destroy() {
    stop();
    destroyed = true;
  }

  return Object.freeze({
    start,
    stop,
    destroy,
    get diagnostics() {
      return Object.freeze({ active, destroyed, pendingFrames: frameHandle ? 1 : 0, renderedFrames });
    },
  });
}

