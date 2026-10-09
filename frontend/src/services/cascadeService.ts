import { config } from "../lib/config";
import type { CascadeQuery, CascadeResult } from "../types/cascade";
import { apiClient } from "./apiClient";

export const cascadeService = {
  simulate: (requestCode: string, query: CascadeQuery, signal?: AbortSignal) =>
    apiClient.get<CascadeResult>(
      `${config.apiPrefix}/requests/${encodeURIComponent(requestCode)}/cascade` +
        `?evaluate_at=${query.evaluateAt}&max_waves=${query.maxWaves}&seed=${query.seed}` +
        `&response_stress=${query.stress}`,
      { signal },
    ),
};
