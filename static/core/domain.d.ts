export type ConnectionState = "online" | "degraded" | "offline" | "unknown";
export type AppMode = "presence" | "command";
export type RoomMode = "home" | "away" | "sleep" | "study";
export type VerificationStatus =
  | "unknown"
  | "simulated"
  | "software_verified"
  | "basic_physical_validated"
  | "hardware_verified"
  | "restricted";

export interface CapabilityStatus {
  node_id: string;
  capability_id: string;
  risk_level: "safe" | "controlled" | "restricted" | "unknown";
  supported_actions: string[];
  verification_status: VerificationStatus;
  basic_physical_validation: boolean;
  hardware_verified: boolean;
  command_allowed: boolean;
  allowed_modes: string[];
  restriction_reason: string | null;
}

export interface NodeVerification {
  node_id: string;
  verification_status: VerificationStatus;
  hardware_verified: boolean;
  capabilities: Record<string, CapabilityStatus>;
}

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

export interface DevicePayload extends NodeVerification {
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
  details: Record<string, unknown> | null;
}

export interface OtaState {
  operation_id: string;
  target_version: string;
  status: string;
  requested_at: string;
  status_updated_at?: string;
  confirmed_at?: string;
  reason?: string;
}

export interface OtaInfo {
  installed_version: string | null;
  available_version: string | null;
  update_available: boolean;
  releases: Record<string, { size: number; sha256: string; created_at: string }>;
  state: OtaState | null;
}

export interface SystemSnapshot {
  health: HealthPayload;
  config: ConfigPayload;
  device: DevicePayload;
  system: SystemPayload;
  events: EventItem[];
  v1Device: V1Device | null;
  currentCommand: V1Command | null;
  otaInfo: OtaInfo | null;
  receivedAt: string;
}

export interface V1Device extends NodeVerification {
  node_id: string;
  friendly_name: string;
  firmware: string | null;
  ip: string | null;
  rssi: number | null;
  last_seen_at: string | null;
  connection: ConnectionState;
  reported_state: { test_led?: { on: boolean } };
  desired_state: { test_led?: { on: boolean } } | null;
  current_command_id: string | null;
  source: string;
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
  verification: {
    node: Omit<NodeVerification, "capabilities">;
    capability: CapabilityStatus | null;
  };
}
