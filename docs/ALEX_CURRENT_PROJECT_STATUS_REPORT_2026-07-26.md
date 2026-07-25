# ALEX NEXUS OS / AlexRoom
# BÁO CÁO TÌNH TRẠNG DỰ ÁN HIỆN TẠI & ROADMAP KỸ THUẬT

**Ngày tổng hợp:** 2026-07-26  
**Phạm vi bằng chứng:** toàn bộ lịch sử dự án đã trao đổi, các audit/report đã tải lên, log runtime Orange Pi/Brain, kết quả test, ảnh DevTools/browser, và các báo cáo Codex/Antigravity đến checkpoint `406371c`.  
**Repository:** `BanhKhuc04/AlexRoom`  
**Máy phát triển:** `D:\AlexRoom`  
**Nhánh Voice hiện tại:** `phase-1.0-voice-foundation`  
**Source HEAD mới nhất được báo cáo:** `406371c` — `fix(voice): close phase 1.0 spoken runtime gaps`

> **Lưu ý source-of-truth:** `406371c` đã PASS software test theo báo cáo Codex, nhưng lịch sử trao đổi chưa có log xác nhận đầy đủ rằng cả Orange Pi Core và Brain PC đang cùng chạy commit này. Trạng thái deploy phải được re-verify trước khi coi là runtime source-of-truth.

---

# 0. TÓM TẮT ĐIỀU HÀNH

ALEX hiện không còn là prototype UI đơn thuần. Dự án đã có một nền tảng control-plane tương đối trưởng thành:

- FastAPI Core chạy 24/7 trên Orange Pi.
- SQLite production có backup/recovery.
- Mosquitto MQTT có auth/ACL.
- ESP01 đã tham gia runtime thật.
- Command lifecycle, SafetyPolicy, capability registry và authoritative Core state.
- OTA/rollback/LKG, watchdog, health, backup, recovery và production acceptance.
- ALEX Brain chạy trên PC/VM riêng.
- Intelligence Router và Brain safe-tool boundary.
- Text conversation thật thông qua Brain.
- Voice WebSocket từ browser tới Core.
- STT thật bằng FasterWhisper.
- TTS engine thật bằng Piper.
- Browser là microphone + speaker endpoint.
- Core vẫn là final authority; Brain không được publish MQTT.

Điểm yếu lớn nhất hiện tại **không còn là “chưa có AI/Voice”**, mà là **runtime synchronization và trải nghiệm hội thoại cuối-to-cuối**:

1. Frontend/Presence hiện có dấu hiệu regression hoặc state-machine/cache mismatch: người dùng nói nhưng UI không luôn tự chuyển THINKING, bấm mic đôi khi không phản ứng và không có trả lời.
2. Real speaker E2E chưa được nghiệm thu thành công: chưa có bằng chứng cuối cùng rằng `assistant_text → Piper → speaking audio → Chrome speaker` phát tiếng ổn định.
3. STT model `small` đã tốt hơn đáng kể với mic thật, nhưng trước VAD vẫn hallucinate khi im lặng.
4. Source `406371c` đã thêm VAD/no-speech gating và speaking/audio contract, nhưng chưa có physical acceptance sau deploy.
5. LLM local hiện là nút thắt latency lớn nhất: nhiều request mất khoảng 19–23 giây trên CPU.
6. Conversation semantics trên UI vẫn có trường hợp hội thoại thường bị render như hardware SUCCESS/Evidence.
7. Context/memory đa lượt, streaming, smart turn, bilingual auto-routing, robot voice DSP và realtime voice vẫn thuộc Phase 1.1+.

**Kết luận hiện tại:** ALEX Core/Brain architecture đã đúng hướng và an toàn. Phase 1.0 có thể coi là **software-complete candidate**, nhưng **chưa được phép tuyên bố REAL SPOKEN END-TO-END ACCEPTANCE PASS** cho tới khi frontend/runtime được đồng bộ lại và qua 2 bài kiểm thử vật lý cuối: `silence → no_speech` và `speech → audible reply`.

---

# 1. NGUYÊN TẮC KIẾN TRÚC BẮT BUỘC

## 1.1. Core là final authority

```text
USER / BROWSER
      │
      ▼
ALEX CORE — ORANGE PI
      │
      ├── Authentication
      ├── IntelligenceRouter
      ├── SafetyPolicy
      ├── CapabilityRegistry
      ├── Command lifecycle
      ├── SQLite authoritative state/audit
      ├── MQTT authority
      └── Hardware verification
      │
      ▼
     MQTT
      │
      ▼
    ESP01
```

Brain không được trở thành hardware authority.

## 1.2. Brain chỉ compute/propose

```text
ALEX CORE
   │
   ├── STT request ──────> ALEX BRAIN
   ├── LLM request ──────> ALEX BRAIN
   └── TTS request ──────> ALEX BRAIN

ALEX BRAIN
   ├── STT compute
   ├── reasoning/LLM
   ├── structured tool proposals
   └── TTS compute
```

Brain:

- không publish MQTT;
- không GPIO;
- không shell để điều khiển hardware;
- không bypass Core;
- không tự xác nhận hardware success;
- không mở khóa relay nguy hiểm.

## 1.3. Browser là endpoint I/O

Browser cung cấp:

- UI;
- microphone capture;
- audio playback;
- Presence state;
- Command Center;
- Voice WebSocket client.

Điều này loại bỏ nhu cầu passthrough audio PCI vào Brain VM.

## 1.4. Hardware truth

Các trạng thái phải phân biệt:

- requested;
- queued;
- sent;
- waiting_ack;
- acknowledged;
- reported;
- verified;
- physically_verified;
- failed/timed_out/cancelled.

Không dùng `SUCCESS` chỉ vì request HTTP trả 200.

---

# 2. PHẦN CỨNG & HẠ TẦNG HIỆN TẠI

## 2.1. Orange Pi One — ALEX Core

Thông tin runtime đã quan sát:

- Host: `orangepione`
- LAN: `192.168.0.174`
- Tailscale đã hoạt động.
- UI: `https://orangepione.tail81f539.ts.net`
- OS: Armbian / Debian trixie.
- Kernel quan sát gần nhất: `6.18.35-current-sunxi`
- RAM thực tế khoảng `484 MiB`.
- Production repository: `/opt/alex/AlexRoom-0.2.0-hardware-rc`
- Production environment: `/etc/alex/alex.env`
- Core service: `alex-core.service`
- HTTP: `0.0.0.0:8000`
- Production DB: `/var/lib/alex/alex.db`

Health từng được xác nhận:

```json
{"api":"online","mqtt":"connected","device":"online"}
```

Core hiện có:

- FastAPI;
- SQLite;
- Mosquitto MQTT;
- SSE realtime;
- Voice WebSocket;
- health;
- backup;
- recovery;
- watchdog;
- OTA/Core update;
- ESP OTA;
- capability registry;
- command lifecycle;
- SafetyPolicy;
- IntelligenceRouter.

## 2.2. Brain PC / Proxmox VM

- Proxmox VMID: `101`
- Hostname: `alex-brain-prod`
- LAN: `192.168.0.216`
- OS: Ubuntu 26.04 LTS
- CPU: host passthrough / 2 cores
- RAM cấu hình khoảng `6560 MB`; runtime nhìn thấy khoảng `5.7 GiB`
- Disk khoảng `40 GB`
- Python: `3.14.4`
- Repository: `/opt/alex/brain`
- Venv: `/opt/alex/brain/.venv`
- Service: `alex-brain.service`
- Service user: `alex-brain`
- HOME: `/var/lib/alex-brain`
- Environment: `/etc/alex/brain.env`
- Brain HTTP: `192.168.0.216:8090`
- Ollama local: `127.0.0.1:11434`

### Audio VM

PCI audio passthrough từng làm VM 101 không start. `hostpci0 00:1b.0` sau đó đã được gỡ.

**Quyết định hiện tại:** không passthrough audio vào Brain. Browser làm mic/speaker.

---

# 3. DATA, BACKUP & SỰ CỐ `git clean -fd`

Người dùng từng chạy:

```bash
git clean -fd
```

trên production repo Orange Pi.

Nó xóa:

```text
backups/
data/
```

trong repository vì hai thư mục này là untracked.

## 3.1. Production data không mất

Kiểm tra xác nhận:

- `/var/lib/alex/alex.db` còn nguyên.
- DB khoảng `304 KiB` tại thời điểm kiểm tra.
- `/var/lib/alex/backups/` còn nhiều backup `.db`.
- `/var/lib/alex/recovery/` còn recovery database.
- `/var/lib/alex/powerloss/probe.db` còn.

## 3.2. Vì sao Core fail sau restart

`alex-core.service` dùng systemd sandbox/mount namespace. Khi `backups/` trong repo bị xóa, service fail:

```text
status=226/NAMESPACE
Failed to set up mount namespacing
```

Sau khi recreate:

```text
/opt/alex/AlexRoom-0.2.0-hardware-rc/backups
/opt/alex/AlexRoom-0.2.0-hardware-rc/data
```

Core phục hồi:

```text
HEAD=68e23b8
SERVICE=active
api=online
mqtt=connected
device=online
```

## 3.3. Policy mới

**Không dùng `git clean -fd` trên production.**

Runtime directories phải được provision rõ ràng và deploy script phải đảm bảo tồn tại trước service start.

---

# 4. REPOSITORY & VERSION HISTORY

## 4.1. Canonical platform baseline cũ

Audit canonical ngày 2026-07-23:

- VERSION `0.6.0`
- HEAD `140e159`

Roadmap sau đó tiến hóa:

```text
0.7 Product Reconciliation
0.8 Brain Text Intelligence
0.9 Intelligence Router
1.0 Voice Foundation
1.1 Realtime Voice Engine
```

Một số tài liệu cũ từng gọi 0.9 là Voice; implementation thực tế hiện coi 1.0 là Voice Foundation.

## 4.2. Commit quan trọng

### Phase 0.9 / Intelligence

- `16e642a` — baseline Intelligence Router production.

### Phase 1.0 C1→C9

- `fb73099`
- `8490106`
- `fef6db5`
- `2019276`
- `2ad7af4`
- `fd6b121`
- `ac89a8e`
- `7bd4fdf`
- `ac3aa48`

Hardening:

- `ba82c8a`

### Runtime reconciliation

- `1f72533` — synchronize Phase 1.0 browser runtime
- `a7d09dd` — move speech compute behind Brain boundary
- `92adb4b` — complete runtime reconciliation
- `109b36f` — close runtime acceptance gaps
- `a1e6a9d` — restore frontend runtime initialization
- `78fc043` — normalize speech audio and harden runtime transport

### Real TTS

- `68e23b8` — integrate real Piper TTS runtime
- `058114a` — reject empty Piper audio and use `synthesize_wav`

### STT

- `6cf499d` — configure production Whisper STT runtime

### Latest software closure candidate

- `406371c` — close Phase 1.0 spoken runtime gaps

---

# 5. ALEX CORE — TÌNH TRẠNG NỀN TẢNG

Core là vùng mạnh nhất:

- FastAPI Core.
- SQLite WAL/persistence/audit.
- command lifecycle.
- MQTT abstraction.
- safety boundary.
- capability registry.
- simulator.
- missions/automations backend.
- OTA.
- backup/recovery.
- health.
- watchdog.
- production acceptance.
- SSE.
- authentication/safety logic.

## 5.1. MQTT

Mosquitto runtime đã được xác nhận active.

Principals lịch sử:

- `alex_core`
- `esp01`
- `esp02`

Brain production dependency không được chứa MQTT client.

## 5.2. ESP01 & capability

`esp01` đã tham gia runtime.

`test_led`:

- capability safe;
- từng được dùng cho thử nghiệm điều khiển;
- latest forensic audit có thời điểm command ở `waiting_ack`;
- vì vậy lần audit đó chưa chứng minh `physically_verified`.

`relay_1..relay_4`:

- `restricted`;
- `command_allowed=false`;
- Brain refusal + Core SafetyPolicy đều giữ lockdown;
- zero MQTT mutation khi test restricted action.

---

# 6. PHASE 0.8 / 0.9 — BRAIN TEXT INTELLIGENCE & ROUTER

Brain được tách khỏi Core thành compute node.

Brain service có:

```text
GET  /health
POST /v1/chat
POST /v1/stt
POST /v1/tts
```

Safe tool boundary:

```text
Brain proposes
Core validates
Core decides
Core executes
```

Tool allowlist từng gồm:

- `system_status`
- `list_devices`
- `set_test_led`
- `set_room_mode`
- `run_safe_mission`
- `run_safe_automation`

## 6.1. LLM runtime

Ollama CPU đã chạy:

- `qwen3.5:4b`
- sau đó `qwen3.5:2b`

Text `"Bạn là ai?"` đã chạy thật qua:

```text
Browser
→ Core /api/v1/brain/chat
→ IntelligenceRouter
→ Brain /v1/chat
→ Ollama
→ assistant_text
→ UI
```

Latency quan sát nhiều lần:

```text
~19–23 giây
```

Đây là **nút thắt latency lớn nhất**.

## 6.2. Semantic issue

Greeting `"Xin chào ALEX"` từng bị hiểu thành `system_status` thay vì greeting tự nhiên.

Đã có chỉnh system instruction, nhưng chưa có final acceptance đầy đủ cho mọi greeting.

---

# 7. PHASE 1.0 — VOICE FOUNDATION

Đã xây:

- Voice lifecycle contracts.
- STT boundary.
- FasterWhisper provider.
- Brain `/v1/stt`.
- WebSocket `/api/v1/voice/stream`.
- first-message auth.
- strict Origin.
- chunk/session/duration bounds.
- cancellation/cleanup.
- Voice→IntelligenceRouter integration.
- session supervisor/store.
- browser microphone transport.
- PCM16/WAV contract.
- browser VoiceClient.
- browser playback module.
- TTS boundary và Brain `/v1/tts`.

State backend:

- IDLE
- LISTENING
- TRANSCRIBING
- THINKING
- ACTING
- SPEAKING
- COMPLETED
- CANCELLED
- FAILED
- UNAVAILABLE

---

# 8. FRONTEND/BACKEND SYNC — LỊCH SỬ SỰ CỐ

Forensic audit từng phát hiện frontend/backend lệch nghiêm trọng:

- mic chỉ `getUserMedia + AnalyserNode` để vẽ waveform;
- không gửi audio qua network;
- frontend không có WebSocket Voice client;
- text dùng regex client-side;
- text bypass IntelligenceRouter;
- legacy Phase-2 fallback active;
- Orb có nhiều owner state;
- TTS playback chưa nối;
- Service Worker cache có nguy cơ stale.

Các commit reconciliation:

```text
1f72533
a7d09dd
92adb4b
109b36f
a1e6a9d
78fc043
```

Sau đó browser đã thật sự:

```text
Browser mic
→ WebSocket 101
→ Core
→ Brain STT
```

## 8.1. WebSocket dependency incident

Core từng báo:

```text
Unsupported upgrade request
No supported WebSocket library detected
```

Sau khi cài `websockets 16.1.1`:

```text
HTTP/1.1 101 Switching Protocols
```

Browser→Tailscale→Core Voice WS PASS.


# 9. STT — TÌNH TRẠNG CHI TIẾT

## 9.1. FasterWhisper runtime

Brain đã cài:

- `faster-whisper`
- `ctranslate2`

Service user `alex-brain` load model được.

## 9.2. Audio contract

Browser/Core:

```text
raw PCM16LE
→ Core raw_pcm16le_to_wav
→ WAV 16kHz mono PCM16
→ Brain
```

Brain `raw_pcm16le_to_wav()` đã được xác minh:

- nếu input đã là RIFF/WAVE đúng contract, trả nguyên bytes;
- không double-wrap WAV;
- nếu raw PCM thì mới tạo header.

## 9.3. Benchmark model

### Tiny

Reference `"Bạn là ai?"`:

```text
"Bắt lại ai."
```

Inference khoảng `0.63s`.

Không đủ accuracy.

### Base

Short:

```text
"bạn lại"
```

Long:

```text
"Xin chào ãy, hôm nay bạn có quẻ không."
```

Inference khoảng `1.15–1.45s`.

### Small

Short synthetic:

```text
"Bắt lại ai?"
```

Long synthetic:

```text
"Xin chào á, hôm nay bạn có khỏe không?"
```

Inference khoảng `3.7–4.16s`.

Với **real mic**, small tốt hơn synthetic short benchmark:

- `"một hai ba bốn"` → gần đúng `1, 2, 3, 4`
- `"Bạn là ai? Xin chào"` → gần đúng.

`small` được chọn làm Phase 1.0 candidate.

### Medium

Short:

```text
"Bạn là ai?"
```

đúng.

Nhưng:

- load ~42.94s;
- short inference ~18.82s;
- long ~12.44s;
- available RAM giảm khoảng `1.9 GiB → 462 MiB`;
- swap tăng `36 KiB → 1.4 GiB`.

**Medium bị loại khỏi production trên Brain hiện tại.**

## 9.4. Production STT candidate

```text
ALEX_STT_MODEL=small
ALEX_STT_LANGUAGE=vi
ALEX_STT_DEVICE=cpu
ALEX_STT_COMPUTE_TYPE=int8
```

Commit `6cf499d`:

- environment-driven model/language/device/compute type;
- `condition_on_previous_text=False`;
- singleton model caching;
- no silent fallback to tiny.

## 9.5. Silence hallucination

Trước VAD, browser silence tạo transcript giả:

```text
"Hãy subscribe cho kênh..."
"Xin chào!"
```

Commit `406371c` được báo cáo đã thêm:

- FasterWhisper `vad_filter=True`;
- `ALEX_STT_VAD_ENABLED`;
- `ALEX_STT_VAD_MIN_SILENCE_MS`;
- `no_speech` event;
- bypass Router/Brain/TTS khi không có speech.

**Physical/runtime acceptance sau deploy chưa được ghi nhận.**

---

# 10. TTS — TÌNH TRẠNG CHI TIẾT

## 10.1. Piper đã chạy thật

Brain đã cài:

```text
piper-tts==1.5.0
```

Voice:

```text
vi_VN-vais1000-medium
```

Model:

```text
/var/lib/alex-brain/models/piper/
  vi_VN-vais1000-medium.onnx
  vi_VN-vais1000-medium.onnx.json
```

Direct synthesis as service user đã PASS:

```text
sample_rate = 22050
channels    = 1
sample_width= 2
duration    ≈ 2.1s
file size   ≈ 94 KB
```

## 10.2. Pronunciation ALEX

Raw `"ALEX"` được Piper tiếng Việt phát âm không tự nhiên.

Đã thêm TTS-only normalization:

```text
ALEX / Alex / alex
→ A-lếch
```

Display text vẫn giữ `ALEX`.

## 10.3. Empty WAV bug

Live `/v1/tts` ban đầu trả:

```text
audio_bytes = 44
frames      = 0
duration    = 0
```

Root cause:

```python
self._piper_voice.synthesize(text, wav_out)
```

đã gọi generator nhưng không consume.

Direct API đúng:

```python
voice.synthesize_wav(text, wav_out)
```

Commit `058114a` sửa:

- dùng `synthesize_wav`;
- reject zero-frame WAV;
- `validate_wav_pcm()` yêu cầu frames > 0;
- Brain/Core test không cho 44-byte WAV qua.

## 10.4. Runtime TTS hiện tại

Đã xác minh:

- Piper engine thật: PASS.
- Model thật: PASS.
- Direct Python synth: PASS.
- Software contract sau fix: PASS theo tests.

Chưa xác minh cuối:

- live `/v1/tts` sau fix trả non-empty WAV trên production;
- `speaking` event có real audio;
- Chrome phát audible response ổn định.

**Đây vẫn là acceptance gap.**

---

# 11. VOICE RUNTIME THẬT ĐÃ QUAN SÁT

## 11.1. Browser microphone

Đã thấy real WebSocket frames:

```text
auth_ok
binary audio
end_audio
transcribing
transcript_final
thinking
...
```

Mic permission, capture và WS transport đều đã hoạt động thật.

## 11.2. Brain log

Đã quan sát:

```text
POST /v1/stt  200
POST /v1/chat 200
```

Một số session có:

```text
POST /v1/tts 200
```

nhưng nhiều session không gọi TTS do `assistant_text=""`.

## 11.3. Empty assistant issue

Có session:

```json
{
  "transcript": "Mà là",
  "assistant_text": "",
  "error_code": null,
  "state": "completed"
}
```

Semantic bug:

```text
non-empty transcript
+ no tool
+ empty assistant_text
≠ successful completed conversation
```

Commit `406371c` được báo cáo đã harden:

- `empty_response`;
- không fake completed;
- không fake speaking.

## 11.4. Speaking state không đồng nghĩa audio

Core log từng có:

```text
thinking
→ speaking
→ completed
```

trong vài ms và không có `/v1/tts`.

Điều này chứng minh `"speaking"` trước đây có thể chỉ là visual state, không phải playback thật.

`406371c` được báo cáo đã yêu cầu speaking chỉ khi có real playable audio.

---

# 12. TEXT CONVERSATION

Text path chạy thật:

```text
Browser
→ POST /api/v1/brain/chat
→ IntelligenceRouter
→ Brain /v1/chat
→ Ollama
→ assistant_text
→ UI
```

`"Bạn là ai?"` đã trả natural text kiểu:

> Tôi là ALEX Brain...

Vì vậy:

- Brain LLM không chết;
- IntelligenceRouter path thật;
- vấn đề voice không thể quy hết cho Brain.

## 12.1. UI semantic bug

Ảnh thực tế cho thấy hội thoại thường vẫn có lúc render:

```text
ALEX CORE • SUCCESS
Đã xác nhận
Kết quả có bằng chứng từ reported state
Evidence: CONFIRMED
```

dù đó chỉ là conversation.

Sai semantic:

```text
conversation
≠ action
≠ hardware evidence
```

Future correction cần envelope kiểu:

```text
response_type
execution_status
action_result
evidence
```

---

# 13. FRONTEND / UI HIỆN TẠI — BLOCKER MỚI NHẤT

Mô tả mới nhất:

> nói nhưng ALEX không tự suy nghĩ; bấm vào cũng không trả lời; giao diện có vấn đề.

Đây là trạng thái **chưa chẩn đoán cuối**.

Khả năng mạnh:

1. frontend JS exception;
2. VoiceClient state machine regression;
3. mismatch frontend asset/backend commit;
4. Service Worker/cache stale;
5. browser giữ module `304 Not Modified`;
6. deployment HEAD Core/Brain không đồng bộ `406371c`;
7. state ownership conflict giữa Presence/App/Voice events.

## 13.1. Service Worker/cache

Trước đây có cache key dạng:

```text
alex-nexus-mark3-phase-1.0-v1
```

và asset query:

```text
/static/app.js?v=phase-1.0-v1
```

trong khi code đã thay nhiều lần.

Rủi ro browser giữ JS cũ là có thật.

## 13.2. Diagnostic cần làm trước khi sửa tiếp

- verify Core HEAD;
- verify Brain HEAD;
- verify browser-served asset version/hash;
- inspect F12 Console;
- inspect Voice WebSocket Messages;
- verify no duplicate WS/session;
- verify Service Worker state;
- xác định exact last event khi UI freeze.

**Không sửa backend mù khi chưa biết frontend đang chạy code nào.**

---

# 14. SECURITY & SAFETY

## 14.1. Voice WS

Invariant đã từng xác minh:

- strict Origin;
- exact scheme+host;
- first-message auth;
- auth timeout ~5s;
- API key không nằm trong query;
- chunk max ~512 KiB;
- total session ~5 MiB;
- session duration ~30s;
- cleanup on disconnect;
- close code 1008 cho auth/origin violation.

## 14.2. Brain

Brain `/v1/stt`, `/v1/tts`, `/v1/chat` dùng Brain key.

Comparison dùng constant-time strategy.

Brain dependencies đã được harden để **không chứa MQTT client**.

## 14.3. API key exposure

Một Core API key đã xuất hiện trong screenshot DevTools.

**Action bắt buộc sau khi runtime ổn định: rotate Core API key.**

Không lưu key vào report này.

---

# 15. TESTING

## 15.1. Original Phase 1.0

```text
Python: 1405 passed, 3 skipped
JS:     110 passed
```

## 15.2. Runtime reconciliation

`78fc043`:

```text
Python: 1430 passed, 4 skipped
JS:     116 passed
```

## 15.3. Piper fix

`058114a`:

```text
Focused: 27 passed, 1 skipped
Full:    1436 passed, 4 skipped
JS:      116 passed
```

## 15.4. STT config

`6cf499d`:

```text
Focused: 37 passed, 1 skipped
Full:    1441 passed, 4 skipped
JS:      116 passed
```

## 15.5. Latest closure candidate

`406371c` report:

```text
Python: 1449 passed, 4 skipped
JS:     116 passed
npm run check: PASS
```

Software gates reported PASS:

- silence hallucination software;
- no-speech Brain bypass;
- no-speech TTS bypass;
- STT small regression;
- assistant text contract;
- real TTS audio contract;
- browser playback software;
- relay lockdown;
- Brain no MQTT.

**Automated PASS không thay thế physical/browser acceptance.**

---

# 16. DEPLOYMENT TRUTH — SOURCE KHÁC RUNTIME

## 16.1. Mốc đã xác minh rõ

`78fc043`:

- Local = Core = Brain từng được forensic audit xác minh đồng bộ.

`68e23b8`:

- Core checkout thành công;
- xảy ra namespace incident;
- sau recovery Core:
  `HEAD=68e23b8`, `SERVICE=active`.

Brain tại Piper runtime verify:

- `HEAD=68e23b8`;
- service active;
- Piper model/config readable.

## 16.2. Commit sau

Source:

```text
058114a
6cf499d
406371c
```

đều có software report PASS.

Nhưng transcript hiện tại không có đủ terminal evidence để khẳng định chắc chắn:

```text
Core HEAD = 406371c
Brain HEAD = 406371c
```

**Việc đầu tiên khi quay lại runtime: verify 3 HEAD: Local / Core / Brain.**

---

# 17. CURRENT CAPABILITY MATRIX

| Capability | Software | Runtime real | Physical/User acceptance | Status |
|---|---:|---:|---:|---|
| FastAPI Core | PASS | PASS | PASS | ✅ |
| SQLite production | PASS | PASS | PASS | ✅ |
| MQTT broker | PASS | PASS | PASS | ✅ |
| ESP01 online | PASS | PASS | observed | ✅ |
| SafetyPolicy | PASS | PASS | restricted test | ✅ |
| relay lockdown | PASS | PASS | no mutation | ✅ |
| test_led path | PASS | PASS | latest audit waiting_ack | 🟡 |
| Brain `/health` | PASS | PASS | PASS | ✅ |
| Brain `/v1/chat` | PASS | PASS | text UI works | ✅ |
| IntelligenceRouter | PASS | PASS | text works | ✅ |
| Natural text conversation | PASS | PASS | observed | ✅ |
| Conversation UI semantics | partial | partial | wrong Evidence sometimes | 🟡 |
| Voice WebSocket | PASS | PASS | browser 101/messages | ✅ |
| Mic capture | PASS | PASS | real mic observed | ✅ |
| STT tiny | PASS | poor | poor accuracy | ❌ retired |
| STT base | PASS | benchmark | insufficient | ❌ |
| STT small | PASS | real mic tested | candidate | 🟢 |
| STT medium | PASS | benchmark | too slow/heavy | ❌ rejected |
| VAD/no-speech source | PASS reported | unverified latest | unverified | 🟡 |
| Piper engine | PASS | direct runtime PASS | file audio exists | ✅ |
| Piper `/v1/tts` post-fix | PASS tests | not re-proven live | not heard | 🟡 |
| Browser playback code | PASS tests | unverified latest | no stable audible reply | 🔴 |
| Voice spoken E2E | partial | partial | NOT ACCEPTED | 🔴 |
| Context memory | minimal/none | — | — | ❌ Phase 1.1 |
| Streaming STT | no | — | — | ❌ Phase 1.1 |
| Streaming LLM | no | — | — | ❌ Phase 1.1 |
| Streaming TTS | no | — | — | ❌ Phase 1.1 |
| Smart Turn | no | — | — | ❌ Phase 1.1 |
| Bilingual auto-routing | no | — | — | ❌ Phase 1.1 |
| Robot/JARVIS-like DSP | no | — | — | ❌ Phase 1.1 |


# 18. BLOCKER HIỆN TẠI

## P0 — Frontend/runtime synchronization

Hiện tượng mới nhất:

- nói nhưng UI không tự THINKING;
- bấm mic không luôn xử lý;
- không có reply.

Phải phân biệt:

```text
browser asset
vs
VoiceClient
vs
WebSocket
vs
Core HEAD
vs
Brain HEAD
```

trước khi thêm feature.

## P0 — Spoken E2E chưa PASS

Cần chứng minh một flow:

```text
"Bạn là ai?"
→ transcript_final
→ assistant_text
→ /v1/tts 200
→ non-empty WAV
→ speaking event
→ AudioContext decode
→ audible browser speaker
→ completed
```

## P0 — Silence acceptance sau VAD

Cần chứng minh:

```text
silence
→ no_speech
→ NO /v1/chat
→ NO /v1/tts
→ NO speaking
```

## P1 — API key rotation

Key đã xuất hiện trong screenshot.

Rotate sau khi runtime ổn định.

## P1 — UI conversation semantics

Conversation không được render hardware evidence/confirmed.

## P1 — LLM latency

Local Ollama CPU ~19–23s là quá chậm cho “Jarvis-like realtime”.

---

# 19. PHASE 1.0 — ĐỊNH NGHĨA DONE

Phase 1.0 chỉ được đóng khi qua:

## Gate A — silence

```text
mic start
→ silence
→ no_speech
→ UI neutral
→ idle
```

Không Brain, không TTS.

## Gate B — real speech

```text
mic
→ STT
→ correct-enough transcript
→ Brain
→ non-empty assistant_text
→ Piper
→ speaking with audio
→ browser playback
→ user hears ALEX
```

## Gate C — safety

```text
"Bật relay 1"
→ truthful refusal
→ zero MQTT mutation
```

## Gate D — safe action

```text
"Bật test led"
→ Core SafetyPolicy
→ command lifecycle
→ ACK/reported state if device reports
```

Không fake physical confirmation.

---

# 20. PHASE 1.1 — REALTIME VOICE ENGINE

`docs/PHASE_1_1_REALTIME_VOICE_PLAN.md` đã được tạo theo report `406371c`.

## 20.1. Target architecture

```text
Browser Audio Stream
      ↓
Silero VAD
      ↓
Smart Turn / endpointing
      ↓
Streaming / Partial STT
      ↓
ConversationSession / context
      ↓
Streaming LLM
      ↓
Sentence / clause chunker
      ↓
Streaming TTS
      ↓
Browser Audio Queue
      ↓
Barge-in
```

## 20.2. Candidate cần benchmark/nghiên cứu

- Silero VAD.
- Pipecat.
- Pipecat Smart Turn.
- LiveKit Agents architecture.
- whisper.cpp.
- llama.cpp.
- Piper streaming API.

Không vendor/copy third-party code trước audit license/fit.

## 20.3. Metric latency

Phải đo:

```text
speech_end → transcript_final
transcript_final → first LLM token
first token → first TTS audio
speech_end → first audible response
```

Không dùng “cảm giác nhanh” làm metric.

---

# 21. CONTEXT & MEMORY

Hiện mỗi turn còn quá độc lập.

Phase 1.1/1.2 nên có:

```text
ConversationSession
├── session_id
├── language
├── recent turns
├── rolling summary
├── active entities/references
├── user preferences được phép nhớ
├── current room context
├── pending task
└── authoritative Core tool results
```

Ví dụ:

```text
User: Bật đèn bàn.
ALEX: Đã gửi lệnh...

User: Tắt nó đi.
```

Brain phải hiểu `nó = đèn bàn`, nhưng hardware truth vẫn phải lấy từ Core.

---

# 22. BILINGUAL VI/EN

Phase 1.0 đang dùng:

```text
language=vi
```

Phù hợp acceptance hiện tại nhưng chưa phù hợp mục tiêu dài hạn.

Phase 1.1 nên hỗ trợ:

```text
VI turn → Vietnamese STT/TTS
EN turn → English STT/TTS
```

Cần:

- language detection theo turn;
- hysteresis để không flip language vì một từ;
- TTS voice router theo language;
- giữ cùng personality ALEX.

---

# 23. ROBOT / JARVIS-LIKE VOICE

Mục tiêu hợp lý là tạo chất giọng trợ lý robot tương lai, không clone trực tiếp giọng có bản quyền.

Pipeline dự kiến:

```text
Piper / future TTS
→ EQ
→ compression
→ subtle modulation
→ short metallic delay
→ small reverb
→ limiter
→ browser output
```

Đưa vào Phase 1.1 sau khi playback ổn định.

---

# 24. INTELLIGENCE PERFORMANCE ROADMAP

## 24.1. Nút thắt hiện tại

```text
Ollama + qwen3.5:2b + CPU
≈ 19–23s/request
```

Dù STT nhanh hơn, UX vẫn chậm.

## 24.2. Future local fast path

Benchmark:

```text
llama.cpp
+ quantized small model
+ KV/prompt caching
```

cho:

- greeting;
- identity;
- simple conversation;
- deterministic commands.

## 24.3. Hybrid smart path

Để đạt chất lượng gần ChatGPT/Gemini trên hardware hiện tại:

```text
simple/local
→ fast local model

complex reasoning
→ optional cloud smart model

tool proposal
→ ALWAYS back to Core
→ SafetyPolicy
→ execution
```

Hybrid phải opt-in và không phá local-first/safety.

---

# 25. PRODUCT / UI ROADMAP NGOÀI VOICE

Canonical audit trước AI cho thấy nhiều backend domain còn underexposed.

## Logs

- chuyển sang durable `/api/v1/audit`;
- không chỉ volatile `/api/events`.

## Brain workspace

- online/offline/degraded;
- model/provider;
- latency;
- STT/TTS readiness;
- WOL.

## Automations

Cần:

- list;
- create/update;
- enable/disable;
- manual run;
- last evaluation;
- blocked reason;
- history.

## Missions

- list;
- create/update;
- run;
- per-step progress;
- completed/partial/failed;
- run history.

## Backup UI

- list backups;
- backup now;
- integrity metadata.

Không expose destructive restore quá sớm.

## Scenes

- backend-backed;
- phân biệt logical mode và executable scene;
- không fake steps.

---

# 26. HARDWARE ROADMAP

Mở rộng low-voltage trước:

- temperature/humidity;
- PIR;
- door contact;
- ambient light;
- relay test load an toàn.

Mỗi capability phải có:

```text
registry
→ safe boot
→ safety rule
→ command lifecycle
→ ACK
→ reported state
→ failure test
→ audit
→ physical validation
```

High-risk:

- mains relay;
- pump/motor;
- UV;
- door lock;

phải có:

- interlock;
- sensor prerequisite;
- maximum runtime;
- safe shutdown;
- non-voice-only confirmation khi phù hợp.

---

# 27. ARCHITECTURAL DEBT REGISTER

## Fix/verify now

- frontend/runtime sync.
- Service Worker asset lifecycle.
- no-speech physical acceptance.
- speaking real audio acceptance.
- empty assistant state.
- API key rotation after debug.

## Phase 1.1

- streaming STT.
- partial transcript.
- Smart Turn.
- streaming LLM.
- streaming Piper.
- audio queue.
- barge-in.
- VI/EN auto routing.
- ConversationSession memory.
- latency telemetry.
- robot voice DSP.
- AudioWorklet migration.

## Phase 1.2+

- canonical semantic response envelope:
  - `response_type`
  - `execution_status`
  - `action_result`
  - `evidence`
- hybrid cloud/local intelligence.
- deeper long-term memory.
- advanced tool planning.

## Later product

- camera.
- energy.
- physical security.
- advanced sensors.
- higher-risk hardware.

---

# 28. KNOWN WARNINGS / NON-BLOCKERS

Đã từng quan sát:

- `ScriptProcessorNode` deprecated.
- `aria-hidden` retained-focus warning.
- manifest/icon warning.
- OTA poller 401 noise.
- browser `304 Not Modified`.
- Service Worker cache drift.

Không trộn warning UX với blocker Voice nếu không có evidence trực tiếp.

---

# 29. NGUYÊN TẮC LÀM VIỆC TỪ ĐÂY

Rule đã thống nhất:

> Khi audit phát hiện kiến trúc hiện tại đi sai hướng hoặc desynchronized, không chỉ vá phase đang làm. Phải phân loại thành architectural correction/debt. Chỉ sửa ngay phần trực tiếp chặn runtime hiện tại; refactor rộng hơn đưa vào roadmap phase phù hợp.

Mỗi checkpoint phải phân biệt:

```text
SOFTWARE PASS
RUNTIME PASS
PHYSICAL PASS
```

Không gộp ba mức.

---

# 30. NEXT ACTION PLAN — THỨ TỰ CHÍNH XÁC

## Step 1 — Verify deployment truth

Trên dev/Core/Brain:

```text
git rev-parse --short HEAD
git status --short
systemctl is-active ...
```

Mục tiêu xác nhận:

```text
Local = 406371c
Core  = 406371c
Brain = 406371c
```

hoặc ghi rõ mismatch.

## Step 2 — Diagnose frontend freeze

Browser:

- Disable cache trong DevTools.
- F12 Console.
- Network → Socket.
- kiểm tra Service Worker.
- ghi exact asset query/hash.
- bấm mic một lần.
- xác định last WS event.

Không sửa code trước khi có trace.

## Step 3 — Silence acceptance

```text
silence
→ no_speech
```

No chat, no TTS.

## Step 4 — Spoken E2E

```text
"Bạn là ai?"
→ transcript
→ assistant
→ TTS
→ speaking
→ audible
```

## Step 5 — Rotate exposed Core API key

Sau khi debug session kết thúc.

## Step 6 — Freeze/tag Phase 1.0

Chỉ khi 2 physical tests PASS.

## Step 7 — Start Phase 1.1

Realtime Voice Engine theo plan đã tạo.

---

# 31. CURRENT VERDICT

## Platform/Core

**PASS / production-capable foundation**

Core architecture, persistence, MQTT, safety, backup/recovery, OTA và observability là phần trưởng thành nhất.

## Brain Text Intelligence

**PASS with latency limitations**

Text reasoning và safe tool proposal chạy thật. Latency local CPU còn cao.

## Voice software components

**MOSTLY PASS**

STT/TTS/WS/browser client đã tồn tại thật và có test mạnh.

## Voice real end-to-end

**NOT ACCEPTED YET**

Lý do:

- frontend hiện có dấu hiệu runtime/state regression;
- latest VAD source chưa physical verified;
- real browser speaker response chưa được nghe ổn định;
- deployment HEAD latest chưa được xác nhận đầy đủ.

## Safety

**PASS**

- Core final authority giữ nguyên.
- Brain no MQTT.
- relays locked.
- no intentional bypass.

---

# 32. ĐỊNH NGHĨA MỐC THÀNH CÔNG TIẾP THEO

Mốc tiếp theo không phải “thêm feature”.

Mốc tiếp theo là:

```text
1. mở ALEX
2. bấm mic
3. nói "Bạn là ai?"
4. UI nhận đúng/đủ hiểu
5. ALEX tự THINKING
6. assistant_text xuất hiện
7. ALEX phát tiếng thật từ browser
8. phiên kết thúc sạch
9. silence không hallucinate
```

Khi đó mới ghi:

> **ALEX PHASE 1.0 — REAL SPOKEN END-TO-END ACCEPTANCE PASS**

Sau đó mới bắt đầu xây cảm giác “ChatGPT Voice / Gemini Live / JARVIS-like” bằng Phase 1.1.

---

# 33. NGUỒN BẰNG CHỨNG CHÍNH

Nguồn lịch sử/canonical:

- `ALEX_CANONICAL_PROJECT_REPORT_AND_ROADMAP_2026-07-23.md`
- `ALEX_FULL_PROJECT_AUDIT_2026-07-23.md`
- `PROJECT_PROGRESS_AND_ROADMAP.md`
- `step_2_1_audit.md`
- `ALEXROOM_CODEX_MASTER_PROMPT.txt`
- `ALEX_ROOM_OS_KE_HOACH_THAM_DINH*.md`

Runtime forensic/report:

- `ALEX PHASE 1.0 — REAL RUNTIME FORENSIC ACCEPTANCE REPORT`
- `ALEX CURRENT UI / BACKEND SYNCHRONIZATION AUDIT`
- Brain/Core journal logs
- `/v1/stt`, `/v1/chat`, `/v1/tts` tests
- browser WebSocket DevTools screenshots
- Piper direct API tests
- FasterWhisper tiny/base/small/medium benchmark
- Codex reports cho `68e23b8`, `058114a`, `6cf499d`, `406371c`

---

# 34. SOURCE-OF-TRUTH POLICY

Tài liệu cũ trước Phase 0.8 có thể nói “AI/Voice chưa implement”. Điều đó đúng ở thời điểm audit cũ nhưng **không còn đúng hiện tại**.

Thứ tự ưu tiên:

```text
1. live runtime evidence
2. deployed Git HEAD + service state
3. current source/tests
4. current Phase reports
5. old canonical audits
6. old roadmap/spec
```

Nếu tài liệu và live runtime mâu thuẫn, **live runtime thắng**.

---

# END OF REPORT
