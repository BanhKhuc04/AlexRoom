#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include "config.h"

namespace {
constexpr char NODE_ID[] = "esp01";
constexpr char FIRMWARE_VERSION[] = "1.0.0";
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint8_t TEST_LED_PIN = LED_BUILTIN;
constexpr bool LED_ACTIVE_LOW = true;
constexpr unsigned long HEARTBEAT_INTERVAL_MS = 10000;
constexpr unsigned long RECONNECT_MIN_MS = 1000;
constexpr unsigned long RECONNECT_MAX_MS = 30000;
constexpr size_t RECENT_COMMANDS = 8;

constexpr char COMMAND_TOPIC[] = "alex/v1/nodes/esp01/command";
constexpr char ACK_TOPIC[] = "alex/v1/nodes/esp01/ack";
constexpr char REPORTED_TOPIC[] = "alex/v1/nodes/esp01/reported";
constexpr char HEARTBEAT_TOPIC[] = "alex/v1/nodes/esp01/heartbeat";
constexpr char STATUS_TOPIC[] = "alex/v1/nodes/esp01/status";

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
bool ledOn = false;
unsigned long lastHeartbeat = 0;
unsigned long nextWifiAttempt = 0;
unsigned long nextMqttAttempt = 0;
unsigned long wifiBackoff = RECONNECT_MIN_MS;
unsigned long mqttBackoff = RECONNECT_MIN_MS;

struct CachedCommand {
  String id;
  bool value = false;
  bool valid = false;
};
CachedCommand recent[RECENT_COMMANDS];
size_t recentCursor = 0;

unsigned long timestampMs() { return millis(); }

void setLed(bool on) {
  ledOn = on;
  digitalWrite(TEST_LED_PIN, LED_ACTIVE_LOW ? !on : on);
}

CachedCommand* findCached(const String& id) {
  for (auto& item : recent) {
    if (item.valid && item.id == id) return &item;
  }
  return nullptr;
}

void remember(const String& id, bool value) {
  recent[recentCursor] = {id, value, true};
  recentCursor = (recentCursor + 1) % RECENT_COMMANDS;
}

void publishAck(const String& commandId, const char* status, const char* reason = nullptr) {
  JsonDocument doc;
  doc["protocolVersion"] = PROTOCOL_VERSION;
  doc["commandId"] = commandId;
  doc["nodeId"] = NODE_ID;
  doc["status"] = status;
  doc["timestamp"] = timestampMs();
  if (reason) doc["reason"] = reason;
  char output[256];
  serializeJson(doc, output, sizeof(output));
  mqtt.publish(ACK_TOPIC, output, false);
}

void publishReported(const String& commandId, bool value) {
  JsonDocument doc;
  doc["protocolVersion"] = PROTOCOL_VERSION;
  doc["nodeId"] = NODE_ID;
  doc["target"] = "test_led";
  doc["state"]["on"] = value;
  doc["commandId"] = commandId;
  doc["timestamp"] = timestampMs();
  char output[256];
  serializeJson(doc, output, sizeof(output));
  mqtt.publish(REPORTED_TOPIC, output, true);
}

void handleCommand(char*, uint8_t* bytes, unsigned int length) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, bytes, length);
  if (error) {
    Serial.printf("[MQTT] Invalid JSON: %s\n", error.c_str());
    return;
  }
  const String commandId = doc["commandId"] | "";
  const char* target = doc["target"] | "";
  const char* action = doc["action"] | "";
  if (doc["protocolVersion"] != PROTOCOL_VERSION || commandId.length() == 0) return;
  if (strcmp(target, "test_led") != 0 || strcmp(action, "set") != 0 || !doc["value"].is<bool>()) {
    publishAck(commandId, "rejected", "unsupported_target_or_action");
    return;
  }
  if (CachedCommand* cached = findCached(commandId)) {
    Serial.printf("[CMD] Duplicate %s; no second execution\n", commandId.c_str());
    publishAck(commandId, "duplicate");
    publishReported(commandId, cached->value);
    return;
  }
  const bool desired = doc["value"].as<bool>();
  publishAck(commandId, "accepted");
  setLed(desired);
  remember(commandId, desired);
  publishReported(commandId, ledOn);
  Serial.printf("[CMD] %s test_led=%s\n", commandId.c_str(), ledOn ? "ON" : "OFF");
}

void publishHeartbeat() {
  JsonDocument doc;
  doc["protocolVersion"] = PROTOCOL_VERSION;
  doc["nodeId"] = NODE_ID;
  doc["online"] = true;
  doc["uptime"] = millis() / 1000;
  doc["rssi"] = WiFi.RSSI();
  doc["firmware"] = FIRMWARE_VERSION;
  doc["ip"] = WiFi.localIP().toString();
  doc["timestamp"] = timestampMs();
  char output[320];
  serializeJson(doc, output, sizeof(output));
  mqtt.publish(HEARTBEAT_TOPIC, output, false);
}

void maintainWifi(unsigned long now) {
  if (WiFi.status() == WL_CONNECTED) {
    wifiBackoff = RECONNECT_MIN_MS;
    return;
  }
  if (now < nextWifiAttempt) return;
  Serial.printf("[WIFI] Reconnect; backoff=%lums\n", wifiBackoff);
  WiFi.disconnect();
  WiFi.begin(ALEX_WIFI_SSID, ALEX_WIFI_PASSWORD);
  nextWifiAttempt = now + wifiBackoff;
  wifiBackoff = min(wifiBackoff * 2, RECONNECT_MAX_MS);
}

void maintainMqtt(unsigned long now) {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected()) return;
  if (now < nextMqttAttempt) return;
  String clientId = String("alex-") + NODE_ID + "-" + String(ESP.getChipId(), HEX);
  const char offline[] = "{\"protocolVersion\":1,\"nodeId\":\"esp01\",\"online\":false,\"source\":\"hardware\"}";
  Serial.printf("[MQTT] Connect %s; backoff=%lums\n", clientId.c_str(), mqttBackoff);
  if (mqtt.connect(clientId.c_str(), ALEX_MQTT_USERNAME, ALEX_MQTT_PASSWORD, STATUS_TOPIC, 1, true, offline)) {
    mqttBackoff = RECONNECT_MIN_MS;
    mqtt.subscribe(COMMAND_TOPIC, 1);
    mqtt.publish(STATUS_TOPIC, "{\"protocolVersion\":1,\"nodeId\":\"esp01\",\"online\":true,\"source\":\"hardware\"}", true);
    publishReported("boot", ledOn);
    publishHeartbeat();
    Serial.println("[MQTT] Online");
  } else {
    nextMqttAttempt = now + mqttBackoff;
    mqttBackoff = min(mqttBackoff * 2, RECONNECT_MAX_MS);
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(TEST_LED_PIN, OUTPUT);
  setLed(false);  // Safe default after every boot.
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  mqtt.setServer(ALEX_MQTT_HOST, ALEX_MQTT_PORT);
  mqtt.setCallback(handleCommand);
  mqtt.setBufferSize(512);
  Serial.printf("\n[ALEX] %s firmware %s; safe test_led OFF\n", NODE_ID, FIRMWARE_VERSION);
}

void loop() {
  const unsigned long now = millis();
  maintainWifi(now);
  maintainMqtt(now);
  if (mqtt.connected()) {
    mqtt.loop();
    if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
      lastHeartbeat = now;
      publishHeartbeat();
    }
  }
  yield();
}
