import { config } from "../lib/config";
import type { DigitalTwinState, Page, PatientListItem } from "../types/twin";
import { apiClient } from "./apiClient";

const MAX_PAGE_SIZE = 100;

export const patientService = {
  /** The synthetic dataset has 80 patients, so one page holds them all. */
  listPatients: (signal?: AbortSignal) =>
    apiClient.get<Page<PatientListItem>>(`${config.apiPrefix}/patients?page=1&page_size=${MAX_PAGE_SIZE}`, { signal }),
  getDigitalTwin: (patientCode: string, signal?: AbortSignal) =>
    apiClient.get<DigitalTwinState>(`${config.apiPrefix}/patients/${encodeURIComponent(patientCode)}/digital-twin`, {
      signal,
    }),
};
