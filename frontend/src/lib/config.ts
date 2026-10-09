export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  apiPrefix: "/api/v1",
  healthPollIntervalMs: 15_000,
} as const;
