from __future__ import annotations

import json
import hashlib
import hmac
import os
import asyncio
import queue
import shutil
import socket
import subprocess
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from alex_store import AlexStore, utc_now
from alex_hardware import (
    ACK_TOPIC, COMMAND_TOPIC, HEARTBEAT_TOPIC, REPORTED_TOPIC, STATUS_TOPIC, TELEMETRY_TOPIC,
    CommandService, RealtimeHub,
)
from alex_simulator import Esp01Simulator
from alex_orchestration import AutomationExecutor, AutomationScheduler, MissionExecutor
from alex_brain import BrainService
from alex_safety import CapabilityRegistry, CommandGateway, GatewayResult, SafetyDecision, SafetyPolicy


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config.json"
DATABASE_PATH = Path(os.getenv("ALEX_DATABASE_PATH", str(BASE_DIR / "data" / "alex.db")))

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "alex_core")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "").strip()
ALEX_API_KEY = os.getenv("ALEX_API_KEY", "")
ALEX_SIMULATOR = os.getenv("ALEX_SIMULATOR", "0").lower() in {"1", "true", "yes"}
ALEX_SIMULATOR_SCENARIO = os.getenv("ALEX_SIMULATOR_SCENARIO", "normal")
MUTATION_RATE_LIMIT = int(os.getenv("ALEX_MUTATION_RATE_LIMIT", "30"))
BRAIN_MAC = os.getenv("ALEX_BRAIN_MAC")
BRAIN_HOST = os.getenv("ALEX_BRAIN_HOST")
BRAIN_PORT = int(os.getenv("ALEX_BRAIN_PORT", "22"))

DEVICE_ID = "esp01"
TOPIC_PREFIX = f"alex/device/{DEVICE_ID}"

if not MQTT_PASSWORD:
    raise RuntimeError("Thiếu biến môi trường MQTT_PASSWORD")

if not ALEX_API_KEY:
    raise RuntimeError("Thiếu biến môi trường ALEX_API_KEY")


DEFAULT_CONFIG = {
    "room_name": "Phòng của Việt Anh",
    "relay_names": {
        "1": "Relay 1",
        "2": "Relay 2",
        "3": "Relay 3",
        "4": "Relay 4",
    },
    "relay_subtitles": {
        "1": "D1 / GPIO5",
        "2": "D2 / GPIO4",
        "3": "D5 / GPIO14",
        "4": "D6 / GPIO12",
    },
}

mqtt_connected = threading.Event()
state_lock = threading.Lock()
event_lock = threading.Lock()
store_ready = threading.Event()
store = AlexStore(DATABASE_PATH)
realtime_hub = RealtimeHub()
simulator: Esp01Simulator | None = None

device_state: dict[str, Any] = {
    "device_id": DEVICE_ID,
    "availability": "unknown",
    "last_seen": None,
    "relays": {
        "1": "UNKNOWN",
        "2": "UNKNOWN",
        "3": "UNKNOWN",
        "4": "UNKNOWN",
    },
    "mode": "home",
}

events: deque[dict[str, Any]] = deque(maxlen=80)
mutation_times: deque[float] = deque()
mutation_lock = threading.Lock()


def default_mqtt_client_id() -> str:
    """Return a short process-unique ID so parallel previews cannot evict each other."""
    identity = f"{socket.gethostname()}:{os.getpid()}".encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:10]
    return f"alex-core-{suffix}"


class ConfigUpdate(BaseModel):
    room_name: str = Field(min_length=1, max_length=60)
    relay_names: dict[str, str]


class ModeRequest(BaseModel):
    mode: str


class V1CommandRequest(BaseModel):
    node_id: str = "esp01"
    target: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Retained only for wire compatibility. SafetyPolicy never consumes this value.
    risk_level: str = "safe"
    origin: str = "user"


class DomainRecordRequest(BaseModel):
    body: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_event(
    kind: str,
    message: str,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    with event_lock:
        events.appendleft(
            {
                "time": utc_now_iso(),
                "kind": kind,
                "message": message,
                "level": level,
                "details": details,
            }
        )
    if store_ready.is_set():
        try:
            store.add_audit(kind, message, level, details=details)
        except Exception as error:
            print(f"SQLite audit write failed: {error}")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)

    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_CONFIG)
        merged.update(loaded)
        merged["relay_names"] = {
            **DEFAULT_CONFIG["relay_names"],
            **loaded.get("relay_names", {}),
        }
        merged["relay_subtitles"] = {
            **DEFAULT_CONFIG["relay_subtitles"],
            **loaded.get("relay_subtitles", {}),
        }
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> None:
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(CONFIG_PATH)


def require_api_key(x_alex_key: str | None = Header(default=None)) -> None:
    if x_alex_key is None or not hmac.compare_digest(x_alex_key, ALEX_API_KEY):
        raise HTTPException(status_code=401, detail="Sai mã điều khiển")


def require_mutation_budget(_: None = Depends(require_api_key)) -> None:
    """Bound local mutations to limit accidental command/config floods."""
    import time

    now = time.monotonic()
    with mutation_lock:
        while mutation_times and now - mutation_times[0] >= 60:
            mutation_times.popleft()
        if len(mutation_times) >= MUTATION_RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Quá nhiều thao tác; thử lại sau")
        mutation_times.append(now)


def _gateway_response_or_denied(result: GatewayResult) -> dict[str, Any]:
    if result.decision.allowed:
        return result.as_dict()
    decision = result.decision.as_dict()
    raise HTTPException(status_code=423, detail=decision)


def _record_safety_denial(decision: SafetyDecision) -> None:
    details = {
        "node": decision.node_id,
        "capability": decision.capability_id,
        "action": decision.action,
        "status": decision.verification_status,
        "risk": decision.risk_level,
        "reason": decision.reason,
        "execution_mode": decision.execution_mode,
    }
    add_event(
        "safety_denial",
        f"Đã chặn {decision.node_id}/{decision.capability_id}/{decision.action}: {decision.reason}",
        "warning",
        details,
    )


def _publish_v1_command(topic: str, payload: str, qos: int, retain: bool) -> bool:
    if topic != COMMAND_TOPIC:
        add_event("safety", f"Transport từ chối topic ngoài command V1: {topic}", "warning")
        return False
    if simulator is not None:
        return simulator.publish(topic, payload, qos, retain)
    if not mqtt_connected.is_set():
        return False
    result = mqtt_client.publish(topic, payload, qos=qos, retain=retain)
    return result.rc == mqtt.MQTT_ERR_SUCCESS


capability_registry = CapabilityRegistry()
safety_policy = SafetyPolicy(capability_registry, simulator_mode=ALEX_SIMULATOR)
command_service = CommandService(store, _publish_v1_command, realtime_hub, simulator_mode=ALEX_SIMULATOR)
command_gateway = CommandGateway(safety_policy, command_service, on_denied=_record_safety_denial)
mission_executor = MissionExecutor(store, command_gateway)
automation_executor = AutomationExecutor(store, mission_executor, command_gateway)
automation_scheduler = AutomationScheduler(store, automation_executor, realtime_hub)
brain_service = BrainService(store, realtime_hub, BRAIN_MAC, BRAIN_HOST, BRAIN_PORT)


def _with_command_verification(command: dict[str, Any]) -> dict[str, Any]:
    node_id = str(command.get("node_id", "unknown")).lower()
    capability_id = str(command.get("target", "unknown")).lower()
    node_truth = capability_registry.get_node_status(node_id)
    capability_truth = capability_registry.list_capabilities(node_id).get(capability_id)
    node_summary = (
        {
            "node_id": node_truth["node_id"],
            "verification_status": node_truth["verification_status"],
            "hardware_verified": node_truth["hardware_verified"],
        }
        if node_truth is not None
        else {
            "node_id": node_id,
            "verification_status": "unknown",
            "hardware_verified": None,
        }
    )
    return {
        **command,
        "verification": {
            "node": node_summary,
            "capability": capability_truth,
        },
    }


def on_connect(
    client: mqtt.Client,
    userdata: Any,
    flags: Any,
    reason_code: Any,
    properties: Any = None,
) -> None:
    if reason_code == 0:
        mqtt_connected.set()
        client.subscribe(f"{TOPIC_PREFIX}/availability")
        client.subscribe(f"{TOPIC_PREFIX}/switch/+/state")
        client.subscribe(ACK_TOPIC, qos=1)
        client.subscribe(REPORTED_TOPIC, qos=1)
        client.subscribe(HEARTBEAT_TOPIC, qos=1)
        client.subscribe(TELEMETRY_TOPIC, qos=0)
        client.subscribe(STATUS_TOPIC, qos=1)
        add_event("mqtt", "Alex Core đã kết nối MQTT", "success")
        print("MQTT connected")
    else:
        mqtt_connected.clear()
        add_event("mqtt", f"MQTT kết nối thất bại: {reason_code}", "error")
        print(f"MQTT connection failed: {reason_code}")


def on_disconnect(
    client: mqtt.Client,
    userdata: Any,
    disconnect_flags: Any = None,
    reason_code: Any = None,
    properties: Any = None,
) -> None:
    mqtt_connected.clear()
    if not ALEX_SIMULATOR:
        command_service.mark_degraded()
    add_event("mqtt", f"MQTT đã ngắt kết nối: {reason_code}", "warning")
    print(f"MQTT disconnected: {reason_code}")


def on_message(
    client: mqtt.Client,
    userdata: Any,
    message: mqtt.MQTTMessage,
) -> None:
    topic = message.topic
    payload = message.payload.decode("utf-8", errors="replace").strip()

    if topic in {ACK_TOPIC, REPORTED_TOPIC, HEARTBEAT_TOPIC, TELEMETRY_TOPIC, STATUS_TOPIC}:
        try:
            document = json.loads(payload)
        except json.JSONDecodeError:
            add_event("mqtt_protocol", f"Bỏ qua JSON không hợp lệ trên {topic}", "warning")
            return
        message_source = "simulated" if document.get("source") == "simulated" else "mqtt"
        if message_source == "simulated" and not ALEX_SIMULATOR:
            add_event("safety", f"Bỏ qua simulated message trong hardware mode: {topic}", "warning")
            return
        if topic == ACK_TOPIC:
            command_service.handle_ack(document, message_source)
        elif topic == REPORTED_TOPIC:
            command_service.handle_reported(document, message_source)
        elif topic == HEARTBEAT_TOPIC:
            command_service.handle_heartbeat(document, message_source)
        elif topic == STATUS_TOPIC and document.get("online") is False:
            command_service.mark_offline()
        else:
            realtime_hub.emit("telemetry", document, message_source)
        return

    with state_lock:
        device_state["last_seen"] = utc_now_iso()

        if topic == f"{TOPIC_PREFIX}/availability":
            old = device_state["availability"]
            device_state["availability"] = payload.lower()
            if old != device_state["availability"]:
                add_event(
                    "device",
                    f"ESP01 chuyển sang {device_state['availability']}",
                    "success" if payload.lower() == "online" else "warning",
                )

        for relay_id in range(1, 5):
            relay_topic = f"{TOPIC_PREFIX}/switch/relay_{relay_id}/state"
            if topic == relay_topic:
                device_state["relays"][str(relay_id)] = payload.upper()
                break


try:
    mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID or default_mqtt_client_id(),
    )
except AttributeError:
    mqtt_client = mqtt.Client(client_id=MQTT_CLIENT_ID or default_mqtt_client_id())

mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    global simulator
    store.migrate()
    if not store.records("scenes"):
        for scene_id in ("home", "study", "sleep", "away"):
            store.put_record("scenes", scene_id, {
                "name": scene_id.title(), "safety_level": "safe",
                "steps": [], "execution": "backend_mode_contract",
            })
    store_ready.set()
    add_event("system", "Alex Core khởi động", "success")
    mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
    mqtt_client.loop_start()
    command_service.start()
    automation_scheduler.start()
    if ALEX_SIMULATOR:
        simulator = Esp01Simulator(
            command_service.handle_heartbeat,
            command_service.handle_ack,
            command_service.handle_reported,
            scenario=ALEX_SIMULATOR_SCENARIO,
        )
        simulator.start()

    yield

    if simulator is not None:
        simulator.stop()
        simulator = None
    automation_scheduler.stop()
    command_service.stop()
    mqtt_client.disconnect()
    mqtt_client.loop_stop()
    store_ready.clear()


app = FastAPI(
    title="Alex Core API",
    version="0.3.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
    )


@app.get("/api/info")
def info() -> dict[str, str]:
    return {
        "name": "Alex Room",
        "version": "0.3.0",
        "status": "running",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    with state_lock:
        availability = device_state["availability"]
        last_seen = device_state["last_seen"]

    return {
        "api": "online",
        "mqtt": "connected" if mqtt_connected.is_set() else "disconnected",
        "device": availability,
        "last_seen": last_seen,
    }


@app.get("/api/auth/verify")
def verify_auth(_: None = Depends(require_api_key)) -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return load_config()


@app.put("/api/config")
def update_config(
    payload: ConfigUpdate,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    current = load_config()
    relay_names = dict(current["relay_names"])

    for relay_id in {"1", "2", "3", "4"}:
        value = payload.relay_names.get(relay_id, relay_names[relay_id]).strip()
        relay_names[relay_id] = value[:40] or relay_names[relay_id]

    updated = {
        **current,
        "room_name": payload.room_name.strip()[:60],
        "relay_names": relay_names,
    }
    save_config(updated)
    add_event("config", "Đã cập nhật tên phòng và thiết bị", "success")
    return updated


@app.get("/api/devices/esp01")
def get_esp01() -> dict[str, Any]:
    registry_truth = capability_registry.get_node_status(DEVICE_ID)
    if registry_truth is None:
        raise HTTPException(status_code=503, detail="ESP01 chưa có trong capability registry")
    with state_lock:
        return {
            "device_id": device_state["device_id"],
            "availability": device_state["availability"],
            "last_seen": device_state["last_seen"],
            "mode": device_state["mode"],
            "relays": dict(device_state["relays"]),
            **registry_truth,
        }


@app.get("/api/system")
def system_metrics() -> dict[str, Any]:
    mem_total = 0
    mem_available = 0

    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1]) * 1024
    except OSError:
        pass

    disk = shutil.disk_usage("/")
    uptime_seconds = 0.0

    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        pass

    temperature = None
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        temperature = round(int(raw) / 1000, 1)
    except (OSError, ValueError):
        pass

    tailscale_ip = None
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        tailscale_ip = result.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        load_average = list(os.getloadavg())
    except (AttributeError, OSError):
        # Windows preview không có os.getloadavg(); Orange Pi/Linux vẫn dùng số thật.
        load_average = [0.0, 0.0, 0.0]

    return {
        "memory": {
            "total": mem_total,
            "used": max(mem_total - mem_available, 0),
            "percent": round(
                ((mem_total - mem_available) / mem_total) * 100,
                1,
            ) if mem_total else 0,
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "percent": round((disk.used / disk.total) * 100, 1),
        },
        "load": load_average,
        "uptime_seconds": uptime_seconds,
        "temperature_c": temperature,
        "tailscale_ip": tailscale_ip,
    }


@app.get("/api/events")
def get_events() -> dict[str, Any]:
    with event_lock:
        return {"items": list(events)}


@app.post("/api/devices/esp01/relays/{relay_id}/{action}")
def control_relay(
    relay_id: int,
    action: str,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    if relay_id not in {1, 2, 3, 4}:
        raise HTTPException(
            status_code=400,
            detail="relay_id chỉ được từ 1 đến 4",
        )

    action = action.upper()
    if action not in {"ON", "OFF"}:
        raise HTTPException(
            status_code=400,
            detail="action chỉ được là ON hoặc OFF",
        )

    result = command_gateway.request(
        node_id=DEVICE_ID,
        capability_id=f"relay_{relay_id}",
        action=action,
        payload={},
        origin="legacy_api",
    )
    return _gateway_response_or_denied(result)


@app.post("/api/devices/esp01/relays-all/{action}")
def control_all_relays(
    action: str,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    action = action.upper()

    if action not in {"ON", "OFF"}:
        raise HTTPException(
            status_code=400,
            detail="action chỉ được là ON hoặc OFF",
        )

    decisions = command_gateway.authorize_batch(
        (DEVICE_ID, f"relay_{relay_id}", action) for relay_id in range(1, 5)
    )
    if not all(decision.allowed for decision in decisions):
        raise HTTPException(
            status_code=423,
            detail={
                "allowed": False,
                "reason": "batch_contains_denied_capability",
                "decisions": [decision.as_dict() for decision in decisions],
            },
        )
    raise HTTPException(status_code=501, detail="Không có relay transport nào được phép")


@app.post("/api/modes")
def set_mode(
    payload: ModeRequest,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    mode = payload.mode.lower()
    allowed = {"home", "away", "sleep", "study"}

    if mode not in allowed:
        raise HTTPException(status_code=400, detail="Chế độ không hợp lệ")

    with state_lock:
        device_state["mode"] = mode

    add_event("mode", f"Đã cập nhật room mode logic: {mode}; không gửi relay", "success")
    return {
        "accepted": True,
        "mode": mode,
        "logical_mode_updated": True,
        "physical_actions": [],
        "physical_result": "not_requested_restricted_capabilities",
    }


@app.get("/api/v1/status")
def v1_status() -> dict[str, Any]:
    node_truth = capability_registry.get_node_status(DEVICE_ID)
    if node_truth is None:
        raise HTTPException(status_code=503, detail="ESP01 chưa có trong capability registry")
    return {
        "api_version": "1",
        "source": "simulated" if ALEX_SIMULATOR else "local_software",
        "simulator": ALEX_SIMULATOR,
        "database": store.health(),
        "mqtt": "connected" if mqtt_connected.is_set() else "disconnected",
        "node": node_truth,
        "safety_policy": "central_gateway",
    }


@app.get("/api/v1/safety/capabilities")
def v1_safety_capabilities() -> dict[str, Any]:
    return {
        "source": "server_authoritative",
        "execution_mode": safety_policy.execution_mode,
        "nodes": capability_registry.public_snapshot(),
    }


@app.get("/api/v1/devices")
def v1_devices() -> dict[str, Any]:
    node_truth = capability_registry.get_node_status(DEVICE_ID)
    if node_truth is None:
        raise HTTPException(status_code=503, detail="ESP01 chưa có trong capability registry")
    v1_device = {**command_service.device(), **node_truth}
    with state_lock:
        esp = {
            "id": DEVICE_ID,
            "name": "ESP01",
            "connection": device_state["availability"],
            "reported_state": {"relays": dict(device_state["relays"])},
            "desired_state": None,
            "last_seen_at": device_state["last_seen"],
            "source": "mqtt_reported_state",
            **node_truth,
        }
    return {"items": [v1_device, esp], "simulator": ALEX_SIMULATOR}


@app.post("/api/v1/commands")
def v1_command(
    payload: V1CommandRequest,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    try:
        result = command_gateway.request(
            node_id=payload.node_id,
            capability_id=payload.target,
            action=payload.action,
            payload=payload.payload,
            origin=payload.origin,
        )
    except RuntimeError as error:
        if str(error) == "esp01_offline":
            raise HTTPException(status_code=409, detail="ESP01 chưa ONLINE; command không được gửi") from error
        raise
    response = _gateway_response_or_denied(result)
    command = response.get("command")
    if command is None:
        raise HTTPException(status_code=500, detail="Gateway không tạo command")
    return {
        **_with_command_verification(command),
        "safety_decision": response["decision"],
        "simulated": ALEX_SIMULATOR,
    }


@app.get("/api/v1/commands")
def v1_commands(limit: int = 50) -> dict[str, Any]:
    return {
        "items": [_with_command_verification(command) for command in command_service.recent_commands(limit)],
        "source": "sqlite",
    }


@app.get("/api/v1/commands/{command_id}")
def v1_command_detail(command_id: str) -> dict[str, Any]:
    command = command_service.command(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Command không tồn tại")
    return {**_with_command_verification(command), "events": store.command_events(command_id)}


@app.post("/api/v1/commands/{command_id}/cancel")
def v1_cancel_command(command_id: str, _: None = Depends(require_mutation_budget)) -> dict[str, Any]:
    command = command_service.cancel(command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="Command không tồn tại")
    return {
        **_with_command_verification(command),
        "note": "MQTT đã phát không thể bị thu hồi; ACK/reported muộn không tạo success",
    }


@app.get("/api/v1/realtime")
async def v1_realtime() -> StreamingResponse:
    async def stream():
        subscriber = realtime_hub.subscribe()
        try:
            yield "retry: 1000\n\n"
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 15)
                    yield f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            realtime_hub.unsubscribe(subscriber)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/automations/{automation_id}/run")
def v1_run_automation(
    automation_id: str,
    trigger: dict[str, Any],
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    rule = store.get_record("automations", automation_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Automation không tồn tại")
    result = automation_executor.evaluate(rule, trigger)
    realtime_hub.emit("automation_evaluated", result, str(rule.get("source", "local_software")))
    return result


@app.post("/api/v1/missions/{mission_id}/run")
def v1_run_mission(mission_id: str, _: None = Depends(require_mutation_budget)) -> dict[str, Any]:
    definition = store.get_record("missions", mission_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Mission không tồn tại")
    result = mission_executor.run(definition, "user")
    realtime_hub.emit("mission_completed", result, str(definition.get("source", "local_software")))
    return result


@app.get("/api/v1/audit")
def v1_audit(limit: int = 80) -> dict[str, Any]:
    return {"items": store.recent_audit(limit), "source": "sqlite"}


@app.get("/api/v1/brain")
def v1_brain() -> dict[str, Any]:
    return brain_service.status()


@app.post("/api/v1/brain/wake")
def v1_brain_wake(_: None = Depends(require_mutation_budget)) -> dict[str, Any]:
    try:
        return brain_service.wake()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail="ALEX Brain chưa cấu hình MAC/host") from error


@app.post("/api/v1/backup")
def v1_backup(_: None = Depends(require_mutation_budget)) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BASE_DIR / "backups" / f"alex-{stamp}.db"
    store.backup(destination)
    store.add_audit("backup", f"Created {destination.name}", "success")
    return {"created": True, "file": destination.name, "source": "local_software"}


@app.put("/api/v1/{domain}/{record_id}")
def v1_put_domain(
    domain: str,
    record_id: str,
    payload: DomainRecordRequest,
    _: None = Depends(require_mutation_budget),
) -> dict[str, Any]:
    allowed = {"scenes", "missions", "automations", "settings"}
    if domain not in allowed:
        raise HTTPException(status_code=404, detail="Domain không tồn tại")
    if not record_id or len(record_id) > 80:
        raise HTTPException(status_code=400, detail="record_id không hợp lệ")
    store.put_record(domain, record_id, payload.body)
    store.add_audit(domain, f"Updated {record_id}", "success")
    return {"saved": True, "domain": domain, "id": record_id, "source": "local_software"}


@app.get("/api/v1/{domain}")
def v1_domain(domain: str) -> dict[str, Any]:
    allowed = {"scenes", "missions", "mission_runs", "automations", "settings"}
    if domain not in allowed:
        raise HTTPException(status_code=404, detail="Domain không tồn tại")
    return {"items": store.records(domain), "source": "local_software"}
