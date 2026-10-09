import { config } from "../lib/config";
import type { DonorComparison, DonorListItem, DonorRequestAssessment, DonorStateAssessment, EvaluateAt } from "../types/donorState";
import type { Page } from "../types/twin";
import { apiClient } from "./apiClient";

const enc = encodeURIComponent;

export const donorService = {
  listDonors: (page: number, pageSize: number, signal?: AbortSignal) =>
    apiClient.get<Page<DonorListItem>>(`${config.apiPrefix}/donors?page=${page}&page_size=${pageSize}`, { signal }),
  getState: (donorCode: string, signal?: AbortSignal) =>
    apiClient.get<DonorStateAssessment>(`${config.apiPrefix}/donors/${enc(donorCode)}/state`, { signal }),
  getStateForRequest: (donorCode: string, requestCode: string, evaluateAt: EvaluateAt, signal?: AbortSignal) =>
    apiClient.get<DonorRequestAssessment>(
      `${config.apiPrefix}/donors/${enc(donorCode)}/state-for-request/${enc(requestCode)}?evaluate_at=${evaluateAt}`,
      { signal },
    ),
  /** Without `donorCodes`, the backend compares the donors the request's cascade contacted. */
  compareForRequest: (requestCode: string, evaluateAt: EvaluateAt, donorCodes?: string[], signal?: AbortSignal) => {
    const codes = donorCodes?.length ? `&donor_codes=${enc(donorCodes.join(","))}` : "";
    return apiClient.get<DonorComparison>(
      `${config.apiPrefix}/requests/${enc(requestCode)}/donor-comparison?evaluate_at=${evaluateAt}${codes}`,
      { signal },
    );
  },
};
