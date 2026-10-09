import { config } from "../lib/config";
import type { IndividualFailureAutopsy, RequestAutopsy } from "../types/failureAutopsy";
import { apiClient } from "./apiClient";

const enc = encodeURIComponent;

export const failureAutopsyService = {
  /** RECORDED: analyses every Failure row attached to this request's coordination attempts
   * ("what actually happened" in the synthetic dataset — never the simulated cascade). */
  getRequestAutopsy: (requestCode: string, signal?: AbortSignal) =>
    apiClient.get<RequestAutopsy>(`${config.apiPrefix}/requests/${enc(requestCode)}/failures/autopsy`, { signal }),
  getSingleFailureAutopsy: (requestCode: string, failureCode: string, signal?: AbortSignal) =>
    apiClient.get<IndividualFailureAutopsy>(
      `${config.apiPrefix}/requests/${enc(requestCode)}/failures/${enc(failureCode)}/autopsy`,
      { signal },
    ),
};
