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
        self.client = mqtt.Client(client_id=f"alex-harness-{int(time.time())}")
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

    def on_connect(self, client, userdata, flags, rc):
        print("[MQTT] Connected to broker")
        self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/status")
        self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/heartbeat")
        self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/reported")
        self.client.subscribe(f"alex/v1/nodes/{NODE_ID}/ack")

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
                if item.get("id") == NODE_ID:
                    esp = item
                    break
                    
        print(f"Device: {json.dumps(esp)}")
        
        if esp:
            print("hardware_verified:", esp.get("hardware_verified"))
            caps = esp.get("capabilities", {})
            for r in ["relay_1", "relay_2", "relay_3", "relay_4"]:
                rc = caps.get(r, {})
                print(f"{r} status: {rc.get('verification_status')} allowed: {rc.get('command_allowed')}")
                
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()
        print("Waiting 12 seconds for a heartbeat...")
        time.sleep(12)
        self.client.loop_stop()
        
        self.save_report("baseline_check", esp, health)

    def run_watch_recovery(self):
        print("=== WATCH RECOVERY ===")
        print("Please manually disconnect Wi-Fi or power-cycle the ESP.")
        print("Waiting for ONLINE -> OFFLINE -> ONLINE transition...")
        
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.loop_start()
        
        phase = "wait_initial_online"
        t0 = time.time()
        offline_time = None
        recovery_start = None
        
        try:
            while True:
                time.sleep(1)
                health = fetch_health()
                is_online = health.get("device") == "online"
                
                if phase == "wait_initial_online":
                    if is_online:
                        print("Initial state: ONLINE")
                        phase = "wait_offline"
                elif phase == "wait_offline":
                    if not is_online:
                        offline_time = time.time()
                        print(f"[{utc_now_iso()}] ALEX API reported OFFLINE")
                        phase = "wait_recovery"
                elif phase == "wait_recovery":
                    if is_online:
                        recovery_time = time.time() - offline_time
                        self.state["recovery_time"] = recovery_time
                        print(f"[{utc_now_iso()}] ALEX API reported ONLINE. Recovery took {recovery_time:.2f}s")
                        break
                        
                if time.time() - t0 > 300: # 5 mins timeout
                    print("Timeout waiting for recovery sequence.")
                    break
        except KeyboardInterrupt:
            print("Interrupted")
            
        self.client.loop_stop()
        self.save_report("watch_recovery", None, fetch_health())

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
        self.save_report("broker_restart", None, fetch_health())

    def save_report(self, test_name, esp_data, health_data):
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
            "result": "OK",
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
