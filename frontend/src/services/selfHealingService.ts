import { config } from "../lib/config";
import type { CascadeQuery } from "../types/cascade";
import type { SelfHealingReport } from "../types/selfHealing";
import { apiClient } from "./apiClient";

export const selfHealingService = {
  /** Recovery plans of a deterministic simulated cascade, plus an advisory plan for RECORDED failures. */
  getReport: (requestCode: string, query: CascadeQuery, signal?: AbortSignal) =>
    apiClient.get<SelfHealingReport>(
      `${config.apiPrefix}/requests/${encodeURIComponent(requestCode)}/self-healing` +
        `?evaluate_at=${query.evaluateAt}&max_waves=${query.maxWaves}&seed=${query.seed}` +
        `&response_stress=${query.stress}`,
      { signal },
    ),
};
