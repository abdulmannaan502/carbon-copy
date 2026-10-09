import { config } from "../lib/config";

const DEFAULT_TIMEOUT_MS = 5_000;

export class ApiError extends Error {
  readonly status: number | null;
  /** The backend's `detail` message when it sent one (validation and conflict errors), else null. */
  readonly detail: string | null;

  constructor(message: string, status: number | null = null, detail: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

/** FastAPI errors carry `detail` as a string, or as a list of validation problems. */
async function readDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string };
          return `${(entry.loc ?? []).filter((part) => part !== "query" && part !== "body").join(".")}: ${entry.msg ?? "invalid"}`;
        })
        .join("; ");
    }
  } catch {
    // Not JSON: fall back to the status line.
  }
  return null;
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const timeout = AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}${path}`, {
      method,
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (timeout.aborted) throw new ApiError("The API did not respond in time.");
    if (options.signal?.aborted) throw error;
    throw new ApiError(`Cannot reach the API at ${config.apiBaseUrl}.`);
  }

  if (!response.ok) {
    throw new ApiError(`API request failed: ${response.status} ${response.statusText}`, response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, options?: RequestOptions) => request<T>("POST", path, options),
  patch: <T>(path: string, options?: RequestOptions) => request<T>("PATCH", path, options),
};
