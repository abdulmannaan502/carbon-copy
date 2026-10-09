import { config } from "../lib/config";
import type {
  NotificationDispatchReport,
  NotificationFilters,
  NotificationItem,
  NotificationPage,
  NotificationSummary,
  RequestListItem,
  SimulationSettings,
} from "../types/notifications";
import type { Page } from "../types/twin";
import { apiClient } from "./apiClient";

const base = `${config.apiPrefix}/notifications`;

/** Only filters the backend supports; empty values are left out of the query. */
function filterParams(filters: NotificationFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.recipientRole) params.set("recipient_role", filters.recipientRole);
  if (filters.status) params.set("status", filters.status);
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.requestCode.trim()) params.set("request_code", filters.requestCode.trim());
  if (filters.unreadOnly) params.set("unread_only", "true");
  return params;
}

export const notificationService = {
  list: (filters: NotificationFilters, page: number, pageSize: number, signal?: AbortSignal) => {
    const params = filterParams(filters);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return apiClient.get<NotificationPage>(`${base}?${params.toString()}`, { signal });
  },
  summary: (filters: NotificationFilters, signal?: AbortSignal) => {
    const query = filterParams(filters).toString();
    return apiClient.get<NotificationSummary>(`${base}/summary${query ? `?${query}` : ""}`, { signal });
  },
  markRead: (notificationId: string) => apiClient.patch<NotificationItem>(`${base}/${encodeURIComponent(notificationId)}/read`),
  /** Runs the deterministic simulation and records its events as DEMO notifications. Explicit POST only. */
  recordSimulation: (settings: SimulationSettings) => {
    const params = new URLSearchParams({
      seed: String(settings.seed),
      response_stress: settings.stress,
      max_waves: String(settings.maxWaves),
      evaluate_at: "auto",
    });
    if (settings.waveSize !== null) params.set("wave_size", String(settings.waveSize));
    return apiClient.post<NotificationDispatchReport>(
      `${config.apiPrefix}/requests/${encodeURIComponent(settings.requestCode)}/cascade/notifications?${params.toString()}`,
      { timeoutMs: 30_000 },
    );
  },
  /** Backend code search (GET /requests?search=), one small page; never the whole dataset. */
  findRequests: (search: string, limit: number, signal?: AbortSignal) => {
    const params = new URLSearchParams({ page: "1", page_size: String(limit) });
    if (search) params.set("search", search);
    return apiClient.get<Page<RequestListItem>>(`${config.apiPrefix}/requests?${params.toString()}`, { signal });
  },
};
