import { useEffect, useState } from "react";
import { ApiError } from "../services/apiClient";

export type QueryState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };

/** Runs `fetcher` whenever `key` changes and aborts stale requests. */
export function useApiQuery<T>(fetcher: (signal: AbortSignal) => Promise<T>, key: string): QueryState<T> {
  const [state, setState] = useState<{ key: string; value: QueryState<T> }>({ key, value: { status: "loading" } });

  useEffect(() => {
    const controller = new AbortController();
    fetcher(controller.signal)
      .then((data) => setState({ key, value: { status: "success", data } }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError = error instanceof ApiError ? error : new ApiError("Unexpected error while loading data.");
        setState({ key, value: { status: "error", error: apiError } });
      });
    return () => controller.abort();
    // `fetcher` is recreated on every render; `key` identifies what it fetches.
  }, [key]);

  return state.key === key ? state.value : { status: "loading" };
}
