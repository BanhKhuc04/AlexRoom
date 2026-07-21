/**
 * @typedef {"idle" | "wake" | "listening" | "thinking" | "acting" | "speaking" | "success" | "warning" | "critical" | "offline"} AlexVisualState
 */

/** @type {readonly AlexVisualState[]} */
export const ALEX_VISUAL_STATES = Object.freeze([
  "idle",
  "wake",
  "listening",
  "thinking",
  "acting",
  "speaking",
  "success",
  "warning",
  "critical",
  "offline",
]);

/** @type {Readonly<Record<AlexVisualState, readonly AlexVisualState[]>>} */
const TRANSITIONS = Object.freeze({
  idle: ["wake", "warning", "critical", "offline"],
  wake: ["listening", "thinking", "idle", "warning", "offline"],
  listening: ["thinking", "idle", "warning", "offline"],
  thinking: ["acting", "speaking", "success", "warning", "critical", "idle", "offline"],
  acting: ["speaking", "success", "warning", "critical", "idle", "offline"],
  speaking: ["success", "warning", "critical", "idle", "offline"],
  success: ["idle", "wake", "offline"],
  warning: ["idle", "wake", "critical", "offline"],
  critical: ["warning", "idle", "offline"],
  offline: ["idle", "warning", "critical"],
});

/** @type {Readonly<Record<AlexVisualState, {label: string, detail: string}>>} */
export const ALEX_STATE_COPY = Object.freeze({
  idle: { label: "Sẵn sàng", detail: "Chạm vào lõi khi bạn cần ALEX" },
  wake: { label: "Đang kết nối", detail: "ALEX đang mở kênh tương tác" },
  listening: { label: "Đang lắng nghe", detail: "Nhập lệnh hoặc chọn một tác vụ" },
  thinking: { label: "Đang phân tích", detail: "Xác định ý định và điều kiện hiện tại" },
  acting: { label: "Đang thực hiện", detail: "Chờ phản hồi xác nhận từ hệ thống" },
  speaking: { label: "Đang phản hồi", detail: "Kênh trả lời của ALEX đang hoạt động" },
  success: { label: "Đã xác nhận", detail: "Kết quả có bằng chứng từ reported state" },
  warning: { label: "Cần chú ý", detail: "Một phần hệ thống chưa thể xác nhận" },
  critical: { label: "Cảnh báo nghiêm trọng", detail: "Hành động đã dừng ở trạng thái an toàn" },
  offline: { label: "Mất kết nối", detail: "ALEX Core chưa phản hồi; không gửi lệnh điều khiển" },
});

/**
 * @param {AlexVisualState} from
 * @param {AlexVisualState} to
 */
export function canTransitionAlexState(from, to) {
  return from === to || TRANSITIONS[from].includes(to);
}

/**
 * @param {AlexVisualState} from
 * @param {AlexVisualState} to
 * @returns {AlexVisualState}
 */
export function transitionAlexState(from, to) {
  if (!ALEX_VISUAL_STATES.includes(from) || !ALEX_VISUAL_STATES.includes(to)) {
    throw new TypeError(`Unknown ALEX visual state: ${from} -> ${to}`);
  }
  if (!canTransitionAlexState(from, to)) {
    throw new Error(`Invalid ALEX visual transition: ${from} -> ${to}`);
  }
  return to;
}

/**
 * @param {AlexVisualState} [initialState]
 */
export function createAlexStateMachine(initialState = "idle") {
  if (!ALEX_VISUAL_STATES.includes(initialState)) {
    throw new TypeError(`Unknown initial ALEX state: ${initialState}`);
  }

  /** @type {AlexVisualState} */
  let current = initialState;

  return Object.freeze({
    get value() {
      return current;
    },
    /** @param {AlexVisualState} next */
    can(next) {
      return canTransitionAlexState(current, next);
    },
    /** @param {AlexVisualState} next */
    transition(next) {
      current = transitionAlexState(current, next);
      return current;
    },
  });
}
