import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

# Safe observation script for ALEX Phase 7 hardware acceptance.
# DO NOT include relay publishing or dangerous commands.

HTTP_BASE = "http://127.0.0.1:8000"
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
NODE_ID = "esp01"

REPORT_DIR = os.path.join("report", "hardware-acceptance")

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def fetch_health():
    try:
        req = urllib.request.Request(f"{HTTP_BASE}/health")
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode())
    except Exception as e:
        return {"error": str(e)}

def fetch_devices():
    try:
        req = urllib.request.Request(f"{HTTP_BASE}/api/v1/devices")
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.loads(res.read().decode())
    except Exception as e:
        return {"error": str(e)}

class Harness:
    def __init__(self, mode, execute_safe):
        self.mode = mode
        self.execute_safe = execute_safe
        
        # Use Paho MQTT API v2 to resolve deprecation warnings
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"alex-harness-{int(time.time())}")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        username = os.environ.get("MQTT_USERNAME", "alex_core")
        password = os.environ.get("MQTT_PASSWORD")
        if password:
            self.client.username_pw_set(username, password)
            
        self.events = []
        self.started_at = utc_now_iso()
        self.state = {
            "heartbeats": 0,
            "last_heartbeat": None,
            "last_status": None,
            "status_online_count": 0,
            "status_offline_count": 0,
            "recovery_time": None
        }
        self.done = False
        self.connected_once = False

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            if not self.connected_once:
                print("[MQTT] Connected to broker")
                self.connected_once = True
            self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/status")
            self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/heartbeat")
            self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/reported")
            self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/ack")
        else:
            print(f"[MQTT] Connect failed with reason code {reason_code}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return
        
        now = time.time()
        
        if topic.endswith("/heartbeat"):
            self.state["heartbeats"] += 1
            self.state["last_heartbeat"] = now
            print(f"[{utc_now_iso()}] HEARTBEAT received")
            
        elif topic.endswith("/status"):
            online = payload.get("online")
            self.state["last_status"] = online
            if online:
                self.state["status_online_count"] += 1
                print(f"[{utc_now_iso()}] STATUS: ONLINE")
            else:
                self.state["status_offline_count"] += 1
                print(f"[{utc_now_iso()}] STATUS: OFFLINE")
                
        self.events.append({
            "time": utc_now_iso(),
            "monotonic": now,
            "topic": topic,
            "payload": payload
        })

    def run_baseline(self):
        print("=== BASELINE CHECK ===")
        health = fetch_health()
        print(f"Health API: {json.dumps(health)}")
        
        devices = fetch_devices()
        esp = None
        if "items" in devices:
            for item in devices["items"]:
                # TASK 1: Canonical V1 device selection by node_id
                if item.get("node_id") == NODE_ID:
                    esp = item
                    break
                    
        print(f"Device: {json.dumps(esp)}")
        
        # Connect and observe
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()
        print("Waiting up to 12 seconds for a heartbeat...")
        time.sleep(12)
        self.client.loop_stop()
        self.client.disconnect()
        
        # TASK 4 & 5: Baseline Pass Rules
        reasons = []
        
        if health.get("api") != "online":
            reasons.append("Health API is not online")
        if health.get("mqtt") != "connected":
            reasons.append("Health MQTT is not connected")
            
        if not esp:
            reasons.append("Canonical ESP01 record missing")
        else:
            if esp.get("node_id") != NODE_ID:
                reasons.append("Device node_id mismatch")
            if esp.get("connection") != "online":
                reasons.append("Device connection is not online")
            if not esp.get("firmware"):
                reasons.append("Device firmware is empty")
            if esp.get("hardware_verified") is not False:
                reasons.append("hardware_verified must be false")
                
            caps = esp.get("capabilities", {})
            test_led = caps.get("test_led", {})
            if test_led.get("verification_status") != "basic_physical_validated" or not test_led.get("command_allowed"):
                reasons.append("test_led permissions invalid")
                
            for r in ["relay_1", "relay_2", "relay_3", "relay_4"]:
                rc = caps.get(r, {})
                if rc.get("verification_status") != "restricted" or rc.get("command_allowed") is not False:
                    reasons.append(f"{r} safety truth invalid")

        if self.state["heartbeats"] < 1:
            reasons.append("No heartbeat observed within timeout")
            
        is_pass = len(reasons) == 0
        
        result_str = "PHYSICAL_PASS" if is_pass else "FAIL"
        self.save_report("baseline_check", esp, health, result_str)
        
        if is_pass:
            print("BASELINE PASS")
            sys.exit(0)
        else:
            print("BASELINE FAIL")
            for r in reasons:
                print(f" - {r}")
            sys.exit(1)

    def run_watch_recovery(self):
        print("=== WATCH RECOVERY ===")
        print("Please manually disconnect Wi-Fi or power-cycle the ESP.")
        print("Waiting for ONLINE -> OFFLINE -> ONLINE transition...")
        
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()
        
        phase = "wait_initial_online"
        t0 = time.time()
        
        offline_detection_time = None
        online_restoration_time = None
        last_heartbeat_before_loss = None
        first_heartbeat_after_recovery = None
        
        try:
            while True:
                time.sleep(1)
                
                # Fetch authoritative status from API, not just MQTT status topic
                devices = fetch_devices()
                is_online = False
                esp = None
                if "items" in devices:
                    for item in devices["items"]:
                        if item.get("node_id") == NODE_ID:
                            esp = item
                            is_online = (item.get("connection") == "online")
                            break
                
                if phase == "wait_initial_online":
                    if is_online:
                        print("Initial state: ONLINE")
                        phase = "wait_offline"
                elif phase == "wait_offline":
                    if not is_online:
                        offline_detection_time = time.time()
                        last_heartbeat_before_loss = self.state["last_heartbeat"]
                        print(f"[{utc_now_iso()}] ALEX API reported OFFLINE")
                        self.state["heartbeats"] = 0 # reset to track first heartbeat after
                        phase = "wait_recovery"
                elif phase == "wait_recovery":
                    if is_online:
                        online_restoration_time = time.time()
                        recovery_time = online_restoration_time - offline_detection_time
                        self.state["recovery_time"] = recovery_time
                        first_heartbeat_after_recovery = self.state["last_heartbeat"]
                        print(f"[{utc_now_iso()}] ALEX API reported ONLINE. Recovery took {recovery_time:.2f}s")
                        break
                        
                if time.time() - t0 > 300: # 5 mins timeout
                    print("Timeout waiting for recovery sequence.")
                    break
        except KeyboardInterrupt:
            print("Interrupted")
            
        self.client.loop_stop()
        self.client.disconnect()
        
        # TASK 6: Require actual transitions
        if phase != "wait_recovery" or online_restoration_time is None:
            result_str = "WAITING_FOR_PHYSICAL_TEST"
            print("\nResult: WAITING_FOR_PHYSICAL_TEST (No physical transition observed)")
        else:
            result_str = "PHYSICAL_PASS"
            print("\nResult: PHYSICAL_PASS")
            print(f" - Last heartbeat before loss: {last_heartbeat_before_loss}")
            print(f" - Offline detection timestamp: {offline_detection_time}")
            print(f" - First heartbeat after recovery: {first_heartbeat_after_recovery}")
            print(f" - Online restoration timestamp: {online_restoration_time}")
            print(f" - Recovery duration: {self.state['recovery_time']:.2f}s")
            
        self.save_report("watch_recovery", None, fetch_health(), result_str)

    def run_broker_restart(self):
        print("=== BROKER RESTART ===")
        if not self.execute_safe:
            print("Observation only. Please manually restart Mosquitto in another terminal:")
            print("sudo systemctl restart mosquitto")
        else:
            print("Restarting Mosquitto...")
            os.system("sudo systemctl restart mosquitto")
            
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()
        
        try:
            print("Waiting 30 seconds to observe reconnects...")
            time.sleep(30)
        except KeyboardInterrupt:
            pass
            
        self.client.loop_stop()
        self.client.disconnect()
        self.save_report("broker_restart", None, fetch_health(), "CODE_READY")

    def save_report(self, test_name, esp_data, health_data, result_str="OK"):
        os.makedirs(REPORT_DIR, exist_ok=True)
        filename = f"phase7-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        path = os.path.join(REPORT_DIR, filename)
        
        # Scrub keys if accidentally included
        scrubbed_env = dict(os.environ)
        for k in list(scrubbed_env.keys()):
            if "PASSWORD" in k or "API_KEY" in k:
                scrubbed_env[k] = "***"

        report = {
            "test_name": test_name,
            "started_at": self.started_at,
            "finished_at": utc_now_iso(),
            "mode": self.mode,
            "result": result_str,
            "observations": {
                "events_count": len(self.events),
                "heartbeats_received": self.state["heartbeats"],
                "status_online_count": self.state["status_online_count"],
                "status_offline_count": self.state["status_offline_count"],
                "recovery_time": self.state["recovery_time"],
                "health_final": health_data,
                "device_final": esp_data
            },
            "events": self.events,
            "limitations": [
                "Script is read-only unless --execute-safe-system-test is used",
                "Does not physically verify relay state, only logical lockdown"
            ]
        }
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        print(f"Report saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="ALEX Phase 7 Hardware Acceptance Harness")
    parser.add_argument("mode", choices=["baseline", "watch-recovery", "broker-restart"])
    parser.add_argument("--execute-safe-system-test", action="store_true", help="Allow script to run systemd commands")
    
    args = parser.parse_args()
    
    harness = Harness(args.mode, args.execute_safe_system_test)
    
    if args.mode == "baseline":
        harness.run_baseline()
    elif args.mode == "watch-recovery":
        harness.run_watch_recovery()
    elif args.mode == "broker-restart":
        harness.run_broker_restart()

if __name__ == "__main__":
    main()
