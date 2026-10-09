// Mirrors backend/app/schemas/learning.py. Keep both sides in sync.
import type { FailureSource } from "./failureAutopsy";
import type { ApiDateTime } from "./twin";

export type EvidenceStrength = "INSUFFICIENT_DATA" | "LOW" | "MODERATE" | "HIGH";
export type InsightCategory =
  | "CHANNEL_EFFECTIVENESS"
  | "FAILURE_PATTERN"
  | "RECOVERY_EFFECTIVENESS"
  | "DONOR_FATIGUE"
  | "COORDINATION_BOTTLENECK";

export interface InsightGroup {
  label: string;
  numerator: number | null;
  denominator: number | null;
  rate: number | null;
  ci_low: number | null;
  ci_high: number | null;
  value: number | null;
  unit: string | null;
}

export interface TimeWindow {
  start: ApiDateTime | null;
  end: ApiDateTime | null;
}

export interface Insight {
  insight_id: string;
  category: InsightCategory;
  source: FailureSource;
  provenance: string;
  title: string;
  finding: string;
  numerator: number | null;
  denominator: number | null;
  sample_size: number;
  time_window: TimeWindow;
  strength: EvidenceStrength;
  strength_reason: string;
  reason: string;
  limitations: string[];
  consideration: string;
  groups: InsightGroup[];
}

export interface Recommendation {
  recommendation_id: string;
  insight_ids: string[];
  text: string;
  strength: EvidenceStrength;
  implemented: boolean;
  adjustment: { target: string; value: number; bound: number } | null;
}

export interface SufficiencyEntry {
  capability: string;
  status: EvidenceStrength;
  reason: string;
}

export interface LearningReport {
  source: FailureSource;
  provenance: string;
  population: string;
  time_window: TimeWindow;
  insights: Insight[];
  recommendations: Recommendation[];
  sufficiency: SufficiencyEntry[];
  thresholds: Record<string, number | string>;
  adjustments_enabled: boolean;
  operational_effect: string;
  notice: string;
  data_notice: string;
}

export interface LearningSimulationQuery {
  seed: number;
  runs: number;
  stress: "none" | "moderate" | "severe";
}
