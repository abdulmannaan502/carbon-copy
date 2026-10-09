// Mirrors backend/app/schemas/digital_twin.py. Keep both sides in sync.

export type BloodGroup = "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-";
export type UrgencyLevel = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
export type RequestStatus = "OPEN" | "MATCHING" | "COORDINATING" | "FULFILLED" | "RECOVERING" | "CANCELLED";
export type CoordinationStatus = "INITIATED" | "OUTREACH_SENT" | "WAITING" | "SUCCESS" | "FAILED" | "SKIPPED";
export type CoordinationOutcome = "DONOR_ACCEPTED" | "NO_RESPONSE" | "DONOR_UNAVAILABLE" | "DONOR_DECLINED" | "OTHER";
export type RecoveryActionType =
  | "NEXT_DONOR"
  | "ALTERNATIVE_DONOR"
  | "BRIDGE_GROUP_ESCALATION"
  | "EXPANDED_SEARCH"
  | "BLOOD_BANK_REFERRAL"
  | "HUMAN_COORDINATOR_REVIEW";
export type RecoveryStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED" | "FAILED";
export type FailureCategory =
  | "NO_RESPONSE"
  | "UNAVAILABLE"
  | "DECLINED"
  | "CONTACT_FAILURE"
  | "FATIGUE"
  | "RECENT_DONATION"
  | "DEFERRAL"
  | "ALREADY_CONTACTED"
  | "CASCADE_EXHAUSTED"
  | "OTHER";
export type FailureSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type RecurrenceStatus = "STABLE" | "APPROACHING" | "DUE" | "OVERDUE" | "UNKNOWN";
export type OperationalState = "HEALTHY" | "WATCH" | "ATTENTION" | "ACTIVE_COORDINATION";
export type NetworkStrengthBand = "STRONG" | "MODERATE" | "WEAK";
export type TimelineEventKind =
  | "REQUEST_CREATED"
  | "AVAILABILITY_CHECKS"
  | "DONOR_CONTACTED"
  | "DONOR_ACCEPTED"
  | "ATTEMPT_FAILED"
  | "FAILURE_DETECTED"
  | "RECOVERY_INITIATED"
  | "AWAITING_RESPONSE"
  | "REQUEST_FULFILLED"
  | "REQUEST_CANCELLED";
export type TimelineTone = "NEUTRAL" | "POSITIVE" | "NEGATIVE" | "PENDING";

/** Naive UTC timestamp from the API, e.g. "2026-10-08T09:00:00". */
export type ApiDateTime = string;
/** Calendar date, e.g. "2026-10-11". */
export type ApiDate = string;

export interface PatientIdentity {
  patient_code: string;
  display_name: string;
  blood_group: BloodGroup;
  city: string;
  district: string;
  state: string;
  urgency_level: UrgencyLevel;
  bridge_group_code: string | null;
  bridge_group_name: string | null;
  active: boolean;
}

export interface TransfusionProfile {
  transfusion_frequency_days: number | null;
  last_transfusion_date: ApiDate | null;
  next_expected_requirement: ApiDate | null;
  days_until_expected_requirement: number | null;
  recurrence_status: RecurrenceStatus;
}

export interface RequirementState {
  active_request: boolean;
  active_request_code: string | null;
  current_request_code: string | null;
  requirement_covered: boolean;
  units_required: number | null;
  request_status: RequestStatus | null;
  request_urgency: UrgencyLevel | null;
  requested_at: ApiDateTime | null;
  required_by: ApiDateTime | null;
  attempts_made: number;
  failed_attempts: number;
  latest_attempt_status: CoordinationStatus | null;
  pending_recovery_action: RecoveryActionType | null;
}

export interface RequestOutcomeSummary {
  request_code: string;
  requested_at: ApiDateTime;
  status: RequestStatus;
  attempts: number;
  failed_attempts: number;
  successful_attempts: number;
}

export interface CoordinationHistory {
  total_requests: number;
  fulfilled_requests: number;
  requests_with_failures: number;
  recovering_requests: number;
  cancelled_requests: number;
  active_requests: number;
  historical_success_rate: number | null;
  first_attempt_success_rate: number | null;
  average_coordination_attempts: number | null;
  total_coordination_attempts: number;
  total_failures: number;
  total_recovery_actions: number;
  successful_recoveries: number;
  requests: RequestOutcomeSummary[];
}

export interface NetworkStrengthComponents {
  depth: number;
  reliability: number;
  responsiveness: number;
  freshness: number;
}

export interface NetworkState {
  known_donor_count: number;
  active_donor_count: number;
  available_donor_count: number;
  high_reliability_donor_count: number;
  recently_contacted_donor_count: number;
  fatigued_donor_count: number;
  bridge_group_donor_count: number;
  network_strength_score: number;
  network_strength_band: NetworkStrengthBand;
  strength_components: NetworkStrengthComponents;
  /** Weight of each component in percent. */
  strength_weights: NetworkStrengthComponents;
}

export interface TimelineEvent {
  at: ApiDateTime;
  kind: TimelineEventKind;
  title: string;
  detail: string | null;
  tone: TimelineTone;
}

export interface RecentActivity {
  window_days: number;
  last_request_date: ApiDateTime | null;
  last_successful_coordination: ApiDateTime | null;
  last_failed_coordination: ApiDateTime | null;
  recent_interaction_count: number;
  recent_failure_count: number;
  recent_success_count: number;
  focus_request_code: string | null;
  timeline: TimelineEvent[];
}

export interface DigitalTwinState {
  as_of: ApiDateTime;
  patient: PatientIdentity;
  transfusion_profile: TransfusionProfile;
  requirement_state: RequirementState;
  coordination_history: CoordinationHistory;
  network_state: NetworkState;
  recent_activity: RecentActivity;
  operational_state: OperationalState;
  operational_state_reasons: string[];
  summary: string;
  summary_source: string;
  data_notice: string;
}

export interface PatientListItem {
  patient_code: string;
  display_name: string;
  blood_group: BloodGroup;
  city: string;
  district: string;
  state: string;
  urgency_level: UrgencyLevel;
  transfusion_frequency_days: number;
  last_transfusion_date: ApiDate | null;
  next_expected_requirement: ApiDate | null;
  bridge_group_code: string | null;
  active: boolean;
}

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}
