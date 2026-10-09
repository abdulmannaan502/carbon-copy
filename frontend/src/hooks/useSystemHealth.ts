import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router";
import { ApiError } from "../services/apiClient";
import { systemService } from "../services/systemService";
import type { HealthResponse, SystemStatusResponse } from "../types/api";

export type ConnectionState = "checking" | "online" | "degraded" | "offline";

export interface SystemHealth {
  state: ConnectionState;
  health: HealthResponse | null;
  status: SystemStatusResponse | null;
  latencyMs: number | null;
  lastCheckedAt: Date | null;
  error: string | null;
  refresh: () => void;
}

type Snapshot = Omit<SystemHealth, "refresh">;

const INITIAL: Snapshot = {
  state: "checking",
  health: null,
  status: null,
  latencyMs: null,
  lastCheckedAt: null,
  error: null,
};

/** Polls the backend and reports connectivity, database and AI-layer state. */
export function useSystemHealth(pollIntervalMs: number): SystemHealth {
  const [snapshot, setSnapshot] = useState<Snapshot>(INITIAL);
  const [manualChecks, setManualChecks] = useState(0);
  const refresh = useCallback(() => setManualChecks((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();

    const check = async () => {
      const startedAt = performance.now();
      try {
        const [health, status] = await Promise.all([
          systemService.getHealth(controller.signal),
          systemService.getStatus(controller.signal),
        ]);
        setSnapshot({
          state: health.status === "ok" ? "online" : "degraded",
          health,
          status,
          latencyMs: Math.round(performance.now() - startedAt),
          lastCheckedAt: new Date(),
          error: null,
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        setSnapshot({
          ...INITIAL,
          state: "offline",
          lastCheckedAt: new Date(),
          error: error instanceof ApiError ? error.message : "Unexpected error while contacting the API.",
        });
      }
    };

    void check();
    const intervalId = window.setInterval(() => void check(), pollIntervalMs);
    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [pollIntervalMs, manualChecks]);

  return { ...snapshot, refresh };
}

/** Health state shared by AppLayout with every routed page. */
export function useLayoutHealth(): SystemHealth {
  return useOutletContext<SystemHealth>();
}
