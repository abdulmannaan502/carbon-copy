// Mirrors backend/app/schemas/matching.py. Keep both sides in sync.
import type {
  CoordinationAvailability,
  DataSufficiency,
  EvaluateAt,
  EvaluationPoint,
  Impact,
  RequestSummary,
  WeightProfile,
} from "./donorState";
import type { ApiDateTime, BloodGroup, NetworkStrengthBand, OperationalState } from "./twin";

export type { EvaluateAt };
export type CandidateStrategy = "RELIABLE" | "BALANCED" | "EXPLORATION";

export interface MatchReason {
  text: string;
  impact: Impact;
}

export interface ScoreComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  points: number;
}

export interface MatchCandidate {
  rank: number | null;
  donor_code: string;
  display_name: string;
  blood_group: BloodGroup;
  city: string;
  distance_km: number | null;
  eligible: boolean;
  availability_status: CoordinationAvailability;
  reliability_score: number;
  response_rate: number | null;
  response_score: number;
  response_data_sufficiency: DataSufficiency;
  fatigue_score: number;
  freshness_score: number;
  donor_priority_score: number;
  request_fit_score: number;
  geographic_fit_score: number;
  context_score: number;
  strategy_adjustment: number;
  match_score: number;
  candidate_strategy: CandidateStrategy | null;
  strategy_reason: string | null;
  score_breakdown: ScoreComponent[];
  reasons: MatchReason[];
  exclusion_reason: string | null;
}

export interface DiscoveryInfo {
  total_donors: number;
  request_location_known: boolean;
  radius_km: number | null;
  radius_expanded: boolean;
  filtered_inactive: number;
  filtered_incompatible: number;
  filtered_outside_radius: number;
  pool_cap: number;
  pool_capped: boolean;
  compatible_donor_groups: BloodGroup[];
}

export interface ExclusionCount {
  reason: string;
  count: number;
  stage: "discovery" | "gate";
}

export interface MatchingResult {
  request: RequestSummary;
  evaluation: { evaluation_point: EvaluationPoint; assessed_at: ApiDateTime; note: string };
  digital_twin_context: {
    patient_code: string;
    operational_state: OperationalState;
    active_request_code: string | null;
    requirement_covered: boolean;
    network_strength_score: number;
    network_strength_band: NetworkStrengthBand;
  };
  discovery: DiscoveryInfo;
  candidate_pool_size: number;
  eligible_candidate_count: number;
  excluded_candidate_count: number;
  weights: {
    profile: WeightProfile;
    components: Record<string, number>;
    exploration_bonus: number;
    uncertainty_discount: number;
  };
  ranking: MatchCandidate[];
  excluded: MatchCandidate[];
  matching_summary: {
    top_candidate: string | null;
    average_match_score: number | null;
    candidates_by_strategy: Record<CandidateStrategy, number>;
    top_exclusion_reasons: ExclusionCount[];
  };
  notice: string;
  data_notice: string;
}
