// Mirrors backend/app/schemas/donor_state.py. Keep both sides in sync.
import type { ApiDateTime, BloodGroup, RequestStatus, UrgencyLevel } from "./twin";

export type CoordinationAvailability = "AVAILABLE" | "RECENTLY_CONTACTED" | "TEMPORARILY_UNAVAILABLE" | "INACTIVE";
export type DeclaredAvailability = "AVAILABLE" | "LIMITED" | "UNAVAILABLE";
export type ScoreBand = "HIGH" | "MEDIUM" | "LOW";
export type FatigueBand = "LOW" | "MODERATE" | "HIGH";
export type PriorityBand = "HIGH" | "MEDIUM" | "LOW" | "NOT_ELIGIBLE";
export type DataSufficiency = "SUFFICIENT" | "INSUFFICIENT_DATA";
export type EvaluationPoint = "CURRENT" | "REQUEST_START";
export type WeightProfile = "GENERAL" | "STANDARD" | "URGENT";
export type Impact = "POSITIVE" | "NEUTRAL" | "NEGATIVE";
export type EvaluateAt = "auto" | "now" | "request_start";

export interface DonorIdentity {
  donor_code: string;
  display_name: string;
  blood_group: BloodGroup;
  city: string;
  district: string;
  state: string;
  bridge_group_code: string | null;
  active: boolean;
}

export interface AvailabilityAssessment {
  availability_status: CoordinationAvailability;
  availability_reason: string;
  declared_availability: DeclaredAvailability | null;
  last_contacted_at: ApiDateTime | null;
  days_since_last_contact: number | null;
  awaiting_reply: boolean;
}

export interface EligibilityCheck {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface EligibilityAssessment {
  eligible: boolean;
  rule_set: string;
  checks: EligibilityCheck[];
  eligibility_reasons: string[];
  donation_count: number;
  last_donation_at: ApiDateTime | null;
  days_since_last_donation: number | null;
}

export interface ReliabilityAssessment {
  reliability_score: number;
  reliability_band: ScoreBand;
  successful_attempts: number;
  failed_attempts: number;
  no_response_failures: number;
  declined_or_unavailable_failures: number;
  other_failures: number;
  prior_donations_counted: number;
  evidence_weight: number;
  reliability_factors: string[];
}

export interface ResponseBehavior {
  total_interactions: number;
  total_responses: number;
  acceptances: number;
  declines: number;
  unavailable_replies: number;
  no_responses: number;
  pending: number;
  donation_requests: number;
  data_sufficiency: DataSufficiency;
  response_rate: number | null;
  acceptance_rate: number | null;
  no_response_rate: number | null;
  response_score: number;
}

export interface FatigueAssessment {
  fatigue_score: number;
  fatigue_band: FatigueBand;
  contacts_last_30_days: number;
  requests_last_30_days: number;
  fatigue_reasons: string[];
}

export interface FreshnessAssessment {
  days_since_last_contact: number | null;
  contact_freshness_score: number;
}

export interface PriorityFactor {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
}

export interface PriorityReason {
  text: string;
  impact: Impact;
}

export interface PriorityAssessment {
  priority_score: number;
  priority_band: PriorityBand;
  gated: boolean;
  weight_profile: WeightProfile;
  priority_factors: PriorityFactor[];
  priority_reasons: PriorityReason[];
}

export interface DonorStateAssessment {
  assessed_at: ApiDateTime;
  evaluation_point: EvaluationPoint;
  donor: DonorIdentity;
  availability: AvailabilityAssessment;
  eligibility: EligibilityAssessment;
  reliability: ReliabilityAssessment;
  response: ResponseBehavior;
  fatigue: FatigueAssessment;
  freshness: FreshnessAssessment;
  priority: PriorityAssessment;
  data_notice: string;
}

export interface RequestSummary {
  request_code: string;
  patient_code: string;
  blood_group: BloodGroup;
  urgency_level: UrgencyLevel;
  status: RequestStatus;
  city: string;
  requested_at: ApiDateTime;
  required_by: ApiDateTime;
}

export interface CompatibilityAssessment {
  request_blood_group: BloodGroup;
  donor_blood_group: BloodGroup;
  compatible: boolean;
  exact_match: boolean;
  compatible_donor_groups: BloodGroup[];
  rule_set: string;
}

export interface DonorRequestAssessment {
  request: RequestSummary;
  compatibility: CompatibilityAssessment;
  evaluation_note: string;
  state: DonorStateAssessment;
}

export interface DonorComparison {
  request: RequestSummary;
  evaluation_point: EvaluationPoint;
  assessed_at: ApiDateTime;
  candidates: DonorRequestAssessment[];
  recommended_donor_code: string | null;
  recommendation_reason: string;
  notice: string;
}

export interface DonorListItem {
  donor_code: string;
  display_name: string;
  blood_group: BloodGroup;
  city: string;
  district: string;
  state: string;
  bridge_group_code: string | null;
  active: boolean;
}
