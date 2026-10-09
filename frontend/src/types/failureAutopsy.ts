// Mirrors backend/app/schemas/failure_autopsy.py. Keep both sides in sync.
import type { Channel } from "./cascade";
import type { ApiDateTime, FailureCategory, FailureSeverity } from "./twin";

export type FailureSource = "RECORDED" | "SIMULATED";

export type FailurePatternType =
  | "INDIVIDUAL_DONOR_FAILURE"
  | "CHANNEL_RESPONSE_FAILURE"
  | "LOCAL_POOL_FAILURE"
  | "BRIDGE_GROUP_FAILURE"
  | "CANDIDATE_POOL_EXHAUSTION"
  | "RESPONSE_WINDOW_FAILURE"
  | "RECENT_DONATION_POOL"
  | "UNKNOWN_PATTERN";

export type EvidenceType = "ATTEMPT" | "INTERACTION" | "OUTCOME" | "PATTERN" | "CONTEXT";

export interface EvidenceItem {
  type: EvidenceType;
  description: string;
  reference: string | null;
}

/** What Failure Autopsy recommends considering — a distinct vocabulary from RecoveryActionType
 * (what Self-Healing actually decides and executes). Autopsy recommends; it never acts. */
export type RecoveryRecommendation =
  | "TRY_ALTERNATIVE_DONOR"
  | "SWITCH_CHANNEL"
  | "INCREASE_WAVE_SIZE"
  | "TRY_ALTERNATIVE_BRIDGE_GROUP"
  | "NO_CHANGE"
  | "EXPAND_SEARCH_RADIUS"
  | "RE_RUN_MATCHING"
  | "HUMAN_COORDINATOR"
  | "BLOOD_BANK_ESCALATION";

export interface IndividualFailureAutopsy {
  source: FailureSource;
  failure_type: FailureCategory;
  severity: FailureSeverity;
  rule_confidence: number;
  summary: string;
  evidence: EvidenceItem[];
  affected_donor: string;
  affected_request: string;
  affected_channel: Channel | null;
  detected_at: ApiDateTime;
  reference: string | null;
  donor_specific: boolean;
  channel_specific: boolean;
  timing_related: boolean;
  network_related: boolean;
  recommended_next_action: RecoveryRecommendation;
}

export interface PatternFinding {
  pattern_type: FailurePatternType;
  severity: FailureSeverity;
  rule_confidence: number;
  supporting_failures: number;
  affected_donors: string[];
  affected_channel: Channel | null;
  donor_specific: boolean;
  channel_specific: boolean;
  timing_related: boolean;
  network_related: boolean;
  evidence: EvidenceItem[];
  interpretation: string;
  recommended_action: RecoveryRecommendation;
}

export interface RequestAutopsy {
  request_code: string;
  analysis_time: ApiDateTime;
  source: FailureSource;
  failures_analyzed: number;
  individual_failures: IndividualFailureAutopsy[];
  patterns: PatternFinding[];
  pattern_detected: boolean;
  dominant_pattern: PatternFinding | null;
  recommended_action: RecoveryRecommendation | null;
  explanation: string;
  notice: string;
  data_notice: string;
}
