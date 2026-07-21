export type ConnectionState = "online" | "degraded" | "offline" | "unknown";
export type AppMode = "presence" | "command";
export type RoomMode = "home" | "away" | "sleep" | "study";

export interface HealthPayload {
  api: string;
  mqtt: string;
  device: string;
  last_seen: string | null;
}

export interface ConfigPayload {
  room_name: string;
  relay_names: Record<string, string>;
  relay_subtitles: Record<string, string>;
}

export interface DevicePayload {
  device_id: string;
  availability: string;
  last_seen: string | null;
  mode: RoomMode;
  relays: Record<string, string>;
}

export interface SystemPayload {
  memory: { total: number; used: number; percent: number };
  disk: { total: number; used: number; percent: number };
  load: number[];
  uptime_seconds: number;
  temperature_c: number | null;
  tailscale_ip: string | null;
}

export interface EventItem {
  time: string;
  kind: string;
  message: string;
  level: string;
}

export interface SystemSnapshot {
  health: HealthPayload;
  config: ConfigPayload;
  device: DevicePayload;
  system: SystemPayload;
  events: EventItem[];
  v1Device: V1Device | null;
  currentCommand: V1Command | null;
  receivedAt: string;
}

export interface V1Device {
  node_id: string;
  friendly_name: string;
  firmware: string | null;
  ip: string | null;
  rssi: number | null;
  last_seen_at: string | null;
  connection: ConnectionState;
  capabilities: string[];
  risk_level: "safe" | "controlled" | "restricted";
  reported_state: { test_led?: { on: boolean } };
  desired_state: { test_led?: { on: boolean } } | null;
  current_command_id: string | null;
  source: string;
  hardware_verified: boolean;
}

export interface V1Command {
  command_id: string;
  node_id: string;
  target: string;
  action: string;
  desired_state: { on: boolean };
  reported_state: { on: boolean } | null;
  phase: string;
  source: string;
  origin: string;
  created_at: string;
  sent_at: string | null;
  acknowledged_at: string | null;
  confirmed_at: string | null;
  updated_at: string;
  retry_count: number;
  failure_reason: string | null;
  ack_status: string | null;
}
