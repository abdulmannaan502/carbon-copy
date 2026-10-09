import type { StatusTone } from "../ui/Status";
import type { NetworkStrengthBand, OperationalState, RecurrenceStatus, RequestStatus } from "../../types/twin";

export const OPERATIONAL_STATE_DISPLAY: Record<OperationalState, { label: string; tone: StatusTone; meaning: string }> = {
  ACTIVE_COORDINATION: {
    label: "Active coordination",
    tone: "warning",
    meaning: "A blood request is currently being coordinated.",
  },
  ATTENTION: {
    label: "Attention",
    tone: "critical",
    meaning: "A requirement is approaching without a confirmed donor, or the donor network is weak.",
  },
  WATCH: { label: "Watch", tone: "neutral", meaning: "Some coordination risk indicators are present." },
  HEALTHY: { label: "Healthy", tone: "ok", meaning: "No immediate coordination concern detected." },
};

export const RECURRENCE_DISPLAY: Record<RecurrenceStatus, { label: string; tone: StatusTone }> = {
  STABLE: { label: "Stable", tone: "ok" },
  APPROACHING: { label: "Approaching", tone: "warning" },
  DUE: { label: "Due", tone: "critical" },
  OVERDUE: { label: "Overdue", tone: "critical" },
  UNKNOWN: { label: "Unknown", tone: "neutral" },
};

export const NETWORK_BAND_DISPLAY: Record<NetworkStrengthBand, { label: string; tone: StatusTone }> = {
  STRONG: { label: "Strong", tone: "ok" },
  MODERATE: { label: "Moderate", tone: "warning" },
  WEAK: { label: "Weak", tone: "critical" },
};

export const REQUEST_STATUS_TONE: Record<RequestStatus, StatusTone> = {
  OPEN: "neutral",
  MATCHING: "warning",
  COORDINATING: "warning",
  RECOVERING: "critical",
  FULFILLED: "ok",
  CANCELLED: "neutral",
};

/** Chart colours, validated for colour-vision deficiency on the light surface. */
export const OUTCOME_COLORS = { successful: "#0d9488", failed: "#d97706" } as const;
