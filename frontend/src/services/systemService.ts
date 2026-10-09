import { config } from "../lib/config";
import type { DatasetStats, HealthResponse, SystemStatusResponse } from "../types/api";
import { apiClient } from "./apiClient";

export const systemService = {
  getHealth: (signal?: AbortSignal) => apiClient.get<HealthResponse>("/health", { signal }),
  getStatus: (signal?: AbortSignal) =>
    apiClient.get<SystemStatusResponse>(`${config.apiPrefix}/system/status`, { signal }),
  getDatasetStats: (signal?: AbortSignal) =>
    apiClient.get<DatasetStats>(`${config.apiPrefix}/system/dataset-stats`, { signal }),
};
