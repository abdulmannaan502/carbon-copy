import type { StatusTone } from "../ui/Status";
import type { CoordinationAvailability, FatigueBand, PriorityBand, ScoreBand } from "../../types/donorState";

export const AVAILABILITY_DISPLAY: Record<CoordinationAvailability, { label: string; tone: StatusTone }> = {
  AVAILABLE: { label: "Available", tone: "ok" },
  RECENTLY_CONTACTED: { label: "Recently contacted", tone: "warning" },
  TEMPORARILY_UNAVAILABLE: { label: "Temporarily unavailable", tone: "critical" },
  INACTIVE: { label: "Inactive", tone: "neutral" },
};

export const PRIORITY_DISPLAY: Record<PriorityBand, { label: string; tone: StatusTone }> = {
  HIGH: { label: "High", tone: "ok" },
  MEDIUM: { label: "Medium", tone: "warning" },
  LOW: { label: "Low", tone: "neutral" },
  NOT_ELIGIBLE: { label: "Not eligible", tone: "critical" },
};

export const SCORE_BAND_LABEL: Record<ScoreBand, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };
export const FATIGUE_BAND_LABEL: Record<FatigueBand, string> = { LOW: "Low", MODERATE: "Moderate", HIGH: "High" };
