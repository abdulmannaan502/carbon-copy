// Mirrors backend/app/schemas/system.py. Keep both sides in sync.

export type DatabaseState = "connected" | "unavailable";

export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  database: DatabaseState;
  timestamp: string;
}

export interface AIStatus {
  provider: string;
  enabled: boolean;
}

export interface SystemStatusResponse {
  service: string;
  version: string;
  environment: string;
  database: DatabaseState;
  ai: AIStatus;
  demo_mode: boolean;
  disclaimer: string;
}

export interface DatasetStats {
  patients: number;
  donors: number;
  donor_states: number;
  bridge_groups: number;
  blood_requests: number;
  donor_interactions: number;
  coordination_attempts: number;
  failures: number;
  recovery_actions: number;
  learning_events: number;
  seeded: boolean;
  data_notice: string;
}
