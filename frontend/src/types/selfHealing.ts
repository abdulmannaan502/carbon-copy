// Mirrors backend/app/schemas/self_healing.py. Keep both sides in sync.
import type { Channel } from "./cascade";
import type { FailurePatternType, FailureSource, RecoveryRecommendation } from "./failureAutopsy";
import type { FailureSeverity, UrgencyLevel } from "./twin";

export type EscalationType = "HUMAN_COORDINATOR" | "BLOOD_BANK";
export type BridgePriority = "DEFAULT" | "BRIDGE_FIRST" | "NON_BRIDGE_FIRST";

export interface RecoveryChanges {
  channel: Channel | null;
  wave_size: number | null;
  radius_step: number | null;
  radius_km: number | null;
  radius_label: string | null;
  bridge_priority: BridgePriority | null;
}

export interface CascadeStateSnapshot {
  wave_number: number;
  max_waves: number;
  wave_size: number;
  channel: Channel | null;
  radius_label: string;
  donors_contacted: number;
  consecutive_failed_waves: number;
  recovery_attempts: number;
  channel_switches: number;
  eligible_remaining: number;
  fatigued_remaining: number;
  bridge_members_remaining: number;
  bridge_priority: BridgePriority;
}

export interface EscalationSummary {
  escalation_type: EscalationType;
  why_automation_stopped: string;
  actions_attempted: string[];
  donors_contacted: number;
  failures: Record<string, number>;
  recommended_human_action: string;
}

export interface RecoveryPlan {
  request_code: string;
  source: FailureSource;
  wave_number: number;
  trigger: { pattern: FailurePatternType | null; severity: FailureSeverity | null };
  urgency: UrgencyLevel;
  autopsy_recommended: RecoveryRecommendation | null;
  primary_action: RecoveryRecommendation;
  fallback_actions: RecoveryRecommendation[];
  rule_id: string;
  rule_name: string;
  rule_strength: number;
  reason: string;
  evidence: string[];
  current_state: CascadeStateSnapshot;
  changes: RecoveryChanges;
  expected_effect: string;
  requires_human_intervention: boolean;
  escalation_type: EscalationType | null;
  escalation: EscalationSummary | null;
  notice: string;
}

export interface SelfHealingReport {
  request_code: string;
  simulated_plans: Array<{ wave_number: number; plan: RecoveryPlan }>;
  simulated_outcome: string;
  automatic_recovery_attempts: number;
  requires_human_intervention: boolean;
  escalation_type: EscalationType | null;
  recorded_plan: RecoveryPlan | null;
  parameters: Record<string, string | number>;
  notice: string;
  data_notice: string;
}
