from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time
import uuid
from collections import OrderedDict

import paho.mqtt.client as mqtt


ROOT = "alex/v1/nodes/esp01"
COMMAND = f"{ROOT}/command"
ACK = f"{ROOT}/ack"
REPORTED = f"{ROOT}/reported"
HEARTBEAT = f"{ROOT}/heartbeat"
STATUS = f"{ROOT}/status"

parser = argparse.ArgumentParser(description="Explicit MQTT V1 ESP01 simulator")
parser.add_argument("--scenario", choices=["normal", "missing_ack", "wrong_reported_state", "delayed_ack", "duplicate_message"], default="normal")
args = parser.parse_args()

host = os.getenv("MQTT_HOST", "127.0.0.1")
port = int(os.getenv("MQTT_PORT", "1883"))
username = os.getenv("MQTT_USERNAME", "alex_core")
password = os.getenv("MQTT_PASSWORD", "")
if not password:
    raise SystemExit("MQTT_PASSWORD is required")

recent: OrderedDict[str, bool] = OrderedDict()
led_on = False
started = time.monotonic()
running = True


def now_ms() -> int:
    return int(time.time() * 1000)


def publish_heartbeat(client: mqtt.Client) -> None:
    client.publish(HEARTBEAT, json.dumps({
        "protocolVersion": 1, "nodeId": "esp01", "online": True,
        "uptime": int(time.monotonic() - started), "rssi": -41,
        "firmware": "mqtt-sim-1.0.0", "ip": "simulated",
        "timestamp": now_ms(), "source": "simulated",
    }), qos=0)


def publish_result(client: mqtt.Client, command_id: str, value: bool, status: str = "accepted") -> None:
    client.publish(ACK, json.dumps({
        "protocolVersion": 1, "commandId": command_id, "nodeId": "esp01",
        "status": status, "timestamp": now_ms(), "source": "simulated",
    }), qos=1)
    client.publish(REPORTED, json.dumps({
        "protocolVersion": 1, "nodeId": "esp01", "target": "test_led",
        "state": {"on": value}, "commandId": command_id,
        "timestamp": now_ms(), "source": "simulated",
    }), qos=1, retain=True)


def on_connect(client, userdata, flags, reason_code, properties=None):
    del userdata, flags, properties
    if reason_code != 0:
        print(f"MQTT simulator connection failed: {reason_code}", flush=True)
        return
    client.subscribe(COMMAND, qos=1)
    client.publish(STATUS, json.dumps({"protocolVersion": 1, "nodeId": "esp01", "online": True, "source": "simulated"}), qos=1, retain=True)
    publish_heartbeat(client)
    print(f"MQTT simulator online: scenario={args.scenario}", flush=True)


def on_message(client, userdata, message):
    del userdata
    global led_on
    try:
        command = json.loads(message.payload)
    except json.JSONDecodeError:
        return
    command_id = str(command.get("commandId", ""))
    if command_id in recent:
        publish_result(client, command_id, recent[command_id], "duplicate")
        return
    if args.scenario == "missing_ack":
        return
    if args.scenario == "delayed_ack":
        time.sleep(1)
    desired = bool(command.get("value"))
    led_on = not desired if args.scenario == "wrong_reported_state" else desired
    recent[command_id] = led_on
    while len(recent) > 12:
        recent.popitem(last=False)
    publish_result(client, command_id, led_on)
    if args.scenario == "duplicate_message":
        publish_result(client, command_id, led_on, "duplicate")
    print(f"{command_id}: test_led={led_on} source=simulated", flush=True)


try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"alex-mqtt-sim-{socket.gethostname()}-{uuid.uuid4().hex[:6]}")
except AttributeError:
    client = mqtt.Client(client_id=f"alex-mqtt-sim-{uuid.uuid4().hex[:6]}")
client.username_pw_set(username, password)
client.reconnect_delay_set(1, 30)
client.will_set(STATUS, json.dumps({"protocolVersion": 1, "nodeId": "esp01", "online": False, "source": "simulated"}), qos=1, retain=True)
client.on_connect = on_connect
client.on_message = on_message


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
client.connect(host, port, 30)
client.loop_start()
try:
    while running:
        publish_heartbeat(client)
        time.sleep(5)
finally:
    client.publish(STATUS, json.dumps({"protocolVersion": 1, "nodeId": "esp01", "online": False, "source": "simulated"}), qos=1, retain=True)
    client.disconnect()
    client.loop_stop()
