// Mirrors backend/app/schemas/cascade.py. Keep both sides in sync.
import type { EvaluateAt, EvaluationPoint, RequestSummary } from "./donorState";
import type { RequestAutopsy } from "./failureAutopsy";
import type { CandidateStrategy } from "./matching";
import type { EscalationSummary, EscalationType, RecoveryPlan } from "./selfHealing";
import type { ApiDateTime, BloodGroup, RecoveryActionType } from "./twin";

export type { EvaluateAt };
export type SimulatedResponse = "ACCEPTED" | "DECLINED" | "UNAVAILABLE" | "NO_RESPONSE";
export type CascadeOutcome = "FULFILLED" | "ESCALATED";
export type Channel = "SIMULATED_SMS" | "SIMULATED_CALL" | "SIMULATED_APP";
export type ResponseStress = "none" | "moderate" | "severe";
export type LearningEventType =
  | "SUCCESSFUL_MATCH"
  | "FAILED_MATCH"
  | "NO_RESPONSE"
  | "DONOR_DECLINED"
  | "RECOVERY_SUCCESS"
  | "RECOVERY_FAILURE";

export interface CascadeContact {
  donor_code: string;
  display_name: string;
  blood_group: BloodGroup;
  match_rank: number;
  match_score: number;
  candidate_strategy: CandidateStrategy | null;
  bridge_group_member: boolean;
  channel: Channel;
  sent_at: ApiDateTime;
  response_probability: number;
  acceptance_probability: number;
  response: SimulatedResponse;
  responded_at: ApiDateTime | null;
  secured: boolean;
  note: string;
}

export interface WaveAutopsy {
  accepted: number;
  declined: number;
  unavailable: number;
  no_response: number;
  dominant_cause: SimulatedResponse | null;
  summary: string;
}

export interface HealingDecision {
  action: RecoveryActionType;
  rationale: string;
  next_wave_size: number | null;
  channel_override: Channel | null;
  radius_step: number;
  bridge_group_first: boolean;
}

export interface CascadeWave {
  wave_number: number;
  started_at: ApiDateTime;
  closed_at: ApiDateTime;
  response_window_minutes: number;
  wave_size: number;
  applied_action: RecoveryActionType | null;
  eligible_candidates: number;
  radius_km: number | null;
  contacts: CascadeContact[];
  units_secured_after_wave: number;
  autopsy: WaveAutopsy | null;
  healing: HealingDecision | null;
  /** Structured Failure Autopsy Engine analysis of this wave's failures (SIMULATED source). */
  failure_autopsy: RequestAutopsy | null;
  /** Self-Healing Engine plan made from the autopsy; applied to the next wave. */
  recovery_plan: RecoveryPlan | null;
}

export interface CascadeResult {
  request: RequestSummary;
  evaluation_point: EvaluationPoint;
  simulation_start: ApiDateTime;
  parameters: {
    wave_size: number;
    max_waves: number;
    response_window_minutes: number;
    seed: number;
    initial_channel_policy: string;
    response_stress: ResponseStress;
  };
  outcome: CascadeOutcome;
  units_required: number;
  units_secured: number;
  waves_used: number;
  total_contacts: number;
  secured_donor_codes: string[];
  completed_at: ApiDateTime;
  elapsed_minutes: number;
  deadline_met: boolean;
  escalation: HealingDecision | null;
  requires_human_intervention: boolean;
  escalation_type: EscalationType | null;
  escalation_summary: EscalationSummary | null;
  waves: CascadeWave[];
  learning_preview: Array<{ donor_code: string | null; event_type: LearningEventType; signal: number; source: string }>;
  historical_attempts: Array<{ sequence_number: number; donor_code: string; status: string; outcome: string | null }>;
  notice: string;
  data_notice: string;
}

export interface CascadeQuery {
  evaluateAt: EvaluateAt;
  maxWaves: number;
  seed: number;
  stress: ResponseStress;
}
