import { config } from "../lib/config";
import type { EvaluateAt, MatchingResult } from "../types/matching";
import { apiClient } from "./apiClient";

export const matchingService = {
  getMatching: (requestCode: string, limit: number, evaluateAt: EvaluateAt, signal?: AbortSignal) =>
    apiClient.get<MatchingResult>(
      `${config.apiPrefix}/requests/${encodeURIComponent(requestCode)}/matching` +
        `?limit=${limit}&include_excluded=true&evaluate_at=${evaluateAt}`,
      { signal },
    ),
};
