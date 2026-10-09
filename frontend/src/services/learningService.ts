import { config } from "../lib/config";
import type { LearningReport, LearningSimulationQuery } from "../types/learning";
import { apiClient } from "./apiClient";

export const learningService = {
  /** RECORDED only: insights from the stored synthetic dataset. */
  getRecordedReport: (signal?: AbortSignal) => apiClient.get<LearningReport>(`${config.apiPrefix}/learning/report`, { signal }),
  /** SIMULATED only: insights from deterministic in-memory cascade runs. */
  getSimulationReport: (requestCode: string, query: LearningSimulationQuery, signal?: AbortSignal) =>
    apiClient.get<LearningReport>(
      `${config.apiPrefix}/requests/${encodeURIComponent(requestCode)}/learning` +
        `?seed=${query.seed}&runs=${query.runs}&response_stress=${query.stress}`,
      { signal },
    ),
};
